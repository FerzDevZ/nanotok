# PLAN — `nanotok` v3.0 Build Specification

Status: **in progress** · Target rilis: `3.0.0` · Runtime: Python ≥ 3.9, **zero runtime dependency**

---

## 1. Masalah yang Diselesaikan

Prompt dan output LLM didominasi *overhead*: basa-basi, pengulangan konteks, stack trace
`node_modules`, dan penulisan ulang file penuh untuk perubahan 3 baris. `rancangan.md`
mendefinisikan protokol kompresi 6 layer. Repo ini belum punya implementasi — hanya dokumen
desain. Plan ini mengubah dokumen tersebut menjadi **engine Python yang benar-benar jalan,
teruji, dan bisa dipasang (`pip install -e .`)**.

## 2. Goal & Non-Goal

### Goal (harus ada di rilis ini)

| # | Deliverable | Kriteria lulus |
|---|---|---|
| G1 | Paket `nanotok` dengan 6 layer pipeline | Setiap layer punya modul + fungsi publik bertipe |
| G2 | CLI `nanotok` (10 subcommand) | Bisa dipanggil via `nanotok`, `python -m nanotok` |
| G3 | `init` generator untuk Claude Code, Cursor, Windsurf, AgentSkills | `nanotok.config.json` + 4 file aturan valid |
| G4 | Test suite pytest | ≥ 90 test, semua layer + CLI ter-cover |
| G5 | Verifikasi eksekusi nyata | `mypy` strict bersih, `pytest` hijau, `ruff` bersih |
| G6 | Bukti penghematan token | `nanotok bench` pada korpus nyata di repo ini |
| G7 | Dokumentasi | `README.md` (pemakaian) + plan ini |

### Non-Goal (sengaja tidak dikerjakan)

- Tidak ada panggilan API LLM. Engine ini deterministik, offline, dan murni stdlib.
- Tidak ada UI web / TUI. Surface = CLI + library import.
- Tidak ada tokenizer BPE asli (`tiktoken`). Estimator heuristik deterministik, akurasi ±10–15%.
- Tidak ada auto-rewrite kode. Layer 1 hanya **menghasilkan patch**, tidak menerapkannya.

## 3. Arsitektur Modul

```text
nanotok/
├── __init__.py        # versi + ekspor publik
├── __main__.py        # entrypoint `python -m nanotok`
├── errors.py          # NanotokError, ConfigError, TemplateError
├── models.py          # Enum tier/intent/format + dataclass hasil (typed, frozen)
├── tokens.py          # estimator + CompressionReport
├── config.py          # NanotokConfig, load/discover/validate, merge default
├── sanitize.py        # LAYER 0
├── patching.py        # LAYER 1
├── telegraph.py       # LAYER 2
├── intent.py          # LAYER 3
├── tiers.py           # LAYER 4
├── session.py         # LAYER 5 (pack, checkpoint, agent-bus)
├── templates.py       # isi aturan siap deploy (embedded, aman saat install)
└── cli.py             # argparse surface + exit code contract
tests/
├── test_tokens.py  test_sanitize.py  test_patching.py  test_telegraph.py
├── test_intent.py  test_tiers.py     test_session.py   test_config.py
├── test_templates.py  test_cli.py
pyproject.toml · README.md · PLAN.md · MEMORY.md · .gitignore
```

Aturan dependensi (tidak boleh dibalik): `models`/`errors` → `tokens`/`config` → layer →
`cli`. Tidak ada import melingkar.

## 4. Spesifikasi per Layer + Kontrak Fungsi

### Layer 0 — `sanitize.py`

```python
def sanitize_log(raw_text: str, config: NanotokConfig | None = None) -> SanitizeResult
```

- Hapus ANSI CSI/OSC (`\x1b[...`).
- **Hanya** menganalisis baris yang berbentuk stack frame (`^at `, `^File ", ^\s+at `)
  untuk filtering internal. Baris pesan error tidak pernah dibuang.
- Frame dianggap internal bila memuat marker: `node_modules/`, `node:internal`,
  `site-packages/`, `dist-packages/`, `webpack-internal://`, `.venv/`, `__pycache__`.
- Frame `<anonymous>` **dipertahankan** jika menunjuk path proyek (`/src/`, `/app/`, `/lib/`, `/pages/`).
- Baris duplikat berurutan dilipat menjadi `... [repeated Nx]`.
- Blok fenced code (```` ``` ````) dilewatkan apa adanya (kecuali ANSI) agar kode tidak rusak.
- Keluaran: `SanitizeResult(text, ansi_removed, frames_removed, duplicates_collapsed, blank_lines_removed, report)`.

### Layer 1 — `patching.py`

```python
def build_patch(old_text: str, new_text: str, path: str, *, config, fmt=PatchFormat.AUTO) -> PatchResult
```

- Rasio perubahan = `changed_lines / max(len(old), len(new))` dari `SequenceMatcher.get_opcodes()`.
- `ratio >= diff_threshold_ratio` (default 0.5) atau file baru → `FULL_FILE` (kode mentah, 0 prosa).
- `ratio < 0.5` → patch. Format `AUTO` memilih `ANCHOR` untuk file > 40 baris, `UNIFIED_DIFF` untuk file kecil.
- `ANCHOR`: header `// filepath: <path>` (prefix komentar mengikuti ekstensi: `#` untuk `.py/.sh/.rb/.toml/.yaml`, `--` untuk `.sql`, `//` default), hunk dipisah `// ... existing code ...`.
- `SEARCH_REPLACE`: blok `FILE:` + `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE`.
- `FULL_FILE` tidak menambahkan kalimat apa pun (Zero-Echo Policy).

### Layer 2 — `telegraph.py`

```python
def compress_prose(text: str, *, tier: CompressionTier, config: NanotokConfig) -> str
def compress_document(text: str, *, tier, config) -> DocumentCompression
```

- Proteksi total: fenced code, inline code, URL, identifier (`snake_case`, `camelCase`, `a.b()`, path, `--flag`, angka+unit, `SCREAMING_CASE`, quoted error) **tidak boleh berubah**.
- L1: hapus filler phrase (`please note that`, `in order to`, `dengan demikian`, `silakan`, …), artikel, pronomina, dan politeness. Grammar tetap utuh.
- L2: L1 + buang stop-word/kopula + operator mapping (`because→bc`, `with→w/`, `without→w/o`, `returns→=>`, `causes→->`, `at→@`, `not→!=`).
- L3: L2 + buang token non-teknis; **fallback otomatis ke L2** bila hasil terlalu pendek/ambigu.
- Semua substitusi berbasis regex word-boundary, case-insensitive, dan idempoten (kompres 2× = kompres 1×).

### Layer 3 — `intent.py`

```python
def classify_intent(prompt: str) -> Intent          # CODE_GEN | DEBUG | COMPARE | EXPLAIN | CLI | GENERAL
def output_contract(intent: Intent, tier: CompressionTier) -> str
def route_prompt(prompt: str, *, tier_request, config) -> RoutedPrompt
```

Prioritas klasifikasi: traceback/`error`/`exception`/`gagal` → DEBUG; `vs|versus|compare|pilih|trade-off` → COMPARE; `explain|jelaskan|why|kenapa` → EXPLAIN; `refactor|rename|fix` → CODE_GEN; perintah shell tunggal → CLI.

### Layer 4 — `tiers.py`

```python
def select_tier(requested: CompressionTier | None, *, token_count: int, attachment_count: int, config) -> TierDecision
```

- Default dari config (`L1`). Eskalasi satu tingkat bila `token_count > 16000` **atau** `attachment_count > 3`. Maksimum L3. `TierDecision` mencatat alasan + tier efektif untuk diaudit.

### Layer 5 — `session.py`

```python
def pack_spec(verbose_text: str, *, tier, config) -> PackedSpec
def build_checkpoint(state: SessionState, *, config) -> CheckpointResult
def compile_agent_task(task: AgentTask) -> str
def parse_agent_task(wire: str) -> AgentTask
```

- `pack_spec` menghasilkan section `GOAL / STACK / CONSTRAINTS / ACCEPTANCE / OUT-OF-SCOPE`, target ≤ 30% token asli; item dibuang dari prioritas terendah sampai target tercapai.
- `build_checkpoint` menghasilkan blok `[NANOTOK SNAPSHOT]` dengan `Stack/Done/WIP/Blocker/Next`, dipangkas agar ≤ `max_checkpoint_tokens` (default 90).
- `agent-bus` = JSON minified key `t,f,ln,err,req,c`; validasi ketat (verb dikenal, `ln` > 0, key asing ditolak) → error RFC-7807-ish di CLI.

## 5. CLI Surface

| Command | Fungsi | Contoh |
|---|---|---|
| `sanitize [FILE\|-]` | Layer 0 | `npm run build 2>&1 \| nanotok sanitize -` |
| `compress [FILE\|-] [--tier]` | Layer 2 | `nanotok compress notes.md --tier L2` |
| `estimate [FILE\|-]` | hitung token | `echo "..." \| nanotok estimate -` |
| `pack [FILE\|-]` | Layer 5 spec compressor | `nanotok pack prd.md` |
| `checkpoint` | snapshot sesi | `nanotok checkpoint --state s.json` / flag eksplisit |
| `diff OLD NEW --path P` | Layer 1 patch | `nanotok diff a.ts b.ts --path src/a.ts` |
| `route PROMPT` | Layer 3+4 | `nanotok route "kenapa build gagal?"` |
| `bus` | agent-bus compile/decode | `nanotok bus --type fix_bug --file src/a.ts --line 88` |
| `bench BASE NANO` | metrik penghematan | `nanotok bench a.txt b.txt` |
| `init [--target all]` | deploy aturan | `nanotok init --dir . --force` |
| `config show\|validate` | config ops | `nanotok config validate` |

Kontrak exit code: `0` sukses, `2` input/argumen invalid, `3` config/IO error. Statistik selalu ke **stderr**, payload ke **stdout** (aman untuk pipe).

## 6. Config Schema (`nanotok.config.json`)

Field baru di atas spesifikasi rancangan (semua punya default, kompatibel mundur):
`pack_target_ratio`, `auto_escalate_attachment_count`, `sanitizer.keep_path_markers`,
`tier_labels`. Validasi tipe ketat + `ConfigError` menyebut nama field. `discover_config()`
mencari ke atas dari cwd sampai root.

## 7. Matriks Test

| Area | Test wajib |
|---|---|
| tokens | kosong=0, monoton Naik, kode > prosa density, report persen benar |
| sanitize | ANSI hilang, frame internal hilang, frame proyek tetap, duplikat dilipat, fence utuh, idempoten |
| patching | file baru→full, 1-baris→patch, rewrite besar→full, 3 format valid, prefix komentar per ekstensi |
| telegraph | code fence/inline code/identifier/URL utuh, L1<asli, L2<L1, L3 fallback, idempoten |
| intent | 5 intent + prioritas debug>compare |
| tiers | default, eskalasi token, eskalasi attachment, clamp L3 |
| session | pack ≤30%, checkpoint ≤90 token, bus round-trip + validasi negatif |
| config | merge default, override, unknown key ditolak, tipe salah → ConfigError |
| templates | `init` menulis 5 file, `--target` filter, `--force` overwrite, tanpa force tidak menimpa |
| cli | tiap subcommand end-to-end + exit code + stdout/stderr terpisah |

## 8. Urutan Eksekusi

1. Scaffold `pyproject.toml`, `.gitignore`, paket kosong.
2. `models`/`errors`/`tokens`/`config` (+test) — fondasi.
3. Layer 0 → 5 satu per satu, test menyertai tiap layer.
4. `templates` + `init`.
5. `cli` + test end-to-end.
6. Gate verifikasi: `ruff check`, `mypy --strict nanotok`, `pytest -q`.
7. Benchmark nyata + README + MEMORY.md.

## 9. Definisi Selesai (DoD)

- [ ] Semua G1–G7 lulus dengan bukti command nyata.
- [ ] `mypy --strict nanotok` → `Success: no issues found`.
- [ ] `pytest -q` → 0 failed.
- [ ] `ruff check .` → `All checks passed`.
- [ ] `pip install -e .` lalu `nanotok --help` jalan.
- [ ] Angka penghematan di README berasal dari output `nanotok bench`, bukan klaim.
