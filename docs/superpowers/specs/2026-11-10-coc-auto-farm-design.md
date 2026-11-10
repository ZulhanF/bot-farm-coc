# CoC Auto-Farm — Desain v1

Tanggal: 2026-11-10
Status: disetujui (menunggu review spec)

## 1. Tujuan

Bot farming Clash of Clans yang **dipakai sungguhan**: stabil berjalan berjam-jam di LDPlayer, mengotomasi loop
"cari base → cek loot → serang → pulang → latih ulang", dan pulih sendiri dari error.

Pengguna sadar bahwa botting melanggar ToS Supercell dan berisiko banned permanen; pengujian langsung dilakukan
dengan akun cadangan.

### Di luar cakupan v1
- Lebih dari 1 instance emulator / multi-akun
- Strategi selain goblin/barch di desa utama (Builder Base, target spesifik)
- Collect resource, upgrade wall, notifikasi HP, GUI
- YOLO / deteksi bangunan (disiapkan sebagai titik ekstensi di `vision/`, tidak diimplementasi)

## 2. Lingkungan

| Item | Nilai |
|---|---|
| OS | Windows 11 |
| Python | 3.12 dalam `.venv` (Python 3.14 sistem tidak dipakai — dukungan wheel onnxruntime/RapidOCR untuk 3.14 belum terjamin; 3.12 paling aman) |
| GPU | AMD/Intel (tanpa CUDA) → semua inferensi di CPU |
| Emulator | LDPlayer 9, resolusi **1280×720, 240 DPI**, ADB local connection aktif |
| ADB | `adb.exe` bawaan LDPlayer atau platform-tools di PATH; default `127.0.0.1:5555` |
| Dependensi | `opencv-python`, `numpy`, `rapidocr-onnxruntime`, `pytest`; `tomllib` (stdlib) untuk config |

## 3. Pendekatan

**Hybrid ringan (dipilih):** ADB untuk capture & input, OpenCV template matching untuk tombol dan pengenalan
layar, RapidOCR (ONNX, CPU) untuk angka loot di ROI tetap, state machine berbasis layar untuk alur & recovery.

Alternatif yang ditolak:
- *Full YOLO (ONNX+DirectML)* — butuh dataset berlabel & retrain tiap update UI; tidak sebanding untuk goblin farming.
- *Fork anugrhaswi/Coc-Auto-Farm* — bergantung PyTorch/EasyOCR/CUDA dan model pihak lain; lambat di CPU.

## 4. Arsitektur

```
coc_bot/
  device/adb.py         EmulatorAdb: connect, screencap() -> np.ndarray (BGR), tap(x,y), swipe(), resolution(),
                        start_app(), stop_app()
  vision/templates.py   find(image, name) -> Match|None ; find_all(); ROI & threshold per template
  vision/ocr.py         read_number(image, roi) -> int|None  (RapidOCR + filter digit + validasi rentang)
  vision/screens.py     detect_screen(image) -> Screen
  game/actions.py       aksi tingkat tinggi (lihat §5.3)
  game/deploy.py        deploy_points(sides, count, jitter) -> list[(x,y)]
  bot/state_machine.py  Bot: loop utama, transisi state, recovery
  bot/session.py        SessionPolicy: jam aktif, durasi main/istirahat, target loot, jeda acak
  config.py             memuat settings.toml -> dataclass Settings
  main.py               CLI: run | calibrate | screenshot | test-vision <img>
assets/templates/       PNG potongan tombol/penanda (dibuat oleh pengguna lewat `calibrate`)
  names.py              nama template/ROI/titik yang dipakai bersama + cek kelengkapan kalibrasi
  game/loot.py          Loot + keputusan serang
  logs.py               setup logging file + konsol
settings.toml           threshold loot, port ADB, jeda, sesi (diedit manual)
calibration.toml        kotak template, ROI loot, titik peta & slot troop (ditulis oleh `calibrate`)
logs/                   bot-YYYY-MM-DD.log + screenshot error
tests/                  pytest; tests/fixtures/ berisi screenshot contoh
```

### Aturan dependensi
- Hanya `device/` yang memanggil ADB.
- `vision/` adalah fungsi murni atas gambar (tanpa I/O ke emulator) → dapat diuji dengan screenshot.
- `game/` = `device/` + `vision/` → aksi.
- `bot/` hanya bergantung pada antarmuka `game/` dan `vision/screens` → dapat diuji dengan fake.

## 5. Detail Komponen

### 5.1 Screen enum
`HOME, ATTACK_MENU, ARMY, SEARCHING, BASE_PREVIEW, BATTLE, RESULT, POPUP, UNKNOWN`
(ATTACK_MENU = layar setelah tombol Attack ditekan, berisi tombol "Find a Match")

Deteksi berdasarkan template penanda unik per layar (mis. tombol Attack di HOME, tombol Next di BASE_PREVIEW,
tombol Return Home di RESULT). Diperiksa berurutan; POPUP dikenali dari daftar template popup yang diketahui
(Reload, Close/X, Okay, Try Again). Tidak ada yang cocok → `UNKNOWN`.

### 5.2 OCR loot
- ROI tetap untuk Gold, Elixir, Dark Elixir di BASE_PREVIEW (dari kalibrasi).
- Pra-proses: crop → upscale 2–3× → grayscale → threshold.
- Hasil difilter hanya digit; ditolak jika kosong atau di luar rentang wajar (0–5.000.000 untuk Gold/Elixir,
  0–100.000 untuk DE). Gagal → coba ulang sekali dengan screenshot baru; masih gagal → `None`.

### 5.3 Aksi (`game/actions.py`)
`ensure_home()`, `army_ready() -> bool`, `quick_train()`, `find_match()`, `read_loot() -> Loot|None`,
`next_base()`, `deploy_army()`, `wait_battle_end()`, `return_home()`, `dismiss_popup() -> bool`, `restart_game()`.

Setiap tap memakai jitter posisi ±3–6 px dan jeda acak (rentang dari config).

### 5.4 Deploy
Peta CoC adalah diamond. Titik deploy = titik-titik terdistribusi di sepanjang N sisi (default 4) sedikit di luar
garis tepi, dengan jitter. Troop dipilih dengan tap kartu troop di bar bawah (posisi slot dari kalibrasi), lalu
tap di setiap titik sampai kartu habis (dideteksi dari template kartu "kosong"/abu-abu atau jumlah tap maksimum).

## 6. Alur State Machine

```
START → ENSURE_HOME → CHECK_ARMY ─(belum siap)→ QUICK_TRAIN → WAIT_ARMY → CHECK_ARMY
                         │(siap)
                         ▼
                   FIND_MATCH → EVALUATE_BASE ─(loot < threshold)→ NEXT_BASE → EVALUATE_BASE
                                     │(cukup / batas Next tercapai)
                                     ▼
                                  DEPLOY → WAIT_BATTLE → RETURN_HOME → CHECK_ARMY
```

- Setiap iterasi: screenshot → `detect_screen()` → jika layar tidak sesuai ekspektasi state, state disinkronkan
  ke layar aktual (mis. terlihat RESULT → RETURN_HOME).
- `EVALUATE_BASE`: serang bila `gold >= min_gold AND elixir >= min_elixir AND de >= min_de` (nilai dari config).
  Loot `None` → dianggap tidak layak. Setelah `max_next` (default 50) kali Next → serang base saat ini.
- `WAIT_ARMY`: tidur dengan polling tiap 60–120 dtk (acak) sampai army siap.
- `WAIT_BATTLE`: tunggu RESULT; opsional End Battle setelah `battle_timeout_s`.

### Recovery
1. `POPUP` → `dismiss_popup()`.
2. `UNKNOWN` atau state tidak berubah > 60 dtk → coba tap Back/Close, lalu `restart_game()`
   (`am force-stop com.supercell.clashofclans` + start).
3. 3 restart beruntun gagal → berhenti aman, simpan screenshot, keluar dengan kode error.
4. ADB putus → reconnect hingga 3×; gagal → berhenti.

### Sesi (`SessionPolicy`)
- Main `play_minutes` (acak dalam rentang), lalu istirahat `break_minutes` (acak).
- Jam aktif harian (mis. 08:00–23:00) dan batas total jam main per hari; di luar itu bot tidur sampai jendela
  aktif berikutnya.
- (Target loot per sesi ditunda ke v2 — butuh OCR layar hasil battle.)

## 7. Konfigurasi (`settings.toml`, contoh)

```toml
[adb]
serial = "127.0.0.1:5555"

[loot]
min_gold = 300000
min_elixir = 300000
min_de = 0
max_next = 50

[deploy]
sides = 4
troop_slots = [1, 2]   # slot kartu goblin/barbar/archer

[timing]
tap_delay_ms = [120, 350]
battle_timeout_s = 180

[session]
play_minutes = [40, 70]
break_minutes = [10, 25]
active_hours = ["08:00", "23:00"]
max_hours_per_day = 10
```

Posisi tombol, ROI loot, 4 sudut peta (`map_top/right/bottom/left`) dan slot troop disimpan terpisah di
`calibration.toml` oleh perintah `calibrate`.

## 8. CLI

| Perintah | Fungsi |
|---|---|
| `python -m coc_bot run` | Jalankan bot; Ctrl+C = berhenti aman |
| `python -m coc_bot calibrate` | Ambil screenshot, tandai tombol & ROI dengan drag mouse, simpan template + ROI |
| `python -m coc_bot screenshot` | Simpan screenshot emulator ke `tests/fixtures/` |
| `python -m coc_bot test-vision <img>` | Tampilkan layar terdeteksi, tombol ditemukan, hasil OCR (tanpa tap) |

## 9. Logging
- `logs/bot-YYYY-MM-DD.log` (file + konsol): transisi state, hasil OCR, keputusan serang/skip, jumlah Next,
  loot didapat, ringkasan sesi.
- Screenshot otomatis ke `logs/screens/` saat error atau `UNKNOWN`.

## 10. Testing
- **Unit (pytest, tanpa emulator):** `detect_screen` untuk tiap screenshot fixture; `read_number` terhadap nilai
  yang diketahui; `deploy_points` (jumlah, berada di area valid); transisi state machine dengan fake
  `Game`/`Screen`; `SessionPolicy` dengan jam palsu.
- **Manual (emulator + akun cadangan):** satu siklus penuh, lalu run ≥ 1 jam memantau log.

## 11. Kriteria Selesai v1
- Satu siklus train → cari → evaluasi → serang → pulang berjalan tanpa campur tangan.
- Bot berjalan ≥ 2 jam di akun cadangan tanpa macet permanen (recovery bekerja).
- Semua unit test lulus.
