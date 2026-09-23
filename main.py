from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from routers import downloader

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "https://well.creativelegacy.my.id").rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n====================================")
    print("        WELL Downloader")
    print("====================================")
    print("App  -> http://localhost:5555")
    print("Docs -> http://localhost:5555/docs")
    print("====================================\n")
    yield
    print("WELL Downloader stopped.")


app = FastAPI(
    title="WELL Downloader API",
    description="Download video, audio, thumbnails, and photo posts from supported public platforms.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(downloader.router, prefix="/api/downloader", tags=["Downloader"])


@app.get("/")
async def home():
    return FileResponse(BASE_DIR / "static" / "index.html", media_type="text/html")


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(BASE_DIR / "static" / "favicon.ico")


@app.get("/og-image.png")
async def og_image_png():
    return FileResponse(BASE_DIR / "static" / "og-image.png", media_type="image/png")


@app.get("/og-image.svg")
async def og_image_svg():
    return FileResponse(BASE_DIR / "static" / "og-image.svg", media_type="image/svg+xml")


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return FileResponse(BASE_DIR / "static" / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap(request: Request):
    base = PUBLIC_SITE_URL or str(request.base_url).rstrip("/")
    return PlainTextResponse(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'<url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>'
        '</urlset>',
        media_type="application/xml",
    )


@app.get("/site.webmanifest")
async def manifest():
    return FileResponse(BASE_DIR / "static" / "site.webmanifest", media_type="application/manifest+json")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5555, reload=True)
