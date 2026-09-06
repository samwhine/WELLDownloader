# ================================================================
#  WELL Downloader — standalone media downloader
#  Author: Samuel Extehines Heydemans
# ================================================================

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from contextlib import asynccontextmanager
import os
import sys
import subprocess
import threading

from routers import downloader

# Vercel sets this env var automatically inside every serverless function.
IS_VERCEL = bool(os.environ.get("VERCEL"))

# No temp/downloader folder needed anymore — the downloader router streams
# bytes straight from source to client and never touches disk. This also
# means the app behaves identically whether it's run locally, on a VPS, or
# on serverless platforms like Vercel.


def _auto_update_ytdlp():
    """
    Update yt-dlp silently on every startup.
    Uses sys.executable so it always targets the SAME Python/pip that is
    currently running this server — if launched from a venv, this updates
    yt-dlp inside that venv, not system Python.
    YouTube (and other platforms) change frequently and can break older
    yt-dlp versions, so keeping it current avoids most download failures.

    Skipped entirely on Vercel: the filesystem there is read-only outside
    /tmp, pip can't write to site-packages at runtime, and even if it
    somehow could, nothing installed at runtime survives past that one
    invocation. On Vercel, yt-dlp is updated by bumping the version in
    requirements.txt and redeploying — that's what actually persists.
    """
    if IS_VERCEL:
        print("  [...] Running on Vercel — skipping runtime yt-dlp update.")
        print("        Bump yt-dlp in requirements.txt and redeploy instead.")
        return
    try:
        print("  [...] Checking for yt-dlp updates...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "--quiet", "--disable-pip-version-check"],
            capture_output=True, text=True, timeout=45,
        )
        if result.returncode == 0:
            print("  [OK]  yt-dlp up to date — Downloader ready!")
        else:
            err = (result.stderr or "").strip().splitlines()
            print(f"  [!!] yt-dlp update check failed: {err[-1] if err else 'unknown error'}")
    except subprocess.TimeoutExpired:
        print("  [!!] yt-dlp update check timed out — continuing with current version.")
    except Exception as e:
        print(f"  [!!] yt-dlp update check skipped: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print()
    print("  ====================================")
    print("        WELL Downloader  v1.0.0")
    print("  ====================================")
    print("   App  -> http://localhost:5556")
    print("   Docs -> http://localhost:5556/docs")
    print("  ====================================")
    print()

    threading.Thread(target=_auto_update_ytdlp, daemon=True).start()

    yield
    print()
    print("  WELL Downloader stopped.")


app = FastAPI(
    title="WELL Downloader API",
    description="Standalone media downloader — YouTube, TikTok, Twitter/X, Reddit, SoundCloud, and 1000+ platforms via yt-dlp.",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(downloader.router, prefix="/api/downloader", tags=["Downloader"])


@app.get("/")
async def serve_home():
    return FileResponse("static/index.html", media_type="text/html")


@app.get("/favicon.ico")
async def favicon():
    fav_path = "static/favicon.ico"
    if os.path.exists(fav_path):
        return FileResponse(fav_path)
    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5556,
        reload=True,
        reload_excludes=["venv/*", "**/venv/*"],
    )
