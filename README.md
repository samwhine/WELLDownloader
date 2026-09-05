# WELL Downloader

A self-hosted media downloader — video, audio, images, and thumbnails from YouTube, TikTok, Twitter/X, Reddit, SoundCloud, Vimeo, Bilibili, and 1000+ other platforms, powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

Built with FastAPI (Python) on the backend and a single-page vanilla HTML/CSS/JS frontend — no build step, no framework, no node_modules.

**Author:** [Samuel Extehines Heydemans](https://github.com/YOUR-GITHUB-USERNAME)

## Features

- Paste a URL, fetch metadata (title, thumbnail, duration, available qualities)
- Download video (MP4/MKV/WEBM), audio-only, or just the thumbnail
- Gallery / multi-image post support (e.g. Twitter/X threads, Reddit galleries)
- Live download progress with speed and ETA
- Download history (session-based)
- Auto-updates yt-dlp on every startup, so it keeps working as platforms change their sites

## Requirements

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and available on your system PATH (needed to merge separate video/audio streams and for audio format conversion)

## Setup

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd well-downloader

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

- yt-dlp is auto-updated in the background on every app startup, since streaming platforms frequently change their sites and break older extractor versions.
- DRM-protected platforms (Spotify, Apple Music, Netflix, Disney+, etc.) are intentionally blocked — this tool works only with content that isn't DRM-encrypted.
- Downloaded files are stored temporarily under `temp/downloader/<task_id>/` and can be cleaned up via the `/api/downloader/cleanup/{task_id}` endpoint (the frontend calls this automatically).

## Deployment

This app needs a server that stays running and supports installing system binaries (FFmpeg) — **not** a serverless platform like Vercel, since downloads are long-running, stateful (in-memory progress tracking), and require FFmpeg. Good fits:

- [Railway](https://railway.app)
- [Render](https://render.com)
- Any VPS (DigitalOcean, Contabo, etc.)

## Author

**Samuel Extehines Heydemans**

- GitHub: [@YOUR-GITHUB-USERNAME](https://github.com/YOUR-GITHUB-USERNAME)

If you use or fork this project, a link back or credit is appreciated.

## License

MIT License — see [LICENSE](LICENSE). Free to use, modify, and share. Please also respect the terms of service of the platforms you download from.
