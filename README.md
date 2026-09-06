# WELL Downloader

A self-hosted media downloader — video, audio, images, and thumbnails from YouTube, TikTok, Twitter/X, Reddit, SoundCloud, Vimeo, Bilibili, and 1000+ other platforms, powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

Built with FastAPI (Python) on the backend and a single-page vanilla HTML/CSS/JS frontend — no build step, no framework, no node_modules.

**Author:** [Samuel Extehines Heydemans](https://github.com/samwhine)

## How it works

The server never saves files to disk. It resolves the real media URL through yt-dlp, then streams the bytes straight through to your browser in the same request — your browser's own download manager shows the progress. This is what makes the app work the same way whether it's running on a normal server or on a serverless platform.

The trade-off: merging separate video+audio streams or converting audio to MP3 both need FFmpeg, which serverless platforms don't provide. So:

- **Video** — only qualities that are already a single combined stream are offered (no merge step needed). Depending on the platform this is usually capped somewhere between 360p–720p.
- **Audio** — served in its original container (m4a/webm/opus) rather than transcoded to MP3.

If you run this on your own server with FFmpeg installed, you could extend it to merge/transcode — the current version deliberately keeps things dependency-free so it runs anywhere.

## Features

- Paste a URL, fetch metadata (title, thumbnail, duration, available qualities)
- Download video, audio, thumbnails, or full image galleries (Twitter/X threads, Reddit galleries, etc.)
- Multi-image downloads are zipped in memory and streamed as one file
- Download history (session-based)
- Works locally, on a VPS, or on serverless platforms like Vercel with zero code changes

## Requirements

- Python 3.10+
- FFmpeg is **not required** — this app intentionally avoids needing it at all

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/samwhine/WELLDownloader.git
cd WELLDownloader

# 2. Create a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

The app will be available at **http://localhost:5556**.

## Project Structure

```
well-downloader/
├── main.py                 # FastAPI app entrypoint
├── requirements.txt
├── routers/
│   └── downloader.py       # All downloader API routes + yt-dlp logic
└── static/
    └── index.html          # Single-page frontend (Apple Minimal design)
```

## Notes

- yt-dlp auto-updates on startup when run locally or on a VPS. On serverless platforms (where the filesystem is read-only), this is automatically skipped — update yt-dlp there by bumping the version in `requirements.txt` and redeploying instead.
- DRM-protected platforms (Spotify, Apple Music, Netflix, Disney+, etc.) are intentionally blocked — this tool works only with content that isn't DRM-encrypted.
- Nothing is ever written to disk, so there's no cleanup job needed and no risk of leftover files piling up.

## Deployment

Because it never writes to disk and never needs FFmpeg, this runs fine on:

- [Vercel](https://vercel.com)
- [Railway](https://railway.app)
- [Render](https://render.com)
- Any VPS (DigitalOcean, Contabo, etc.)

## Author

**Samuel Extehines Heydemans**

- GitHub: [@samwhine](https://github.com/samwhine)

If you use or fork this project, a link back or credit is appreciated.

## License

MIT License — see [LICENSE](LICENSE). Free to use, modify, and share. Please also respect the terms of service of the platforms you download from.
