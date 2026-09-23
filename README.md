# WELL Downloader

WELL Downloader is a local Python media downloader for public video, audio, image, thumbnail, and photo-carousel content. It uses `yt-dlp` for extraction, FastAPI for the backend API, and FFmpeg for media merging and conversion.

> **Important:** Run the full downloader on a machine with Python, FFmpeg, writable storage, and network access. Vercel is suitable for the static UI or a demo, but it is not the recommended runtime for large downloads or background media processing.

## Vercel demo deployment

This repository includes `vercel.json` and `api/index.py` so Vercel can serve the FastAPI application as a lightweight UI demo. When the `VERCEL` environment variable is present, the app uses `/tmp` instead of the repository filesystem, disables the long-lived cache reaper, reports `demo_mode`, and shows sample metadata in the browser. The demo is intentionally non-downloading: it lets visitors preview the layout, quality selector, thumbnail selector, support matrix, and download workflow without pretending that a serverless function can reliably process large media files.

The public header identifies the author as **Samuel Extehines Heydemans** and links directly to [github.com/samwhine](https://github.com/samwhine). The interface uses the WELL light-blue/deep-blue gradient branding. Backend activity logs record `info`, `download_start`, `download_done`, and `download_error` events with a short anonymized client token, action, media type, sanitized host/path, and task identifier. Raw IP addresses, query strings, and full source URLs are not written to the logs.

To deploy the demo, import this repository into Vercel with the repository root as the project root. No FFmpeg installation is required for the demo UI. The expected deployment files are:

```text
vercel.json
api/index.py
main.py
routers/downloader.py
static/
```

For real downloads, run `WELL_DOWNLOADER_START.bat` on Windows or `python main.py` on a Linux/macOS machine with Python, FFmpeg, writable storage, and a process that remains available while a download is fetched and merged. Vercel's serverless filesystem is temporary, functions have execution and response limits, and background threads cannot be treated as durable workers. A VPS or local machine is the correct full-runtime location.

## Supported websites

| Website or source | Support | Notes |
| --- | --- | --- |
| YouTube | Supported | Single videos and other public media supported by `yt-dlp`. Playlist URLs are intentionally reduced to a single-video flow. |
| TikTok | Supported | Public videos and photo/carousel posts are handled separately. |
| X / Twitter | Best effort | Public posts may work; login-only or private posts may fail. |
| Reddit | Best effort | The post must be publicly accessible. |
| SoundCloud | Best effort | Availability depends on the extractor and track access rules. |
| Vimeo, Bilibili | Best effort | Public content only; region restrictions may apply. |
| Telegram public posts | Supported when public | Private channels and login-only content are not supported. |
| Pinterest public pins | Supported when public | Public image and video pins can be extracted when available. |
| Dailymotion, Twitch, Rumble | Best effort | Public media supported when the installed `yt-dlp` extractor can access the URL. |
| Other `yt-dlp` extractors | Best effort | Actual support depends on the installed `yt-dlp` release. |

## Unsupported websites

| Website or source | Reason |
| --- | --- |
| Instagram | Most content requires cookies or login. Some public Reels may work, but Stories and private content are expected to fail. |
| Spotify | DRM-protected streams and login requirements prevent extraction. |
| Apple Music | FairPlay DRM-protected streams are not supported. |
| Deezer and Tidal | Login and DRM restrictions prevent reliable extraction. |
| Netflix, Prime Video, Disney+, HBO / Max, Crunchyroll | DRM-protected streaming services are not supported. Use the service's official offline feature instead. |

Platform behavior can change when a service changes its access rules or when an extractor is updated. Download only content you are allowed to save.

## Format and size behavior

When a URL is pasted, the frontend automatically fetches metadata. The API returns a concrete file size when the source exposes one. Otherwise, it estimates size from bitrate and duration and displays the value with `~`. The highest available video quality is selected automatically, while detected resolutions remain selectable.

Video downloads combine the selected video format with the best available audio track and merge into `.mp4`, `.mkv`, `.webm`, `.mov`, `.avi`, `.m4v`, or `.ts` when FFmpeg is available. `.avi` uses an FFmpeg video conversion pass; `.mov`, `.m4v`, and `.ts` use a remux pass when compatible with the downloaded codecs. Audio downloads use the selected source quality and convert to the chosen output format. TikTok photo/carousel posts are shown as a selectable gallery; multiple selected images are packaged into a ZIP archive.

## Requirements

- Python 3.10 or newer
- FFmpeg available on the system `PATH`
- Internet access
- Windows, macOS, or Linux

## Windows quick start

1. Run `INSTALL.bat` from the project folder.
2. Run `WELL_DOWNLOADER_START.bat`.
3. Open <http://localhost:5555>.

For [WELLLauncher](https://github.com/samwhine/WELLLauncher), use `START_WITH_WELL_LAUNCHER.bat` so the launcher can monitor the server process.

## Manual start

```bash
python -m venv venv

# Windows
venv\\Scripts\\activate

# macOS/Linux
source venv/bin/activate

python -m pip install -r requirements.txt
python main.py
```

Verify FFmpeg with:

```bash
ffmpeg -version
```

## Cache and updates

Temporary files are stored in `temp/downloader/`. Completed and failed tasks are cleaned automatically after four hours. Change the retention period before starting the server with:

```text
WELL_DOWNLOAD_TTL_HOURS=2
```

Stop the server before running `CLEAR_CACHE.bat`. To update `yt-dlp`, stop the server, run `UPDATE_YTDLP.bat`, and restart the application.

## Architecture

The FastAPI application serves `static/index.html` and mounts the downloader router under `/api/downloader`. The frontend preserves paste-to-fetch, YouTube playlist/radio parameter cleanup, public-platform warnings, format selection, thumbnail selection, progress polling, and carousel selection. Downloads run in a background thread and are tracked through `/progress/{task_id}` until the completed file is served by `/file/{task_id}`.

Because downloads depend on `yt-dlp`, FFmpeg, writable temporary storage, and a process that stays available while media is fetched and merged, a local machine or full VPS is a better runtime than a serverless function.

## Search indexing and social previews

The public page includes an absolute canonical URL, English title and description, author metadata for **Samuel Extehines Heydemans**, a GitHub author link to [@samwhine](https://github.com/samwhine), Open Graph and Twitter preview tags, JSON-LD structured data, `robots.txt`, and a 1200×630 `og-image.png`. The sitemap is available at `https://well.creativelegacy.my.id/sitemap.xml`.

After the domain is publicly reachable over HTTPS, add the site to [Google Search Console](https://search.google.com/search-console), verify ownership, submit the sitemap URL, and request indexing for the homepage. Metadata improves discoverability but cannot guarantee a ranking or immediate inclusion in Google results.

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/downloader/status` | Check server and FFmpeg availability. |
| `POST` | `/api/downloader/info` | Extract metadata and available formats. |
| `POST` | `/api/downloader/download` | Start a background download. |
| `GET` | `/api/downloader/progress/{task_id}` | Poll task progress and final file metadata. |
| `GET` | `/api/downloader/file/{task_id}` | Serve a completed download. |
| `DELETE` | `/api/downloader/cleanup/{task_id}` | Remove temporary task files. |
| `GET` | `/api/downloader/rules` | Return supported and blocked platform rules. |

## Project structure

```text
.
├── main.py
├── requirements.txt
├── routers/downloader.py
├── static/index.html
├── static/favicon.ico
├── static/og-image.png
├── static/og-image.svg
├── static/robots.txt
├── static/site.webmanifest
├── static/sitemap.xml
├── INSTALL.bat
├── CLEAR_CACHE.bat
├── UPDATE_YTDLP.bat
├── START_WITH_WELL_LAUNCHER.bat
└── WELL_DOWNLOADER_START.bat
```

## Legal and security notes

`yt-dlp` cannot guarantee that every URL will work. Private, login-only, geo-restricted, rate-limited, DRM-protected, or unsupported URLs may fail. If this app is exposed beyond a trusted local network, add authentication, rate limiting, SSRF protection for the image proxy, and bounded storage.

This repository does not currently declare an open-source license. Add a license before public distribution. Use Git commits or tags for release tracking; the app intentionally has no in-app product-version badge.

## Development check

```bash
python3 -m py_compile main.py routers/downloader.py
```

## References

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [FFmpeg](https://ffmpeg.org/)
- [Vercel Functions runtime documentation](https://vercel.com/docs/functions/runtimes)

## Author

**Samuel Extehines Heydemans**
GitHub: [@samwhine](https://github.com/samwhine)

## Disclaimer

This project is for personal and educational use. Respect the terms of service, copyright, privacy, and access controls of every platform. Do not use it to bypass DRM or access private content.

## End

WELL Downloader is a local-first tool: paste a public URL, review the detected formats and estimated sizes, choose the highest available quality or another option, and save the result locally.
