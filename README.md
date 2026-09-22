# WELL Downloader

WELL Downloader adalah downloader media berbasis Python untuk video, audio, thumbnail, dan post foto dari platform publik yang didukung. Aplikasi ini mempertahankan engine `yt-dlp`, menambahkan dukungan gallery untuk TikTok photo/carousel, serta menyediakan halaman Rules / Help agar batasan platform terlihat jelas.

> **Important:** WELL Downloader bekerja sebagai aplikasi lokal pada komputer yang menjalankan Python dan FFmpeg. Aplikasi ini **tidak dapat dijalankan sebagai full downloader langsung di Vercel**. Vercel hanya cocok untuk demo UI atau halaman presentasi WELL Downloader.

## Author

**Samuel Extehines Heydemans**  
GitHub: [@samwhine](https://github.com/samwhine)

## Supported media

WELL Downloader dapat mencoba mengunduh konten publik dari YouTube, TikTok, Telegram public posts, Pinterest public pins, X/Twitter, Reddit, SoundCloud, Vimeo, Bilibili, serta platform publik lain yang tersedia melalui extractor `yt-dlp`.

TikTok video dan TikTok photo/carousel diproses berbeda. Video akan ditampilkan sebagai pilihan kualitas video. Carousel atau photo post akan ditampilkan sebagai gallery sehingga foto dapat dipilih satu per satu atau dikemas menjadi ZIP.

Instagram sengaja tidak didukung karena sebagian besar konten membutuhkan cookies atau login. Spotify dan layanan ber-DRM seperti Netflix, Apple Music, Disney+, Prime Video, Max, Tidal, Deezer, dan Crunchyroll juga tidak didukung.

Gunakan aplikasi hanya untuk konten yang memang boleh kamu simpan. Dukungan aktual dapat berubah jika sebuah platform mengubah sistem akses atau extractor-nya.

## Requirements

- Python 3.10 atau lebih baru
- FFmpeg yang tersedia di system `PATH`
- Koneksi internet untuk memasang dependency dan mengambil metadata media
- Windows, macOS, atau Linux

## Windows quick start

Pertama kali, jalankan installer berikut dari folder project:

```text
INSTALL.bat
```

`INSTALL.bat` akan membuat virtual environment lokal pada folder `venv`, mengaktifkannya, lalu memasang semua dependency dari `requirements.txt`. Proses ini hanya perlu dilakukan saat instalasi awal atau ketika environment perlu dibuat ulang.

Setelah instalasi selesai, jalankan:

```text
WELL_DOWNLOADER_START.bat
```

Launcher tersebut hanya mengaktifkan `venv` dan menjalankan server di:

```text
http://localhost:5555
```

Buka alamat tersebut di browser setelah server berjalan.

### Start melalui WELLLauncher

Jika project dijalankan dari [WELLLauncher](https://github.com/samwhine/WELLLauncher), gunakan script khusus berikut:

```text
START_WITH_WELL_LAUNCHER.bat
```

Script ini sengaja **tidak memakai `pause`**. WELLLauncher perlu mempertahankan proses server, membaca output terminal, dan menerima exit code ketika server berhenti. Untuk pemakaian manual, `WELL_DOWNLOADER_START.bat` tetap tersedia dan memakai `pause` agar jendela terminal tidak langsung tertutup ketika proses selesai.

## Cache dan storage

File hasil download sementara disimpan di `temp/downloader/`. Task yang sudah selesai atau gagal akan dibersihkan otomatis setelah **4 jam**. Task yang masih berjalan tidak disentuh oleh cleanup.

Durasi tersebut dapat diubah dengan environment variable berikut sebelum server dijalankan:

```text
WELL_DOWNLOAD_TTL_HOURS=2
```

Untuk membersihkan seluruh cache secara manual, matikan server terlebih dahulu, lalu jalankan:

```text
CLEAR_CACHE.bat
```

Jangan menjalankan script tersebut ketika ada download aktif karena file hasil yang sedang diproses akan ikut dihapus.

## Update yt-dlp

WELL Downloader memeriksa versi `yt-dlp` saat website dibuka. Jika versi pada virtual environment tertinggal, banner update akan tetap muncul.

Matikan server terlebih dahulu, kemudian jalankan:

```text
UPDATE_YTDLP.bat
```

Script tersebut mengaktifkan `venv` project dan menjalankan upgrade menggunakan interpreter yang sama dengan server. Setelah selesai, jalankan kembali `WELL_DOWNLOADER_START.bat`.

## Manual start

Jika ingin menjalankan secara manual:

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

python -m pip install -r requirements.txt
python main.py
```

FFmpeg harus dipasang terpisah. Pastikan perintah berikut berhasil sebelum menggunakan downloader:

```bash
ffmpeg -version
```

## Project structure

```text
.
├── main.py
├── requirements.txt
├── routers/
│   └── downloader.py
├── static/
│   ├── index.html
│   ├── favicon.ico
│   ├── og-image.png
│   ├── robots.txt
│   ├── sitemap.xml
│   └── site.webmanifest
├── INSTALL.bat
├── CLEAR_CACHE.bat
├── UPDATE_YTDLP.bat
├── START_WITH_WELL_LAUNCHER.bat
└── WELL_DOWNLOADER_START.bat
```

Runtime files seperti task download sementara, partial files, virtual environment, cache, dan secrets diabaikan oleh `.gitignore`.

## Vercel deployment note

Vercel dapat menjalankan aplikasi Python atau FastAPI sebagai serverless function, tetapi deployment tersebut bukan target runtime untuk WELL Downloader full. Versi downloader saat ini membutuhkan proses `yt-dlp` dan FFmpeg, file sementara, task progress, serta proses yang dapat berjalan hingga file selesai diproses.

Vercel memiliki filesystem read-only dengan writable `/tmp` scratch space hingga 500 MB. Function juga memiliki batas durasi dan batas request/response. Batas tersebut membuat model serverless tidak cocok sebagai tempat utama untuk mengunduh dan menyimpan file media berukuran besar atau menjalankan proses background yang persisten. [1] [2] [3]

Vercel tetap dapat digunakan untuk:

- demo UI dan halaman presentasi;
- preview desain WELL Downloader;
- hosting landing page statis;
- SEO, Open Graph image, manifest, robots.txt, dan sitemap.

Untuk downloader publik yang benar-benar berfungsi, jalankan backend pada local machine yang selalu aktif atau pada server/VPS yang memiliki Python, FFmpeg, filesystem persisten, dan worker background. Jika frontend dipisah dari backend, Vercel dapat menjadi frontend sedangkan backend downloader berjalan pada Windows atau VPS.

## Legal and platform note

`yt-dlp` hanya digunakan sebagai engine extractor. WELL Downloader tidak menjamin setiap URL akan berhasil. Konten private, konten yang membutuhkan login, geo-restricted content, rate-limited content, DRM, dan URL yang tidak lagi didukung platform dapat gagal diproses.

## License

Tambahkan lisensi project sesuai kebutuhan sebelum repository dipublikasikan secara luas. Jika belum ditentukan, repository ini belum menyatakan lisensi open source tertentu.

## References

[1]: https://vercel.com/docs/functions/runtimes "Vercel Functions runtimes and filesystem support"
[2]: https://vercel.com/docs/functions/limitations "Vercel Functions limitations"
[3]: https://vercel.com/docs/functions/runtimes/python "Using the Python Runtime with Vercel Functions"
[4]: https://github.com/yt-dlp/yt-dlp "yt-dlp official repository"
[5]: https://ffmpeg.org/ "FFmpeg official website"
