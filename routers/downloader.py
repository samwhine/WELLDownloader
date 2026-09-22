# ================================================================
# WELL Downloader — yt-dlp media router
# ================================================================
from fastapi import APIRouter, Request
from fastapi.responses import Response, FileResponse, JSONResponse
import yt_dlp
import importlib.metadata as metadata
import os, threading, uuid, shutil, requests as req_lib
import re, zipfile, urllib.parse, time

router = APIRouter()
FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "temp", "downloader"))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
progress_store = {}
_version_cache = {"checked_at": 0, "latest": None, "error": None}
CACHE_TTL_SECONDS = int(os.getenv("WELL_DOWNLOAD_TTL_HOURS", "4")) * 3600

BLOCKED_PLATFORMS = {
    "instagram.com": {"name":"Instagram", "reason":"requires cookies/login for most posts", "tip":"Instagram is intentionally not supported in WELL Downloader."},
    "spotify.com": {"name":"Spotify", "reason":"DRM protected", "tip":"Use an official offline download feature instead."},
    "music.apple.com": {"name":"Apple Music", "reason":"FairPlay DRM protected", "tip":"Use an official offline download feature instead."},
    "deezer.com": {"name":"Deezer", "reason":"login/DRM protected", "tip":"Use an official offline download feature instead."},
    "tidal.com": {"name":"Tidal", "reason":"login/DRM protected", "tip":"Use an official offline download feature instead."},
    "netflix.com": {"name":"Netflix", "reason":"Widevine DRM protected", "tip":"Use the official Netflix app download feature."},
    "primevideo.com": {"name":"Amazon Prime Video", "reason":"DRM protected", "tip":"Use the official Prime Video app download feature."},
    "disneyplus.com": {"name":"Disney+", "reason":"DRM protected", "tip":"Use the official Disney+ app download feature."},
    "hbo.com": {"name":"HBO / Max", "reason":"DRM protected", "tip":"Use the official Max app download feature."},
    "hbomax.com": {"name":"HBO Max", "reason":"DRM protected", "tip":"Use the official Max app download feature."},
    "max.com": {"name":"Max", "reason":"DRM protected", "tip":"Use the official Max app download feature."},
    "crunchyroll.com": {"name":"Crunchyroll", "reason":"login/DRM protected", "tip":"Use the official service download feature."},
}

BROWSER_HEADERS = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language":"en-US,en;q=0.9"}
TIKTOK_HEADERS = {**BROWSER_HEADERS, "Referer":"https://www.tiktok.com/"}

def check_blocked_platform(url):
    low = url.lower()
    for domain, info in BLOCKED_PLATFORMS.items():
        if domain in low: return info
    return None

def headers_for(url):
    return TIKTOK_HEADERS if "tiktok.com" in url.lower() else BROWSER_HEADERS

def format_speed(speed):
    if not speed: return ""
    for unit, div in (("GB/s",1024**3),("MB/s",1024**2),("KB/s",1024),("B/s",1)):
        if speed >= div: return f"{speed/div:.1f} {unit}"
    return "0 B/s"

def format_bytes(value):
    if not value: return "0 B"
    for unit, div in (("GB",1024**3),("MB",1024**2),("KB",1024),("B",1)):
        if value >= div: return f"{value/div:.2f} {unit}" if unit in ("GB","MB") else f"{value/div:.0f} {unit}"
    return "0 B"

def safe_name(name): return (re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip('. ')[:120] or "download")
def is_image_url(url): return any(url.split('?')[0].lower().endswith(x) for x in ('.jpg','.jpeg','.png','.gif','.webp','.bmp','.tiff'))
def proxy_url(url): return f"/api/downloader/proxy-image?url={urllib.parse.quote(url,safe='')}" if url else ""
def unwrap(url): return urllib.parse.unquote(url.split('?url=',1)[1]) if '/api/downloader/proxy-image?url=' in url else url

def build_opts(url, extra=None):
    opts={"quiet":True,"no_warnings":True,"http_headers":headers_for(url),"retries":5,"fragment_retries":5,"socket_timeout":30}
    if os.path.isfile(FFMPEG_PATH): opts["ffmpeg_location"]=FFMPEG_PATH
    if extra: opts.update(extra)
    return opts

def progress_hook(task_id):
    def hook(d):
        if d['status']=='downloading':
            total=d.get('total_bytes') or d.get('total_bytes_estimate') or 0; got=d.get('downloaded_bytes',0)
            progress_store[task_id].update(status='downloading',percent=round(got/total*100,1) if total else 0,speed=format_speed(d.get('speed') or 0),eta=d.get('eta') or 0,downloaded=format_bytes(got),total=format_bytes(total),step='Downloading…',_ts=time.time())
        elif d['status']=='finished': progress_store[task_id].update(status='processing',percent=99,step='Merging / packaging…',_ts=time.time())
    return hook

def friendly_error(message,url):
    m=message.lower()
    if 'login' in m or 'sign in' in m: return '❌ This content requires login/cookies or is private.'
    if 'private' in m: return '❌ Private content cannot be downloaded.'
    if '429' in m or 'rate limit' in m: return '❌ The platform is rate-limiting requests. Please try again in a few minutes.'
    if 'ffmpeg' in m: return '❌ FFmpeg is not available. Install FFmpeg to merge video and audio.'
    if 'playlist' in m: return '❌ Paste a single post or video URL, not a playlist or radio URL.'
    if 'unsupported' in m or 'extractor' in m: return '❌ This URL is not supported by yt-dlp.'
    return f'❌ Download failed: {message}'

def best_thumbnails(info, limit=8):
    arr=sorted([x for x in info.get('thumbnails',[]) if x.get('url')],key=lambda x:(x.get('width') or 0)*(x.get('height') or 0),reverse=True); seen=set(); out=[]
    for t in arr:
        if t['url'] in seen: continue
        seen.add(t['url']); out.append({'url':proxy_url(t['url']),'raw_url':t['url'],'width':t.get('width'),'height':t.get('height'),'label':f"{t.get('width')}×{t.get('height')}" if t.get('width') and t.get('height') else 'Best available'})
    return out[:limit]

def image_entry(e,i):
    formats=e.get('formats') or []; candidates=[f for f in formats if f.get('url') and (f.get('vcodec') or 'none')=='none' and (f.get('acodec') or 'none')=='none'] or [f for f in formats if f.get('url')]
    raw=(max(candidates,key=lambda f:(f.get('width') or 0)*(f.get('height') or 0)).get('url') if candidates else '') or e.get('url') or ''
    thumb=e.get('thumbnail') or raw; ext=e.get('ext') or 'jpg'
    return {'index':i,'url':proxy_url(raw),'thumbnail':proxy_url(thumb),'raw_url':raw,'ext':ext,'width':e.get('width'),'height':e.get('height'),'title':e.get('title') or f'Image {i+1}'}

def cleanup_expired_downloads():
    """Remove finished/error tasks older than the configured TTL."""
    now = time.time()
    for task_id, task in list(progress_store.items()):
        age = now - task.get('_ts', now)
        if age > CACHE_TTL_SECONDS and task.get('status') not in ('pending', 'downloading', 'processing'):
            shutil.rmtree(os.path.join(DOWNLOAD_DIR, task_id), ignore_errors=True)
            progress_store.pop(task_id, None)
    # Also clean orphaned folders left by a previous server process.
    for task_id in os.listdir(DOWNLOAD_DIR):
        folder = os.path.join(DOWNLOAD_DIR, task_id)
        if not os.path.isdir(folder) or task_id in progress_store:
            continue
        try:
            if now - os.path.getmtime(folder) > CACHE_TTL_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass

def _cache_reaper():
    while True:
        try:
            cleanup_expired_downloads()
        except Exception:
            pass
        time.sleep(600)

threading.Thread(target=_cache_reaper, daemon=True).start()

@router.get('/status')
async def status(): return {'server':'WELL Downloader','version':'2.0.0','ffmpeg_found':shutil.which('ffmpeg') is not None}

@router.get('/yt-dlp-version')
async def ytdlp_version():
    """Return current venv version plus PyPI latest; UI keeps warning until this matches."""
    try:
        current = metadata.version('yt-dlp')
    except metadata.PackageNotFoundError:
        current = getattr(yt_dlp.version, '__version__', 'unknown')
    now = time.time()
    if now - _version_cache['checked_at'] > 300 or not _version_cache['latest']:
        try:
            response = req_lib.get('https://pypi.org/pypi/yt-dlp/json', timeout=8)
            response.raise_for_status()
            _version_cache.update(checked_at=now, latest=response.json().get('info', {}).get('version'), error=None)
        except Exception as exc:
            _version_cache.update(checked_at=now, error=str(exc))
    latest = _version_cache.get('latest')
    outdated = bool(latest and current != latest)
    return {'current': current, 'latest': latest, 'outdated': outdated, 'check_error': _version_cache.get('error')}

@router.get('/rules')
async def rules(): return {'supported':['YouTube','TikTok video','TikTok photo/carousel','Telegram public posts','Pinterest public pins','yt-dlp supported public platforms'],'blocked':list(BLOCKED_PLATFORMS)}

@router.get('/proxy-image')
async def proxy_image(url:str=''):
    if not url.startswith(('http://','https://')): return Response('Invalid URL',status_code=400)
    try:
        r=req_lib.get(url,timeout=20,headers=headers_for(url));r.raise_for_status();return Response(r.content,media_type=r.headers.get('content-type','image/jpeg'),headers={'Cache-Control':'public, max-age=3600'})
    except Exception as e:return Response(f'Proxy error: {e}',status_code=502)

@router.post('/info')
async def info_route(request:Request):
    data=await request.json();url=(data.get('url') or '').strip()
    if not url:return JSONResponse({'error':'URL cannot be empty'},status_code=400)
    blocked=check_blocked_platform(url)
    if blocked:return JSONResponse({'error':f"❌ {blocked['name']} is not supported — {blocked['reason']}. {blocked['tip']}"},status_code=400)
    try:
        with yt_dlp.YoutubeDL(build_opts(url,{'extract_flat':'in_playlist'})) as ydl: flat=ydl.extract_info(url,download=False)
        gallery=flat.get('_type') in ('playlist','multi_video')
        if gallery:
            entries=flat.get('entries') or []
            images=[image_entry(e,i) for i,e in enumerate(entries) if e]
            return {'title':flat.get('title') or 'Photo gallery','thumbnail':images[0]['thumbnail'] if images else '','platform':flat.get('extractor_key',''),'uploader':flat.get('uploader',''),'content_type':'gallery','images':images,'count':len(images),'formats':[],'thumbnails':[],'url':url}
        with yt_dlp.YoutubeDL(build_opts(url)) as ydl: data_full=ydl.extract_info(url,download=False)
        formats=data_full.get('formats') or [];has_video=any((f.get('vcodec') or 'none')!='none' and f.get('height') for f in formats)
        if not formats and (data_full.get('ext') in ('jpg','jpeg','png','webp','gif') or is_image_url(data_full.get('url',''))):
            raw=data_full.get('url','');img=image_entry({**data_full,'url':raw},0);return {'title':data_full.get('title','Image'),'thumbnail':proxy_url(raw),'platform':data_full.get('extractor_key',''),'content_type':'image','images':[img],'count':1,'formats':[],'thumbnails':[],'url':url}
        out=[];seen=set()
        for f in formats:
            v=(f.get('vcodec') or 'none')!='none';a=(f.get('acodec') or 'none')!='none';h=f.get('height');abr=f.get('abr') or f.get('tbr')
            if v and h:
                key=(h,f.get('fps'),f.get('ext')); 
                if key not in seen: seen.add(key);out.append({'format_id':f.get('format_id',''),'type':'video','height':h,'quality':f'{h}p','label':f"{h}p · {(f.get('ext') or '').upper()}"})
            elif a and abr:
                key=('a',int(abr),f.get('ext'))
                if key not in seen: seen.add(key);out.append({'format_id':f.get('format_id',''),'type':'audio','abr':abr,'label':f"{int(abr)}kbps · {(f.get('ext') or '').upper()}"})
        raw=(best_thumbnails(data_full,1) or [{'raw_url':data_full.get('thumbnail','')}])[0].get('raw_url','')
        dur=int(data_full.get('duration') or 0);return {'title':data_full.get('title',''),'thumbnail':proxy_url(raw),'thumbnails':best_thumbnails(data_full),'duration':f'{dur//60}:{dur%60:02d}','uploader':data_full.get('uploader') or data_full.get('channel') or '','platform':data_full.get('extractor_key',''),'content_type':'video' if has_video else 'audio_only','images':[],'formats':out,'url':url}
    except yt_dlp.utils.DownloadError as e:return JSONResponse({'error':friendly_error(str(e),url)},status_code=400)
    except Exception as e:return JSONResponse({'error':f'Failed to fetch info: {e}'},status_code=500)

@router.post('/download')
async def download_route(request:Request):
    cleanup_expired_downloads()
    data=await request.json();url=(data.get('url') or '').strip();media=data.get('media_type','video');task=str(uuid.uuid4());folder=os.path.join(DOWNLOAD_DIR,task);os.makedirs(folder,exist_ok=True);progress_store[task]={'status':'pending','percent':0,'_ts':time.time()}
    def work():
        try:
            title=safe_name(data.get('title','download'))
            if media=='thumbnail':
                raw=unwrap(data.get('thumb_url',''));r=req_lib.get(raw,headers=headers_for(raw),timeout=30);r.raise_for_status();ext='png' if 'png' in r.headers.get('content-type','') else 'jpg';path=os.path.join(folder,f'{title}_thumbnail.{ext}');open(path,'wb').write(r.content)
            elif media=='image':
                paths=[]
                for i,raw0 in enumerate(data.get('image_urls',[]),1):
                    raw=unwrap(raw0);r=req_lib.get(raw,headers=headers_for(raw),timeout=30);r.raise_for_status();ext='jpg';ct=r.headers.get('content-type','');ext='png' if 'png' in ct else ('webp' if 'webp' in ct else 'jpg');path=os.path.join(folder,f'{title}_{i:02d}.{ext}');open(path,'wb').write(r.content);paths.append(path)
                if len(paths)>1:
                    archive=os.path.join(folder,f'{title}_photos.zip');
                    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                        for p in paths:z.write(p,os.path.basename(p))
                    path=archive
                elif paths:path=paths[0]
                else:raise Exception('No images selected')
            else:
                fmt='bestaudio/best' if media=='audio' else (f"{data.get('format_id')}+bestaudio/best" if data.get('format_id') else 'bestvideo+bestaudio/best');opts=build_opts(url,{'format':fmt,'outtmpl':os.path.join(folder,'%(title)s.%(ext)s'),'progress_hooks':[progress_hook(task)],'merge_output_format':'mp4' if media=='video' else None,'postprocessors':[{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'0'}] if media=='audio' else []});
                with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
                files=[os.path.join(folder,f) for f in os.listdir(folder) if not f.endswith(('.part','.ytdl'))];path=max(files,key=os.path.getsize)
            progress_store[task].update(status='done',percent=100,filename=os.path.basename(path),filepath=path,filesize=format_bytes(os.path.getsize(path)),title=title,_ts=time.time())
        except Exception as e:progress_store[task].update(status='error',message=friendly_error(str(e),url),_ts=time.time())
    threading.Thread(target=work,daemon=True).start();return {'task_id':task}

@router.get('/progress/{task_id}')
async def progress(task_id:str):return JSONResponse(progress_store.get(task_id,{'status':'not_found'}))
@router.get('/file/{task_id}')
async def file(task_id:str):
    d=progress_store.get(task_id,{});p=d.get('filepath','')
    if d.get('status')!='done' or not os.path.exists(p):return JSONResponse({'error':'File is not ready'},status_code=404)
    return FileResponse(p,filename=d.get('filename','download'))
@router.delete('/cleanup/{task_id}')
async def cleanup(task_id:str):
    shutil.rmtree(os.path.join(DOWNLOAD_DIR,task_id),ignore_errors=True);progress_store.pop(task_id,None);return {'ok':True}
