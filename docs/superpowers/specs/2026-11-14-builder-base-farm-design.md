# Desain: Farm Desa Malam (Builder Base)

Tanggal: 2026-11-14 · Status: diimplementasikan di branch feat/builder-base (rencana docs/superpowers/plans/2026-11-14-builder-base-farm.md), belum dikalibrasi di game · Roadmap: bagian 1 (fondasi task) + 4 (Builder Base)

## Tujuan

Mode jalan `builder` yang mem-farm desa malam terus-menerus, dengan dua sub-mode:

| Sub-mode | Cara | Hasil |
|---|---|---|
| `elixir` | deploy 1 troop → menyerah → ulangi; klaim Elixir Cart tiap N serangan | Builder Elixir dari pertahanan (1 pertahanan per pencarian lawan) |
| `gold` | Battle Copter + 1 Giant (tank) + spam Night Witch di satu titik; serang tahap 2 jika muncul | Builder Gold per bintang + Star Bonus harian |

Sekalian membangun fondasi engine + task agar mode `walls` / `auto` nanti tinggal menambah task.

## Fakta game yang mendasari (riset 2026-11-14)

Sumber: patch notes resmi Builder Base 2.0 (Mei 2023), May Update 2026, wiki Fandom *Builder Battles* & *Elixir Cart*.

- Tidak ada loot yang dicuri. **Menyerang → Builder Gold** (tergantung jumlah bintang + liga).
  **Bertahan → Builder Elixir** (tergantung liga sendiri + bintang yang direlakan), masuk ke **Elixir Cart**
  dan harus diklaim manual; cart punya kapasitas per level BH (BH10 ±400rb, dinaikkan Juni 2025),
  elixir yang datang saat cart penuh hilang.
- Setiap pencarian lawan membuka base kita untuk satu pertahanan.
- Serangan 0 bintang = 0 trofi, 0 gold (liga Stone ke atas). Pertahanan mengurangi trofi → **mode elixir
  menurunkan trofi/liga secara bertahap, elixir per pertahanan ikut turun.** Keputusan: dibiarkan.
- Star Bonus: 7–12 bintang/hari tergantung liga, bisa ditumpuk 2, cooldown 22 jam; tanpa batas loot harian.
- Tahap 2 hanya muncul jika lawan BH6+ **dan** tahap 1 hancur 100%. Ada layar persiapan tahap 2
  (pilih hero: hero yang sama dengan sisa HP atau hero lain dengan HP penuh; troop Reinforcement Camp).
- Timer persiapan 1 menit setelah lawan ditemukan; lawan tidak bisa di-skip; battle mulai saat troop
  pertama diturunkan. Timer battle 2 menit per tahap.
- Battle Copter terbuka di BH8; kemampuan hero punya 3 level charge. Night Witch punya Bat Swarm sekali pakai.

## Arsitektur

```text
coc_bot/bot/
  engine.py        ScreenLoop: run/tick, reconnect ADB, deteksi macet, recovery Back→restart→fatal,
                   watchdog tanpa kemajuan. Netral terhadap desa.
  task.py          Protocol Task (lihat di bawah)
  home_task.py     HomeFarmTask: handler desa siang dari state_machine.py, dipindah tanpa perubahan perilaku
  builder_task.py  BuilderFarmTask: sub-mode elixir / gold, hitungan serangan untuk klaim cart
coc_bot/game/
  actions.py       Game (desa siang), tetap
  builder.py       BuilderGame: aksi desa malam
coc_bot/vision/
  screens.py       + BB_HOME, BB_SEARCHING, BB_PREP, BB_BATTLE, BB_STAGE2_PREP, BB_RESULT
```

`state_machine.py` dipecah menjadi `engine.py` + `home_task.py` (boleh tinggal sebagai re-export agar
import lama tetap jalan).

### Antarmuka Task

```python
class Task(Protocol):
    handlers: dict[Screen, Callable[[datetime], None]]
    forward_transitions: frozenset[tuple[Screen, Screen]]
    action_screens: frozenset[Screen]   # macet jika terlalu lama di sini
    wait_screens: frozenset[Screen]     # macet jika melebihi stuck_timeout_s
    def bind(self, loop: ScreenLoop) -> None: ...
    def on_start(self, now: datetime) -> None: ...
    def is_stuck(self, screen: Screen, same_ticks: int, now: datetime) -> bool: ...  # mis. battle kelamaan
    def on_recover(self) -> None: ...   # setelah Back / restart
    def on_resume(self, now: datetime) -> None: ...   # setelah jeda dari dashboard
```

Tidak ada hook `after_restart`: restart selalu mendarat di desa siang (`HOME`), dan handler `HOME`
milik `BuilderFarmTask` selalu naik perahu.

`ScreenLoop` memegang `Stats`, `stop()`, `reset_timers()`, `current_screen` — API yang dipakai
`control.BotRunner` dan dashboard tidak berubah. Pengenalan layar (`game.screen()`) disediakan oleh
objek game milik task.

### Integrasi kontrol & UI

- `control.Mode.BUILDER` diaktifkan; `BotRunner.run()` membuat `HomeFarmTask` atau `BuilderFarmTask`
  sesuai mode.
- Sub-mode dari `settings.toml` (`[builder] mode`) dan bisa dipilih di menu Mode dashboard.
- `N.missing_for_mode(settings, names, mode)` memeriksa item desa malam hanya untuk mode `builder`.
- Statistik: `Stats` dipakai bersama, ditambah `carts` dan `stage2`.
  CSV terpisah `logs/builder-*.csv` (time, mode, cycle_s, battle_s, damage_pct, gold, stage2).

## Alur layar

### Masuk desa malam

`HOME` (desa siang) → ketuk perahu → loading → `BB_HOME`. Terjadi setiap kali layar `HOME` terlihat
(saat start maupun setelah restart).
Jika perahu tidak ditemukan setelah beberapa percobaan → `FatalError("Desa malam tidak bisa dibuka")`.
`BuilderFarmTask` juga menangani `HOME` (selalu naik perahu), `POPUP` (tutup) dan `UNKNOWN` (tunggu),
sama seperti task desa siang.

### Siklus serangan

```text
BB_HOME → (Attack BB → Find Now) → BB_SEARCHING → BB_PREP → deploy → BB_BATTLE
BB_BATTLE → BB_RESULT → Return Home → BB_HOME
BB_BATTLE → BB_STAGE2_PREP → deploy → BB_BATTLE (tahap 2) → BB_RESULT
```

### Mode elixir

1. `BB_PREP`: turunkan 1 troop dari `troop_slot` di titik deploy tahap 1.
2. Tunggu `surrender_after_s`, tekan Surrender, konfirmasi Okay → `BB_RESULT` → Return Home.
3. `BB_HOME`: jika `attacks_since_claim >= cart_every` → ketuk Elixir Cart → Collect → tutup →
   reset hitungan. Klaim juga sekali saat `BB_HOME` pertama kali terlihat. Gagal klaim → dicoba lagi
   setelah serangan berikutnya.

### Mode gold

1. `BB_PREP` (tahap 1), semua di satu titik (titik terkalibrasi + acakan beberapa piksel):
   hero (`hero_slot`; Copter dipilih di layar army BB) → ±1 detik → Giant (`tank_slot`) → `witch_delay_s` → semua `main_slots`.
2. `BB_BATTLE`:
   - Kemampuan hero: kartu hero diketuk tiap `ability_every_s` (tidak berefek sebelum charge siap, jadi
     praktis aktif di charge level 1). Level charge tidak dibaca dari layar.
   - Bat Swarm: ketuk slot Night Witch `bat_swarm_after_s` setelah deploy.
   - OCR damage %; tidak naik selama `damage_stagnant_s` (khusus BB, default 12 s) → End Battle (bintang
     tetap tersimpan). Kalau OCR tidak pernah terbaca, hanya `battle_timeout_s` yang berlaku.
3. Setelah battle tahap 1:
   - `BB_RESULT` → selesai.
   - `BB_STAGE2_PREP` (dan `stage2 = true`) → deploy kartu hero (pilihan hero di layar tahap 2 dibiarkan
     ke game: Copter jika masih hidup, kalau tidak hero lain — dicek di game saat kalibrasi) + `main_slots`
     + `stage2_slots` (troop Reinforcement Camp) di titik deploy tahap 2 → aturan battle sama.
     Jika `stage2 = false` → akhiri pertempuran.
4. `BB_RESULT`: OCR gold (ROI opsional) untuk statistik; gagal baca → dicatat kosong. Bintang tidak dibaca.

## Config

`settings.toml`:

Satu section datar (loader config hanya mendukung section datar):

```toml
[builder]
mode = "elixir"            # "elixir" | "gold"
cart_every = 15            # klaim Elixir Cart tiap N serangan (semua sub-mode)
troop_slot = 2             # elixir
surrender_after_s = 1.5
hero_slot = 1              # gold
tank_slot = 2              # 0 = tanpa tank
main_slots = [3, 4, 5, 6]
taps_per_slot = 3
witch_delay_s = 2.0
ability_every_s = 3.0
bat_swarm_after_s = 6.0
damage_stagnant_s = 12.0
battle_timeout_s = 150     # per tahap
stage2 = true
stage2_slots = []          # kartu tambahan tahap 2 (Reinforcement Camp)
```

Sub-mode juga bisa dipilih lewat `run --builder-mode` dan menu Mode dashboard (`builder elixir` /
`builder gold`).

`calibration.toml` (dikalibrasi dari screenshot game pengguna):

- Template: `bb_boat`, `bb_attack` (tombol + penanda `BB_HOME`), `bb_btn_find_now`, `bb_searching`
  (opsional), `bb_prep` (banner persiapan, kedua tahap), `bb_btn_surrender`, `bb_btn_end_battle` (gold; "Akhiri Serangan" — `BB_STAGE2_PREP` = banner persiapan + tombol ini **atau** peta biru tua; warna peta juga memberi tahu tahap battle setelah recovery, `coc_bot/vision/stage.py`),
  `bb_btn_return_home` (penanda `BB_RESULT`), `bb_elixir_cart`, `bb_btn_collect`, plus `home_attack`
  dan `popup_okay` yang sudah ada.
- Titik: `bb_deploy_stage1`, `bb_deploy_stage2` (gold + stage2), `bb_slot_N` (N = 1..8) untuk kartu yang dipakai.
- ROI: `bb_damage` (gold), `bb_result_gold` (opsional).

Validasi: nilai di luar rentang (slot bukan 1–8, `cart_every < 1`, mode tak dikenal)
→ `ValueError` saat memuat config, seperti validasi yang sudah ada.

## Penanganan error

- Recovery dari engine bersama; setelah restart, handler `HOME` mengembalikan bot ke desa malam.
- Perahu tak ditemukan 3× berturut-turut → fatal dengan pesan jelas (tanpa loop restart).
- Slot troop kosong → deploy slot itu dilewati, peringatan di log, lanjut.
- Jendela cart tidak muncul → Back, hitungan tidak di-reset, dicoba lagi setelah serangan berikutnya.
- Kalibrasi desa malam belum lengkap → mode `builder` menolak start (exit code 2, pesan daftar item).

## Testing

- Test desa siang yang ada dijalankan terhadap `ScreenLoop` + `HomeFarmTask` dan harus tetap lulus
  (bukti refactor tanpa perubahan perilaku).
- Test baru dengan `FakeBuilderGame` (urutan layar terskrip):
  - siklus elixir; klaim cart saat start dan setiap kelipatan `cart_every`
  - gold tanpa tahap 2; gold dengan tahap 2 (tercatat di CSV); `stage2 = false`; battle melewati batas → recovery
  - recovery restart → naik perahu lagi; perahu tak ditemukan → fatal
  - stagnasi damage → End Battle
  - validasi config `[builder]`
- Verifikasi di game nyata (LDPlayer 1280×720) dilakukan pengguna setelah template diambil; tidak
  diklaim terverifikasi sebelum itu.

## Di luar cakupan

- Menjaga trofi / liga di mode elixir.
- Membaca level isi cart dari gambar (bisa ditambah nanti sebagai pemicu klaim).
- Mode `walls` dan `auto` (fondasi task disiapkan, isinya belum).
- Pemilihan titik deploy otomatis per base.
