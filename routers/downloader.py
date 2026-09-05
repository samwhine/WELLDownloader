# ================================================================
#  WELL Suite — Downloader Router (migrated from Flask to FastAPI)
# ================================================================

from fastapi import APIRouter, Request
from fastapi.responses import Response, FileResponse, JSONResponse
import yt_dlp
import os, threading, uuid, shutil, requests as req_lib
import re, zipfile, urllib.parse, time

router = APIRouter()

# ─── CONFIG ──────────────────────────────────────────────────────
FFMPEG_PATH  = __import__('shutil').which("ffmpeg") or "ffmpeg"
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp", "downloader")
DOWNLOAD_DIR = os.path.abspath(DOWNLOAD_DIR)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
progress_store = {}

# ─── BLOCKED PLATFORMS ───────────────────────────────────────────
BLOCKED_PLATFORMS = {
    "spotify.com":      {"name": "Spotify",       "reason": "Uses Widevine DRM encryption — cannot be bypassed.",        "tip": "Try searching for the same track on YouTube Music or SoundCloud."},
    "music.apple.com":  {"name": "Apple Music",   "reason": "Uses FairPlay DRM — audio cannot be extracted.",            "tip": "Try searching for the same track on YouTube Music or SoundCloud."},
    "deezer.com":       {"name": "Deezer",         "reason": "Premium tracks require login and use DRM.",                 "tip": "Try searching for the same track on YouTube Music or SoundCloud."},
    "tidal.com":        {"name": "Tidal",          "reason": "Requires premium login and uses DRM encryption.",           "tip": "Try searching for the same track on YouTube Music or SoundCloud."},
    "netflix.com":      {"name": "Netflix",        "reason": "Uses Widevine DRM L1 — streams cannot be captured.",       "tip": "Use the official download feature in the Netflix app."},
    "primevideo.com":   {"name": "Amazon Prime",   "reason": "Uses DRM — streams cannot be captured.",                   "tip": "Use the official download feature in the Prime Video app."},
    "disneyplus.com":   {"name": "Disney+",        "reason": "Uses DRM — streams cannot be captured.",                   "tip": "Use the official download feature in the Disney+ app."},
    "hbo.com":          {"name": "HBO / Max",      "reason": "Uses DRM — streams cannot be captured.",                   "tip": "Use the official download feature in the Max app."},
    "hbomax.com":       {"name": "HBO Max",        "reason": "Uses DRM — streams cannot be captured.",                   "tip": "Use the official download feature in the Max app."},
    "max.com":          {"name": "Max (HBO)",      "reason": "Uses DRM — streams cannot be captured.",                   "tip": "Use the official download feature in the Max app."},
    "crunchyroll.com":  {"name": "Crunchyroll",    "reason": "Premium content requires login and uses DRM.",             "tip": "Try searching on YouTube or other free platforms."},
}

LOGIN_REQUIRED_PLATFORMS = {
    "instagram.com": {"name": "Instagram", "reason": "Instagram blocks unauthenticated access for most content since 2024.", "tip": "Public Reels may still work. Stories and private content will fail.", "soft_block": True},
    "facebook.com":  {"name": "Facebook",  "reason": "Facebook requires login for most video content.",                     "tip": "Try a public Facebook video URL — some public posts still work.",   "soft_block": True},
}

def check_blocked_platform(url):
    url_lower = url.lower()
    for domain, info in BLOCKED_PLATFORMS.items():
        if domain in url_lower:
            return "hard", info
    for domain, info in LOGIN_REQUIRED_PLATFORMS.items():
        if domain in url_lower:
            return "soft", info
    return None, None

# ─── HELPERS ─────────────────────────────────────────────────────
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}
TIKTOK_HEADERS  = {**BROWSER_HEADERS, "Referer": "https://www.tiktok.com/"}
TWITTER_HEADERS = {**BROWSER_HEADERS, "Referer": "https://x.com/"}
REDDIT_HEADERS  = {**BROWSER_HEADERS, "Referer": "https://www.reddit.com/"}

def get_headers_for_url(url):
    if "tiktok.com" in url or "tiktokcdn.com" in url: return TIKTOK_HEADERS
    if "twitter.com" in url or "x.com" in url:         return TWITTER_HEADERS
    if "reddit.com" in url or "redd.it" in url:        return REDDIT_HEADERS
    return BROWSER_HEADERS

def format_speed(speed):
    if not speed: return ""
    for unit, div in [("GB/s", 1024**3), ("MB/s", 1024**2), ("KB/s", 1024), ("B/s", 1)]:
        if speed >= div:
            return f"{speed/div:.1f} {unit}"
    return "0 B/s"

def format_bytes(b):
    if not b: return "0 B"
    for unit, div in [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024), ("B", 1)]:
        if b >= div:
            val = b / div
            return f"{val:.2f} {unit}" if unit in ("GB", "MB") else f"{val:.0f} {unit}"
    return "0 B"

def safe_win_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    return name[:120] or "download"

def get_progress_hook(task_id, is_youtube=False):
    stream_count = [0]
    def hook(d):
        s = d["status"]
        if s == "downloading" and progress_store.get(task_id, {}).get("cancelled"):
            raise Exception("Cancelled by user")
        if s == "downloading":
            total      = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed      = d.get("speed") or 0
            eta        = d.get("eta") or 0
            pct        = round(downloaded / total * 100, 1) if total > 0 else 0
            step = ("Downloading video stream..." if stream_count[0] == 0 else "Downloading audio stream...") if is_youtube else "Downloading..."
            progress_store[task_id].update({"status": "downloading", "percent": pct, "speed": format_speed(speed), "eta": int(eta), "downloaded": format_bytes(downloaded), "total": format_bytes(total), "step": step, "_ts": time.time()})
        elif s == "finished":
            stream_count[0] += 1
            progress_store[task_id].update({"status": "processing", "percent": 99, "speed": "", "eta": 0, "step": "Merging streams..."})
        elif s == "error":
            progress_store[task_id].update({"status": "error", "message": str(d.get("error", "Unknown"))})
    return hook

def is_image_url(url):
    clean = url.split('?')[0].lower()
    return any(clean.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'))

def detect_content_type(info):
    _type = info.get("_type", "")
    if _type in ("playlist", "multi_video"): return "gallery"
    formats  = info.get("formats", [])
    has_video = any((f.get("vcodec") or "none") != "none" and f.get("height") for f in formats)
    if not formats:
        url_direct = info.get("url", "")
        ext = info.get("ext", "")
        if ext in ("jpg", "jpeg", "png", "webp", "gif", "bmp") or is_image_url(url_direct):
            return "image"
        return "video"
    if has_video: return "video"
    has_audio = any((f.get("acodec") or "none") != "none" for f in formats)
    return "audio_only" if has_audio else "video"

def build_ydl_opts(extra=None):
    opts = {"quiet": True, "no_warnings": True, "http_headers": BROWSER_HEADERS, "retries": 5, "fragment_retries": 5, "socket_timeout": 30}
    if os.path.isfile(FFMPEG_PATH): opts["ffmpeg_location"] = FFMPEG_PATH
    if extra: opts.update(extra)
    return opts

def build_ydl_opts_for_url(url, extra=None):
    opts = build_ydl_opts(extra)
    if "tiktok.com" in url:                        opts["http_headers"] = TIKTOK_HEADERS
    elif "twitter.com" in url or "x.com" in url:  opts["http_headers"] = TWITTER_HEADERS
    elif "reddit.com" in url or "redd.it" in url: opts["http_headers"] = REDDIT_HEADERS
    # NOTE: deliberately NOT forcing a youtube player_client here.
    # YouTube and yt-dlp are in an active, fast-moving back-and-forth
    # (SABR streaming / PO token requirements, changing almost weekly as of
    # 2026) over which client works at any given time — "android" gets
    # capped to 360p, "tv" started throwing "The page needs to be reloaded",
    # etc. Hardcoding a client list here just fights yt-dlp's own default
    # selection, which its maintainers update constantly to react to
    # whatever YouTube changed that week. Since _auto_update_ytdlp() in
    # main.py keeps yt-dlp itself current on every app startup, letting it
    # use its own default client logic is the most durable fix — no
    # override needed.
    return opts

def fetch_image(url):
    headers = get_headers_for_url(url)
    for attempt in range(3):
        try:
            r = req_lib.get(url, timeout=30, headers=headers, allow_redirects=True)
            r.raise_for_status()
            ct = r.headers.get("content-type", "image/jpeg")
            return r.content, ct
        except Exception as e:
            if attempt == 2: raise
            time.sleep(1)

def proxy_url(u):
    if not u: return u
    return f"/api/downloader/proxy-image?url={urllib.parse.quote(u, safe='')}"

def unwrap_proxy(u):
    if u and "/api/downloader/proxy-image?url=" in u:
        return urllib.parse.unquote(u.split("?url=", 1)[1])
    return u

def best_thumbnails(info, limit=8):
    thumbs_raw = info.get("thumbnails") or []
    thumbs_sorted = sorted([t for t in thumbs_raw if t.get("url")], key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
    seen_t, thumbs = set(), []
    for t in thumbs_sorted:
        u = t.get("url", "")
        if u and u not in seen_t:
            seen_t.add(u)
            w, h = t.get("width"), t.get("height")
            thumbs.append({"url": proxy_url(u), "raw_url": u, "width": w, "height": h, "label": f"{w}×{h}" if w and h else "Best Available"})
    return thumbs[:limit]

def friendly_error(msg, url=""):
    m = msg.lower()
    platform = _detect_platform(url) if url else "Unknown"

    if "sign in" in m or "login" in m:
        reason = f"[{platform}] Login required — content needs authentication."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}\n       Raw: {msg}")
        return f"❌ Login required. This content needs authentication and cannot be downloaded publicly."
    if "private" in m:
        reason = f"[{platform}] Private content — access denied."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}")
        return "❌ This content is private and cannot be downloaded."
    if "not available" in m or "unavailable" in m:
        reason = f"[{platform}] Content unavailable or deleted."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}")
        return "❌ Content is unavailable or has been deleted."
    if "429" in m or "rate limit" in m:
        reason = f"[{platform}] Rate limited by platform."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}")
        return "❌ Rate limited by platform. Please wait a few minutes and try again."
    if "404" in m:
        reason = f"[{platform}] Content not found (404)."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}")
        return "❌ Content not found (404). Please check the URL."
    if "403" in m:
        reason = f"[{platform}] Access denied (403) — geo-restricted or login needed."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}")
        return "❌ Access denied (403). Content may be geo-restricted or require login."
    if "geo" in m or "region" in m:
        reason = f"[{platform}] Geo-restricted content."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}")
        return "❌ Content is not available in your region."
    if "copyright" in m:
        reason = f"[{platform}] Content removed due to copyright."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}")
        return "❌ Content has been removed due to a copyright claim."
    if "ffmpeg" in m:
        print(f"  [!!] DOWNLOADER ERROR: FFmpeg not found on this system!")
        return "❌ FFmpeg not found. Make sure FFmpeg is installed and added to your system PATH."
    if "unsupported url" in m or "no suitable" in m or "extractor" in m:
        reason = f"[{platform}] Unsupported URL or platform."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}\n       Raw: {msg}")
        return f"❌ This URL is not supported. WELL Downloader supports YouTube, TikTok, Twitter/X, Reddit, SoundCloud, Vimeo, Bilibili, and 1000+ other platforms — but not all sites work."
    if "playlist" in m:
        reason = f"[{platform}] Playlist URL not supported for direct download."
        print(f"  [!!] DOWNLOADER ERROR: {reason}\n       URL: {url}")
        return "❌ Playlist URLs are not supported. Please paste a single video URL instead."

    # Generic — log full error for debugging
    print(f"  [!!] DOWNLOADER ERROR [{platform}]: {msg}\n       URL: {url}")
    return f"❌ Download failed: {msg}"


def _detect_platform(url):
    url_l = url.lower()
    if "youtube.com" in url_l or "youtu.be" in url_l: return "YouTube"
    if "tiktok.com" in url_l:   return "TikTok"
    if "twitter.com" in url_l or "x.com" in url_l: return "Twitter/X"
    if "instagram.com" in url_l: return "Instagram"
    if "facebook.com" in url_l:  return "Facebook"
    if "reddit.com" in url_l or "redd.it" in url_l: return "Reddit"
    if "soundcloud.com" in url_l: return "SoundCloud"
    if "vimeo.com" in url_l:      return "Vimeo"
    if "bilibili.com" in url_l:   return "Bilibili"
    if "spotify.com" in url_l:    return "Spotify"
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or "Unknown"
    except Exception:
        return "Unknown" 

def _safe_cleanup(task_dir):
    try:
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
    except Exception:
        pass

def _handle_winerror32(task_id, task_dir, dl_info):
    time.sleep(1.5)
    try:
        files = [f for f in os.listdir(task_dir) if not f.endswith((".part", ".ytdl", ".jpg", ".png", ".webp", ".temp.mp4", ".temp.webm", ".temp.mkv"))]
        if files:
            files.sort(key=lambda f: os.path.getsize(os.path.join(task_dir, f)), reverse=True)
            fname = files[0]
            fpath = os.path.join(task_dir, fname)
            title = (dl_info or {}).get("title", "download")
            progress_store[task_id].update({"status": "done", "percent": 100, "filename": fname, "filepath": fpath, "filesize": format_bytes(os.path.getsize(fpath)), "title": title, "_ts": time.time()})
            return
    except Exception:
        pass
    progress_store[task_id].update({"status": "error", "message": "Windows file lock error. Please try again."})


# ─── ROUTES ──────────────────────────────────────────────────────

@router.get("/status")
async def status():
    ffmpeg_ok = __import__('shutil').which("ffmpeg") is not None
    return {"server": "WELL Suite Downloader", "ffmpeg": FFMPEG_PATH, "ffmpeg_found": ffmpeg_ok}


@router.get("/proxy-image")
async def proxy_image(url: str = ""):
    raw = url.strip()
    if not raw or not raw.startswith(("http://", "https://")):
        return Response("Invalid URL", status_code=400)
    try:
        headers = get_headers_for_url(raw)
        r = req_lib.get(raw, timeout=20, headers=headers, allow_redirects=True)
        r.raise_for_status()
        return Response(r.content, media_type=r.headers.get("content-type", "image/jpeg"), headers={"Cache-Control": "public, max-age=3600"})
    except Exception as e:
        return Response(f"Proxy error: {e}", status_code=502)


@router.post("/info")
async def api_info(request: Request):
    data = await request.json()
    url  = (data.get("url") or "").strip()
    if not url:
        return JSONResponse({"error": "URL cannot be empty"}, status_code=400)

    block_type, block_info = check_blocked_platform(url)
    if block_type == "hard":
        return JSONResponse({"error": f"❌ {block_info['name']} is not supported — {block_info['reason']} 💡 {block_info['tip']}"}, status_code=400)

    platform_warning = None
    if block_type == "soft":
        platform_warning = f"⚠️ {block_info['name']}: {block_info['reason']} {block_info['tip']}"

    try:
        flat_opts = build_ydl_opts_for_url(url, {"extract_flat": "in_playlist"})
        with yt_dlp.YoutubeDL(flat_opts) as ydl:
            info_flat = ydl.extract_info(url, download=False)

        is_gallery = info_flat.get("_type", "") in ("playlist", "multi_video")

        if is_gallery:
            info_full = info_flat
            try:
                with yt_dlp.YoutubeDL(build_ydl_opts_for_url(url)) as ydl:
                    info_full = ydl.extract_info(url, download=False)
            except Exception:
                pass

            entries_raw = info_full.get("entries") or info_flat.get("entries") or []
            images = []

            for i, e in enumerate(entries_raw):
                if not e: continue
                thumbs_e = sorted([t for t in (e.get("thumbnails") or []) if t.get("url")], key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
                thumb_raw = (thumbs_e[0]["url"] if thumbs_e else "") or e.get("thumbnail") or ""
                direct_url = ""
                fmts = e.get("formats") or []
                if fmts:
                    img_fmts = [f for f in fmts if (f.get("vcodec") or "none") == "none" and (f.get("acodec") or "none") == "none" and f.get("url")]
                    if not img_fmts: img_fmts = [f for f in fmts if f.get("url")]
                    if img_fmts:
                        best_f = max(img_fmts, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
                        direct_url = best_f.get("url", "")
                if not direct_url: direct_url = e.get("url") or ""
                if not direct_url:
                    entry_page = e.get("webpage_url") or ""
                    if entry_page.startswith("http"):
                        try:
                            with yt_dlp.YoutubeDL(build_ydl_opts_for_url(entry_page)) as ydl3:
                                re_e = ydl3.extract_info(entry_page, download=False)
                                re_fmts = re_e.get("formats") or []
                                if re_fmts: direct_url = re_fmts[-1].get("url", "")
                                if not direct_url: direct_url = re_e.get("url", "")
                        except Exception: pass
                ext = e.get("ext") or "jpg"
                url_no_qs = (direct_url or "").split("?")[0].split("/")[-1]
                if "." in url_no_qs:
                    maybe = url_no_qs.rsplit(".", 1)[-1].lower()
                    if maybe in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
                        ext = "jpg" if maybe == "jpeg" else maybe
                images.append({"index": i, "url": proxy_url(direct_url), "thumbnail": proxy_url(thumb_raw or direct_url), "raw_url": direct_url, "ext": ext, "width": e.get("width"), "height": e.get("height"), "title": e.get("title") or f"Image {i+1}"})

            uploader = info_full.get("uploader") or info_full.get("channel") or info_flat.get("uploader") or info_flat.get("channel") or ""
            cover = proxy_url(images[0]["raw_url"]) if images else ""
            return JSONResponse({"title": info_full.get("title") or info_flat.get("title") or uploader or "Gallery", "thumbnail": cover, "thumbnails": [], "duration": 0, "uploader": uploader, "view_count": info_full.get("view_count") or info_flat.get("view_count"), "platform": info_full.get("extractor_key") or info_flat.get("extractor_key") or "", "content_type": "gallery", "images": images, "formats": [], "url": url, "count": len(images), "warning": platform_warning})

        with yt_dlp.YoutubeDL(build_ydl_opts_for_url(url)) as ydl:
            info = ydl.extract_info(url, download=False)

        content_type = detect_content_type(info)

        if content_type == "image":
            direct_url = info.get("url", "")
            ext = info.get("ext", "jpg")
            return JSONResponse({"title": info.get("title", "Image"), "thumbnail": proxy_url(direct_url), "thumbnails": [], "duration": 0, "uploader": info.get("uploader") or "", "view_count": info.get("view_count"), "platform": info.get("extractor_key", ""), "content_type": "image", "images": [{"index": 0, "url": proxy_url(direct_url), "thumbnail": proxy_url(direct_url), "raw_url": direct_url, "ext": ext, "width": info.get("width"), "height": info.get("height"), "title": info.get("title", "Image")}], "formats": [], "url": url, "count": 1, "warning": platform_warning})

        formats, seen = [], set()
        for f in info.get("formats", []):
            fid = f.get("format_id", ""); ext = f.get("ext", "") or ""
            vcodec = f.get("vcodec") or "none"; acodec = f.get("acodec") or "none"
            height = f.get("height"); abr = f.get("abr") or f.get("tbr")
            filesize = f.get("filesize") or f.get("filesize_approx"); fps = f.get("fps")
            has_v = vcodec != "none"; has_a = acodec != "none"; tbr = f.get("tbr") or 0
            if has_v and height:
                fps_val = int(fps) if fps else 0
                key = f"v_{height}_{fps_val}_{ext}"
                if key not in seen:
                    seen.add(key)
                    fps_tag = f' {int(fps)}fps' if fps else ''
                    size_tag = f' · {format_bytes(filesize)}' if filesize else ''
                    # Never show 'no audio' — server always merges video+bestaudio via FFmpeg
                    formats.append({'format_id': fid, 'type': 'video', 'quality': f'{height}p', 'ext': ext, 'height': height, 'fps': int(fps) if fps else None, 'has_audio': has_a, 'filesize': format_bytes(filesize) if filesize else 'N/A', 'label': f'{height}p{fps_tag} · {ext.upper()}{size_tag}', 'tbr': tbr})
            elif not has_v and has_a:
                effective_abr = abr or tbr
                if effective_abr:
                    key = f"a_{int(effective_abr)}_{ext}"
                    if key not in seen:
                        seen.add(key)
                        formats.append({"format_id": fid, "type": "audio", "quality": f"{int(effective_abr)}kbps", "ext": ext, "abr": effective_abr, "filesize": format_bytes(filesize) if filesize else "N/A", "label": f"{int(effective_abr)}kbps · {ext.upper()}"})

        video_fmts = sorted([f for f in formats if f["type"] == "video"], key=lambda x: (x["height"], x.get("fps") or 0, x.get("tbr") or 0), reverse=True)
        audio_fmts = sorted([f for f in formats if f["type"] == "audio"], key=lambda x: x.get("abr", 0), reverse=True)
        thumbs = best_thumbnails(info)
        best_thumb_raw = thumbs[0]["raw_url"] if thumbs else (info.get("thumbnail") or "")

        duration = info.get("duration") or 0
        mins, secs = divmod(int(duration), 60)
        hours, mins = divmod(mins, 60)
        duration_str = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins}:{secs:02d}"

        return JSONResponse({"title": info.get("title", ""), "thumbnail": proxy_url(best_thumb_raw), "thumbnails": thumbs, "duration": duration_str, "duration_sec": int(duration), "uploader": info.get("uploader") or info.get("channel") or "", "view_count": info.get("view_count"), "platform": info.get("extractor_key", ""), "content_type": content_type, "images": [], "formats": sorted([f for f in video_fmts if f["ext"]=="mp4"], key=lambda x:(x["height"],x.get("fps") or 0),reverse=True) + sorted([f for f in video_fmts if f["ext"]!="mp4"], key=lambda x:(x["height"],x.get("fps") or 0),reverse=True) + audio_fmts, "url": url, "warning": platform_warning})

    except yt_dlp.utils.DownloadError as e:
        print(f"  [!!] DOWNLOADER /info ERROR [{_detect_platform(url)}]: {e}\n       URL: {url}")
        return JSONResponse({"error": friendly_error(str(e), url)}, status_code=400)
    except Exception as e:
        print(f"  [!!] DOWNLOADER /info UNEXPECTED [{_detect_platform(url)}]: {e}\n       URL: {url}")
        return JSONResponse({"error": f"Failed to fetch info: {e}"}, status_code=500)


@router.post("/download")
async def api_download(request: Request):
    data       = await request.json()
    url        = (data.get("url") or "").strip()
    media_type = data.get("media_type", "video")
    out_fmt    = (data.get("format") or "").lower().strip()
    format_id  = data.get("format_id", "")
    target_height = data.get("height", "")
    image_urls = data.get("image_urls", [])
    thumb_url  = (data.get("thumb_url") or "").strip()

    if not url:
        return JSONResponse({"error": "URL cannot be empty"}, status_code=400)

    task_id  = str(uuid.uuid4())
    task_dir = os.path.join(DOWNLOAD_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    progress_store[task_id] = {"status": "pending", "percent": 0, "_ts": time.time()}

    def do_download():
        dl_info = None
        try:
            # ── Thumbnail download — fetch image directly via HTTP ──
            if media_type == "thumbnail":
                raw_url = unwrap_proxy(thumb_url) if thumb_url else ""
                if not raw_url:
                    raise Exception("No thumbnail URL provided. Try fetching info again.")
                print(f"  [...] Downloading thumbnail: {raw_url[:80]}...")
                progress_store[task_id].update({"status": "downloading", "percent": 50, "step": "Downloading thumbnail..."})
                img_bytes, content_type = fetch_image(raw_url)
                # Detect extension from content-type or URL
                ext = "jpg"
                if "png" in content_type:  ext = "png"
                elif "webp" in content_type: ext = "webp"
                elif "gif" in content_type:  ext = "gif"
                else:
                    # Try detect from URL
                    url_clean = raw_url.split("?")[0].lower()
                    for e in ("png", "webp", "gif", "jpg", "jpeg"):
                        if url_clean.endswith(f".{e}"):
                            ext = "jpg" if e == "jpeg" else e
                            break
                title = safe_win_filename(data.get("title", "thumbnail"))
                fname = f"{title}_thumbnail.{ext}"
                fpath = os.path.join(task_dir, fname)
                with open(fpath, "wb") as f: f.write(img_bytes)
                print(f"  [OK]  Thumbnail saved: {fname} ({format_bytes(len(img_bytes))})")
                progress_store[task_id].update({"status": "done", "percent": 100, "filename": fname, "filepath": fpath, "filesize": format_bytes(os.path.getsize(fpath)), "title": data.get("title", "thumbnail")})
                return

            if media_type == "image" and image_urls:
                progress_store[task_id].update({"status": "downloading", "percent": 0, "step": "Downloading images..."})
                downloaded_files = []
                for i, img_url in enumerate(image_urls):
                    raw_url = unwrap_proxy(img_url)
                    if not raw_url: continue
                    try:
                        img_bytes, content_type = fetch_image(raw_url)
                        ext_guess = "jpg"
                        if "png" in content_type: ext_guess = "png"
                        elif "webp" in content_type: ext_guess = "webp"
                        elif "gif" in content_type: ext_guess = "gif"
                        fpath = os.path.join(task_dir, f"image_{i+1:03d}.{ext_guess}")
                        with open(fpath, "wb") as f: f.write(img_bytes)
                        downloaded_files.append(fpath)
                        pct = round((i + 1) / len(image_urls) * 95)
                        progress_store[task_id].update({"percent": pct, "step": f"Downloading image {i+1}/{len(image_urls)}..."})
                    except Exception: continue

                if not downloaded_files:
                    raise Exception("Failed to download images. CDN URLs may have expired — try fetching info again.")

                progress_store[task_id].update({"status": "processing", "percent": 99})
                if len(downloaded_files) == 1:
                    fpath = downloaded_files[0]
                    fname = os.path.basename(fpath)
                    progress_store[task_id].update({"status": "done", "percent": 100, "filename": fname, "filepath": fpath, "filesize": format_bytes(os.path.getsize(fpath)), "title": data.get("title", "image")})
                    return
                zip_name = safe_win_filename(data.get("title", "images")) + "_images.zip"
                zip_path = os.path.join(task_dir, zip_name)
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fp in downloaded_files: zf.write(fp, os.path.basename(fp))
                progress_store[task_id].update({"status": "done", "percent": 100, "filename": zip_name, "filepath": zip_path, "filesize": format_bytes(os.path.getsize(zip_path)), "title": data.get("title", "images"), "count": len(downloaded_files)})
                return

            is_youtube = "youtube.com" in url or "youtu.be" in url

            if media_type == "audio":
                codec = out_fmt if out_fmt in ("mp3", "m4a", "wav", "ogg", "opus", "flac") else "mp3"
                THUMB_SUPPORTED = {"mp3", "m4a", "ogg", "opus", "flac"}
                supports_thumb = codec in THUMB_SUPPORTED
                postprocessors = [{"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": "0"}, {"key": "FFmpegMetadata"}]
                if supports_thumb: postprocessors.append({"key": "EmbedThumbnail"})
                ydl_opts = build_ydl_opts_for_url(url, {"format": "bestaudio/best", "outtmpl": os.path.join(task_dir, "%(title)s.%(ext)s"), "progress_hooks": [get_progress_hook(task_id, is_youtube=False)], "windowsfilenames": True, "postprocessors": postprocessors, "writethumbnail": supports_thumb})
            else:
                if target_height and str(target_height).isdigit():
                    h = int(target_height)
                    fmt = f"bestvideo[height={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height={h}]+bestaudio/bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/bestvideo+bestaudio/best"
                elif format_id and format_id not in ("best", ""):
                    fmt = f"{format_id}+bestaudio[ext=m4a]/{format_id}+bestaudio/bestvideo+bestaudio/best"
                else:
                    fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
                merge_fmt = out_fmt if out_fmt in ("mp4", "mkv", "webm") else "mp4"
                ydl_opts = build_ydl_opts_for_url(url, {"format": fmt, "outtmpl": os.path.join(task_dir, "%(title)s.%(ext)s"), "progress_hooks": [get_progress_hook(task_id, is_youtube=is_youtube)], "merge_output_format": merge_fmt, "windowsfilenames": True, "keepvideo": False, "postprocessors": [{"key": "FFmpegMetadata"}]})

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                title = dl_info.get("title", "download")

            time.sleep(0.5)
            files = [f for f in os.listdir(task_dir) if not f.endswith((".part", ".ytdl", ".jpg", ".png", ".webp", ".temp.mp4", ".temp.webm", ".temp.mkv"))]
            if not files: raise Exception("Output file not found after download completed")
            files.sort(key=lambda f: os.path.getsize(os.path.join(task_dir, f)), reverse=True)
            fname = files[0]
            fpath = os.path.join(task_dir, fname)
            progress_store[task_id].update({"status": "done", "percent": 100, "filename": fname, "filepath": fpath, "filesize": format_bytes(os.path.getsize(fpath)), "title": title, "_ts": time.time()})

        except yt_dlp.utils.DownloadError as e:
            if progress_store.get(task_id, {}).get("cancelled"):
                progress_store[task_id].update({"status": "cancelled"})
                _safe_cleanup(task_dir)
            elif "WinError 32" in str(e) or "being used by another process" in str(e):
                _handle_winerror32(task_id, task_dir, dl_info)
            else:
                print(f"  [!!] DOWNLOADER /download ERROR [{_detect_platform(url)}]: {e}\n       URL: {url}")
                progress_store[task_id].update({"status": "error", "message": friendly_error(str(e), url)})
        except OSError as e:
            if "WinError 32" in str(e) or "being used by another process" in str(e):
                _handle_winerror32(task_id, task_dir, dl_info)
            else:
                progress_store[task_id].update({"status": "error", "message": str(e)})
        except Exception as e:
            if progress_store.get(task_id, {}).get("cancelled"):
                progress_store[task_id].update({"status": "cancelled"})
                _safe_cleanup(task_dir)
            elif "WinError 32" in str(e) or "being used by another process" in str(e):
                _handle_winerror32(task_id, task_dir, None)
            else:
                progress_store[task_id].update({"status": "error", "message": str(e)})

    threading.Thread(target=do_download, daemon=True).start()
    return JSONResponse({"task_id": task_id})


@router.post("/cancel/{task_id}")
async def api_cancel(task_id: str):
    if task_id in progress_store:
        progress_store[task_id]["cancelled"] = True
        return {"ok": True}
    return JSONResponse({"error": "Task not found"}, status_code=404)


@router.get("/progress/{task_id}")
async def api_progress(task_id: str):
    return JSONResponse(progress_store.get(task_id, {"status": "not_found"}))


@router.get("/file/{task_id}")
async def api_file(task_id: str):
    info = progress_store.get(task_id, {})
    if info.get("status") != "done":
        return JSONResponse({"error": "File is not ready yet"}, status_code=404)
    fpath = info.get("filepath", "")
    if not os.path.exists(fpath):
        return JSONResponse({"error": "File not found on server"}, status_code=404)
    return FileResponse(fpath, filename=info.get("filename", "download"))


@router.delete("/cleanup/{task_id}")
async def api_cleanup(task_id: str):
    task_dir = os.path.join(DOWNLOAD_DIR, task_id)
    if os.path.exists(task_dir):
        shutil.rmtree(task_dir, ignore_errors=True)
    progress_store.pop(task_id, None)
    return {"ok": True}
