// merge.js — thin wrapper around ffmpeg.wasm for merging a separate
// video-only stream and audio-only stream into one playable file,
// entirely in the browser. Loaded lazily (dynamic import) only when a
// "merges in your browser" quality is chosen, so everyone else never
// pays the cost of downloading this.
//
// Uses the single-threaded ffmpeg.wasm core, which needs no special
// cross-origin-isolation headers (COOP/COEP) — slower than the
// multi-threaded build, but works on a plain static file server with
// zero server-side configuration.

import { FFmpeg } from "https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.10/dist/esm/index.js";
import { toBlobURL } from "https://cdn.jsdelivr.net/npm/@ffmpeg/util@0.12.1/dist/esm/index.js";

let ffmpegInstance = null;
let loadPromise = null;

async function getFFmpeg(onProgress){
  if (ffmpegInstance) return ffmpegInstance;
  if (loadPromise) return loadPromise;

  loadPromise = (async () => {
    const ffmpeg = new FFmpeg();
    if (onProgress){
      ffmpeg.on("progress", ({ progress }) => onProgress(Math.min(Math.max(progress, 0), 1)));
    }
    const baseURL = "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.6/dist/esm";
    await ffmpeg.load({
      coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, "text/javascript"),
      wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, "application/wasm"),
    });
    ffmpegInstance = ffmpeg;
    return ffmpeg;
  })();

  return loadPromise;
}

/**
 * Merge a video-only ArrayBuffer and an audio-only ArrayBuffer into one
 * file, without re-encoding (stream copy — fast, no quality loss).
 * @param {ArrayBuffer} videoBuf
 * @param {ArrayBuffer} audioBuf
 * @param {string} outExt - 'mp4' or 'webm', matches the source container family
 * @param {(pct:number)=>void} onProgress - called with 0..1
 * @returns {Promise<Blob>}
 */
export async function mergeAV(videoBuf, audioBuf, outExt, onProgress){
  const ffmpeg = await getFFmpeg(onProgress);

  const videoName = outExt === "webm" ? "input_video.webm" : "input_video.mp4";
  const audioName = outExt === "webm" ? "input_audio.webm" : "input_audio.m4a";
  const outputName = `output.${outExt}`;

  await ffmpeg.writeFile(videoName, new Uint8Array(videoBuf));
  await ffmpeg.writeFile(audioName, new Uint8Array(audioBuf));

  // -c copy: remux only, no re-encoding — this is fast and lossless.
  await ffmpeg.exec(["-i", videoName, "-i", audioName, "-c", "copy", outputName]);

  const data = await ffmpeg.readFile(outputName);

  // Clean up virtual FS so repeated merges in the same session don't leak memory.
  try {
    await ffmpeg.deleteFile(videoName);
    await ffmpeg.deleteFile(audioName);
    await ffmpeg.deleteFile(outputName);
  } catch (_) { /* best-effort cleanup */ }

  const mime = outExt === "webm" ? "video/webm" : "video/mp4";
  return new Blob([data.buffer], { type: mime });
}
