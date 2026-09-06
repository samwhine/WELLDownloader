# ================================================================
#  WELL Downloader — Downloader Router
#  Streaming architecture: the server never writes files to disk.
#  It resolves the real media URL via yt-dlp, then pipes bytes straight
#  from the source to the browser in the same request/response. The
#  browser's own download manager shows progress -- there's no server-
#  side task/progress polling to keep in sync.
#
#  Why: this works identically on a normal server AND on serverless
#  platforms (Vercel etc.) where the filesystem is read-only and each
#  request can land on a different, short-lived instance -- so a
#  "save to disk, poll progress, fetch file later" flow (the old
#  design) can never work reliably there. Streaming sidesteps all of
#  that by never needing state to survive between requests.
#
#  Trade-off: merging separate video+audio streams or transcoding
#  audio to MP3 needs FFmpeg, which isn't available in serverless
#  environments. So:
#    - Video: only formats that already have video+audio combined in
#      one stream are offered (no merge needed).
#    - Audio: served in its native container (m4a/webm/opus) instead
#      of being transcoded to MP3.
#  On a real server with FFmpeg installed, this still all works fine --
#  it's simply a stricter, universally-compatible subset.
# ================================================================

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse, JSONResponse
import yt_dlp
import os, requests as req_lib
import re, io, zipfile, urllib.parse

router = APIRouter()

# CONFIG
import shutil as _shutil
FFMPEG_PATH = _shutil.which("ffmpeg") or "ffmpeg"

# BLOCKED PLATFORMS
BLOCKED_PLATFORMS = {
    "spotify.com":      {"name": "Spotify",       "reason": "Uses Widevine DRM encryption -- cannot be bypassed.",        "tip": "Try searching for the same track on YouTube Music or SoundCloud."},
    "music.apple.com":  {"name": "Apple Music",   "reason": "Uses FairPlay DRM -- audio cannot be extracted.",            "tip": "Try searching for the same track on YouTube Music or SoundCloud."},
    "deezer.com":       {"name": "Deezer",         "reason": "Premium tracks require login and use DRM.",                 "tip": "Try searching for the same track on YouTube Music or SoundCloud."},
    "tidal.com":        {"name": "Tidal",          "reason": "Requires premium login and uses DRM encryption.",           "tip": "Try searching for the same track on YouTube Music or SoundCloud."},
    "netflix.com":      {"name": "Netflix",        "reason": "Uses Widevine DRM L1 -- streams cannot be captured.",       "tip": "Use the official download feature in the Netflix app."},
    "primevideo.com":   {"name": "Amazon Prime",   "reason": "Uses DRM -- streams cannot be captured.",                   "tip": "Use the official download feature in the Prime Video app."},
    "disneyplus.com":   {"name": "Disney+",        "reason": "Uses DRM -- streams cannot be captured.",                   "tip": "Use the official download feature in the Disney+ app."},
    "hbo.com":          {"name": "HBO / Max",      "reason": "Uses DRM -- streams cannot be captured.",                   "tip": "Use the official download feature in the Max app."},
    "hbomax.com":       {"name": "HBO Max",        "reason": "Uses DRM -- streams cannot be captured.",                   "tip": "Use the official download feature in the Max app."},
    "max.com":          {"name": "Max (HBO)",      "reason": "Uses DRM -- streams cannot be captured.",                   "tip": "Use the official download feature in the Max app."},
    "crunchyroll.com":  {"name": "Crunchyroll",    "reason": "Premium content requires login and uses DRM.",             "tip": "Try searching on YouTube or other free platforms."},
}

LOGIN_REQUIRED_PLATFORMS = {
    "instagram.com": {"name": "Instagram", "reason": "Instagram blocks unauthenticated access for most content since 2024.", "tip": "Public Reels may still work. Stories and private content will fail.", "soft_block": True},
    "facebook.com":  {"name": "Facebook",  "reason": "Facebook requires login for most video content.",                     "tip": "Try a public Facebook video URL -- some public posts still work.",   "soft_block": True},
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

# HELPERS
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
    # Deliberately not forcing a youtube player_client -- see README.
    # yt-dlp's own default client selection (kept current via regular
    # `pip install -U yt-dlp` / requirements.txt bumps) reacts to
    # YouTube's frequent changes far better than a hardcoded override.
    return opts

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
            thumbs.append({"url": proxy_url(u), "raw_url": u, "width": w, "height": h, "label": f"{w}x{h}" if w and h else "Best Available"})
    return thumbs[:limit]

def friendly_error(msg, url=""):
    m = msg.lower()
    platform = _detect_platform(url) if url else "Unknown"

    if "sign in" in m or "login" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] Login required.\n       URL: {url}\n       Raw: {msg}")
        return "Login required. This content needs authentication and cannot be downloaded publicly."
    if "private" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] Private content.\n       URL: {url}")
        return "This content is private and cannot be downloaded."
    if "not available" in m or "unavailable" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] Content unavailable.\n       URL: {url}")
        return "Content is unavailable or has been deleted."
    if "429" in m or "rate limit" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] Rate limited.\n       URL: {url}")
        return "Rate limited by platform. Please wait a few minutes and try again."
    if "404" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] 404.\n       URL: {url}")
        return "Content not found (404). Please check the URL."
    if "403" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] 403.\n       URL: {url}")
        return "Access denied (403). Content may be geo-restricted or require login."
    if "geo" in m or "region" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] Geo-restricted.\n       URL: {url}")
        return "Content is not available in your region."
    if "copyright" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] Copyright claim.\n       URL: {url}")
        return "Content has been removed due to a copyright claim."
    if "unsupported url" in m or "no suitable" in m or "extractor" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] Unsupported URL.\n       URL: {url}\n       Raw: {msg}")
        return "This URL is not supported. WELL Downloader supports YouTube, TikTok, Twitter/X, Reddit, SoundCloud, Vimeo, Bilibili, and 1000+ other platforms -- but not all sites work."
    if "playlist" in m:
        print(f"  [!!] DOWNLOADER ERROR: [{platform}] Playlist URL.\n       URL: {url}")
        return "Playlist URLs are not supported. Please paste a single video URL instead."

    print(f"  [!!] DOWNLOADER ERROR [{platform}]: {msg}\n       URL: {url}")
    return f"Download failed: {msg}"

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


# STATUS

@router.get("/status")
async def status():
    ffmpeg_ok = _shutil.which("ffmpeg") is not None
    return {"server": "WELL Downloader", "ffmpeg": FFMPEG_PATH, "ffmpeg_found": ffmpeg_ok, "mode": "streaming"}


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


# INFO

@router.post("/info")
async def api_info(request: Request):
    data = await request.json()
    url  = (data.get("url") or "").strip()
    if not url:
        return JSONResponse({"error": "URL cannot be empty"}, status_code=400)

    block_type, block_info = check_blocked_platform(url)
    if block_type == "hard":
        return JSONResponse({"error": f"{block_info['name']} is not supported -- {block_info['reason']} Tip: {block_info['tip']}"}, status_code=400)

    platform_warning = None
    if block_type == "soft":
        platform_warning = f"{block_info['name']}: {block_info['reason']} {block_info['tip']}"

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

        # Build format list: ONLY combined (progressive) video streams --
        # these can be streamed straight through with no FFmpeg merge step.
        # Audio formats are offered in their native container.
        formats, seen = [], set()
        for f in info.get("formats", []):
            fid = f.get("format_id", ""); ext = f.get("ext", "") or ""
            vcodec = f.get("vcodec") or "none"; acodec = f.get("acodec") or "none"
            height = f.get("height"); abr = f.get("abr") or f.get("tbr")
            filesize = f.get("filesize") or f.get("filesize_approx"); fps = f.get("fps")
            has_v = vcodec != "none"; has_a = acodec != "none"; tbr = f.get("tbr") or 0

            if has_v and has_a and height:
                fps_val = int(fps) if fps else 0
                key = f"v_{height}_{fps_val}_{ext}"
                if key not in seen:
                    seen.add(key)
                    fps_tag = f' {int(fps)}fps' if fps else ''
                    size_tag = f' - {format_bytes(filesize)}' if filesize else ''
                    formats.append({'format_id': fid, 'type': 'video', 'quality': f'{height}p', 'ext': ext, 'height': height, 'fps': int(fps) if fps else None, 'filesize': format_bytes(filesize) if filesize else 'N/A', 'label': f'{height}p{fps_tag} - {ext.upper()}{size_tag}', 'tbr': tbr})
            elif not has_v and has_a:
                effective_abr = abr or tbr
                if effective_abr:
                    key = f"a_{int(effective_abr)}_{ext}"
                    if key not in seen:
                        seen.add(key)
                        formats.append({"format_id": fid, "type": "audio", "quality": f"{int(effective_abr)}kbps", "ext": ext, "abr": effective_abr, "filesize": format_bytes(filesize) if filesize else "N/A", "label": f"{int(effective_abr)}kbps - {ext.upper()}"})

        video_fmts = sorted([f for f in formats if f["type"] == "video"], key=lambda x: (x["height"], x.get("fps") or 0, x.get("tbr") or 0), reverse=True)
        audio_fmts = sorted([f for f in formats if f["type"] == "audio"], key=lambda x: x.get("abr", 0), reverse=True)

        if not video_fmts and detect_content_type(info) == "video":
            no_progressive_warning = "No single-file video quality available for this content -- only formats that need merging (which requires FFmpeg) were found."
            platform_warning = (platform_warning + " " + no_progressive_warning) if platform_warning else no_progressive_warning

        thumbs = best_thumbnails(info)
        best_thumb_raw = thumbs[0]["raw_url"] if thumbs else (info.get("thumbnail") or "")

        duration = info.get("duration") or 0
        mins, secs = divmod(int(duration), 60)
        hours, mins = divmod(mins, 60)
        duration_str = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins}:{secs:02d}"

        return JSONResponse({"title": info.get("title", ""), "thumbnail": proxy_url(best_thumb_raw), "thumbnails": thumbs, "duration": duration_str, "duration_sec": int(duration), "uploader": info.get("uploader") or info.get("channel") or "", "view_count": info.get("view_count"), "platform": info.get("extractor_key", ""), "content_type": content_type, "images": [], "formats": video_fmts + audio_fmts, "url": url, "warning": platform_warning})

    except yt_dlp.utils.DownloadError as e:
        print(f"  [!!] DOWNLOADER /info ERROR [{_detect_platform(url)}]: {e}\n       URL: {url}")
        return JSONResponse({"error": friendly_error(str(e), url)}, status_code=400)
    except Exception as e:
        print(f"  [!!] DOWNLOADER /info UNEXPECTED [{_detect_platform(url)}]: {e}\n       URL: {url}")
        return JSONResponse({"error": f"Failed to fetch info: {e}"}, status_code=500)


# STREAMING DOWNLOAD
# No disk writes, no background threads, no progress polling. Each
# endpoint resolves the real media URL via yt-dlp, then pipes the
# response body straight through to the client as it downloads.

CHUNK_SIZE = 256 * 1024  # 256 KB per chunk

def _stream_from_url(direct_url, headers, filename, media_type):
    def gen():
        with req_lib.get(direct_url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    yield chunk
    safe_name = urllib.parse.quote(filename)
    return StreamingResponse(
        gen(),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@router.get("/stream/video")
async def stream_video(url: str, format_id: str, title: str = "video"):
    """Stream a progressive (video+audio combined) format directly -- no FFmpeg merge needed."""
    try:
        with yt_dlp.YoutubeDL(build_ydl_opts_for_url(url, {"format": format_id})) as ydl:
            info = ydl.extract_info(url, download=False)
        direct_url = info.get("url")
        ext = info.get("ext", "mp4")
        if not direct_url:
            for f in info.get("formats", []):
                if f.get("format_id") == format_id:
                    direct_url = f.get("url")
                    ext = f.get("ext", ext)
                    break
        if not direct_url:
            return JSONResponse({"error": "Could not resolve a direct stream URL for this format. Try fetching info again."}, status_code=400)

        headers = info.get("http_headers") or get_headers_for_url(url)
        filename = f"{safe_win_filename(title)}.{ext}"
        return _stream_from_url(direct_url, headers, filename, f"video/{ext}")
    except yt_dlp.utils.DownloadError as e:
        return JSONResponse({"error": friendly_error(str(e), url)}, status_code=400)
    except Exception as e:
        print(f"  [!!] DOWNLOADER /stream/video ERROR: {e}\n       URL: {url}")
        return JSONResponse({"error": f"Download failed: {e}"}, status_code=500)


@router.get("/stream/audio")
async def stream_audio(url: str, format_id: str = "", title: str = "audio"):
    """Stream the best available audio-only format in its native container (no MP3 transcode)."""
    try:
        fmt = format_id if format_id else "bestaudio/best"
        with yt_dlp.YoutubeDL(build_ydl_opts_for_url(url, {"format": fmt})) as ydl:
            info = ydl.extract_info(url, download=False)
        direct_url = info.get("url")
        ext = info.get("ext", "m4a")
        if not direct_url:
            for f in info.get("formats", []):
                if f.get("format_id") == format_id:
                    direct_url = f.get("url")
                    ext = f.get("ext", ext)
                    break
        if not direct_url:
            return JSONResponse({"error": "Could not resolve a direct audio URL. Try fetching info again."}, status_code=400)

        headers = info.get("http_headers") or get_headers_for_url(url)
        filename = f"{safe_win_filename(title)}.{ext}"
        return _stream_from_url(direct_url, headers, filename, f"audio/{ext}")
    except yt_dlp.utils.DownloadError as e:
        return JSONResponse({"error": friendly_error(str(e), url)}, status_code=400)
    except Exception as e:
        print(f"  [!!] DOWNLOADER /stream/audio ERROR: {e}\n       URL: {url}")
        return JSONResponse({"error": f"Download failed: {e}"}, status_code=500)


@router.get("/stream/thumbnail")
async def stream_thumbnail(url: str, title: str = "thumbnail"):
    """Stream a single thumbnail/image straight through as an attachment."""
    raw_url = unwrap_proxy(url)
    if not raw_url:
        return JSONResponse({"error": "No thumbnail URL provided."}, status_code=400)
    try:
        headers = get_headers_for_url(raw_url)
        r = req_lib.get(raw_url, headers=headers, timeout=30)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "image/jpeg")
        ext = "jpg"
        if "png" in content_type: ext = "png"
        elif "webp" in content_type: ext = "webp"
        elif "gif" in content_type: ext = "gif"
        filename = f"{safe_win_filename(title)}.{ext}"
        return Response(r.content, media_type=content_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"})
    except Exception as e:
        return JSONResponse({"error": f"Failed to download thumbnail: {e}"}, status_code=502)


@router.post("/stream/gallery")
async def stream_gallery(request: Request):
    """Build a ZIP of selected gallery images in memory (no disk) and stream it."""
    data = await request.json()
    image_urls = data.get("image_urls", [])
    title = data.get("title", "images")

    if not image_urls:
        return JSONResponse({"error": "No images selected."}, status_code=400)

    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, img_url in enumerate(image_urls):
            raw_url = unwrap_proxy(img_url)
            if not raw_url:
                continue
            try:
                headers = get_headers_for_url(raw_url)
                r = req_lib.get(raw_url, headers=headers, timeout=30)
                r.raise_for_status()
                content_type = r.headers.get("content-type", "image/jpeg")
                ext = "jpg"
                if "png" in content_type: ext = "png"
                elif "webp" in content_type: ext = "webp"
                elif "gif" in content_type: ext = "gif"
                zf.writestr(f"image_{i+1:03d}.{ext}", r.content)
                count += 1
            except Exception:
                continue

    if count == 0:
        return JSONResponse({"error": "Failed to download any images. CDN URLs may have expired -- try fetching info again."}, status_code=502)

    buf.seek(0)
    zip_name = f"{safe_win_filename(title)}_images.zip"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(zip_name)}"},
    )
