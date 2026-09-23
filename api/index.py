"""Vercel entrypoint for the WELL Downloader demo deployment.

The full downloader still belongs on Windows or a VPS with FFmpeg and persistent
storage. Vercel serves the UI and FastAPI routes for a lightweight demo preview.
"""
from main import app

__all__ = ["app"]
