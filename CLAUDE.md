# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Clinical trial data downloader GUI (Python/PySide6 + R `ctrdata` package), current version **1.5.2** (`core/constants.py`). Downloads structured trial data from ClinicalTrials.gov (CTGOV2), EU CTR, ISRCTN, EU CTIS via the R `ctrdata` package, then extracts, filters, and exports to CSV with optional document downloads. Also has standalone FDA (openFDA) and CDE (国家药监局药审中心) review-document tabs that need **no R/database**.

## Commands

```bash
# Run the application (PySide6 UI, default); falls back to legacy tkinter if PySide6 missing
python main.py
python main.py --ui legacy      # Force legacy tkinter UI

# Run tests (two independent test surfaces; test_suite.py only covers legacy validators/config)
python tests/test_suite.py
python -m pytest tests/ -v

# Install Python dependencies (note: jinja2 is required — used to render R templates)
pip install -r requirements.txt

# Install R dependencies (manual, in R console)
install.packages(c("ctrdata", "nodbi", "RSQLite", "chromote"))

# Lint (ruff, no config file)
ruff check .

# Build a Windows executable (PyInstaller). build.spec is auto-generated — do not hand-edit.
python build.py                 # onedir build
python build.py --onefile       # single exe
python build.py --clean         # clean build/ + dist/ first
```

`build.spec` bundles `ctrdata/templates/`, `assets/`, and `CHANGELOG.md` as datas and declares `PySide6.QtWebEngineCore`, `pandas`, `jinja2`, `qtawesome`, `pyqtdarktheme`, `darkdetect` as hidden imports — any new data file or runtime import must be added to `build.py` (which regenerates the spec), not the spec directly.

## Architecture

**Five-tab GUI** (`ui/tabs/`), each tab receives the `MainWindow` as its `app` parameter:

1. **数据库 Database** (`database_tab.py`): Connect to SQLite via `nodbi::src_sqlite()`, query history, incremental updates, env indicator
2. **搜索与下载 Search & Download** (`search_tab.py`): Three modes — form search (`ctrGenerateQueries`), paste URL, by trial ID. Multi-register with preview count. On success auto-switches to Export tab and triggers extraction (`download_finished` → `MainWindow._on_search_download_finished`)
3. **提取与导出 Extract & Export** (`export_tab.py`): Extract with `f.*` concept functions → filter (phase/status/date/condition/intervention) → export CSV → download documents for filtered trials only
4. **FDA审评资料 FDA** (`fda_tab.py`): Standalone — searches openFDA directly (no R/db), parses TOC.html via QWebEngine to list available PDFs, batch download review documents
5. **CDE上市药品 CDE** (`cde_tab.py`): Scrapes CDE marketed-drug list via QWebEngine (bypasses RuiShu 瑞数 WAF), downloads 审评报告 and 说明书 PDFs

**Data flow / shared state:** `main.py` → `ui.app.create_app()` (theme + QSettings) → `MainWindow` (`ui/main_window.py`). `MainWindow` holds shared state (`self.bridge`, `self.filtered_ids`, `self.current_data`, `self.current_search_ids`, `self.db_total_records`) and runs an async R-environment check on startup (`check_r_environment()` → `EnvCheckDialog` if packages incomplete). Tabs read/write this shared state directly.

**Layers:**
- `ui/` — PySide6 (LGPL). Theme: dark/light/system via `pyqtdarktheme`, QSS design system in `ui/theme.py`, app/theme setup in `ui/app.py`. Reusable widgets in `ui/widgets/` (`card.py`, `filter_table.py`, `date_edit.py`, `progress.py`, `guide_dialog.py`, `log_dialog.py`, `env_check_dialog.py`, `version_dialog.py`, `table_model.py`). QSettings for persistence.
- `ctrdata/` — **the bridge layer** (see R Integration below). `bridge.py` is a thin facade; `CtrdataCore = CtrdataBridge` alias at bottom of `ctrdata_core.py` for backward compatibility.
- `service/` — **actively used** business-logic layer: FDA (`fda_service.py`, `fda_toc_parser.py`, `fda_pdf_downloader.py`), CDE (`cde_scraper.py`, `cde_pdf_downloader.py`), and Qt-free orchestration extracted from tabs (`download_service.py`, `extract_service.py`) so logic is testable without Qt.
- `core/` — `constants.py` (mappings, `classify_registry()`, `APP_VERSION`), `exceptions.py` (`CtrdataError` hierarchy, `DownloadTimeoutError`), `logger.py` / `log_handler.py` (file logging + Qt log handler).
- `gui/` — Original tkinter UI (legacy path via `--ui legacy`). `ctrdata_gui.py` is the legacy main window.

## R Integration (Critical Design)

**Does NOT use rpy2** — Windows encoding conflicts with V8 engine. Uses `subprocess` to call `Rscript.exe`. `CtrdataBridge` (`ctrdata/bridge.py`) is a **facade** that delegates to submodules:

| Submodule | Responsibility |
|-----------|---------------|
| `process.py` | `run_r()` / `run_r_json()` / `run_r_streaming()` — write temp `.R` file, exec via Rscript, parse JSON/line output; per-trial `download_one_trial_doc()`, `download_batch_docs()` |
| `process_env.py` | R path detection (`_find_rscript`), `check_r_environment()`, `_r_escape()`, `_validate_r_input()`, `_translate_r_error()` |
| `connection.py` | connect / db info / query history / collection clearing |
| `search.py`, `search_query.py`, `search_download.py` | query generation, count, load (single/multi URL/by ID), incremental update, document-availability scan |
| `extract.py` | field discovery, `dbGetFieldsIntoDf` + `f.*` extraction, dedup, protocol/all-ids queries |
| `documents.py` | resume/checkpoint helpers + batch doc orchestration |
| `isrctn_download.py` | ISRCTN direct HTTP download via XML API (no R) |
| `template_loader.py` | Jinja2 render of `.R` templates |

**R code comes from templates, not string concatenation.** R snippets live as `.R` files in `ctrdata/templates/` and are rendered with Jinja2 via `template_loader.render(name, **vars)` (see `connection.py`, `extract.py`, `process.py`, `search_download.py`, `search_query.py`). The Jinja2 env uses custom delimiters (`{{ var }}` / `{% %}`) so R's `$` and `{` pass through unchanged — **never** write R as a raw Python f-string. Rendered code is written to a temp `.R` file and run by Rscript (avoids Windows command-line encoding issues).

- Data exchange: R emits JSON lines for structured results (`run_r_json` scans stdout bottom-up for the first `{`/`[` line); tabular extraction uses temp CSV
- `run_r_streaming()` uses `Popen` + reader thread feeding a `queue.Queue`, polled with progress `callback`, thread-safe via Qt Signal/Slot
- `_r_escape()` escapes Python values embedded in R; prefer passing values as Jinja2 vars over manual escaping
- All subprocess calls set `CREATE_NO_WINDOW` + hide the console window on Windows

**Per-registry document routing** (`process.download_one_trial_doc`), dispatched by `classify_registry(trial_id)`:
- **ISRCTN** → direct HTTP via XML API (`isrctn_download.py`, no R/chromote)
- **EUCTR** → R with `euctrresults=TRUE`; **`documents.regexp` not supported** — downloads ALL files. `queryterm` uses EudraCT number without country suffix
- **CTIS** → R with `register="CTIS"`; supports `documents.regexp` but CTIS has no public API (web-scrape only) — inherently slow/timeout-prone
- **CTGOV2** → standard R with `documents.regexp` type filtering

## Key Patterns

- **Two-phase download**: Phase 1 downloads data only (`documents.path=NULL`); Phase 2 downloads documents for filtered trials only, each trial in its own isolated R subprocess with its own timeout
- **Multi-register search**: `generate_queries()` → `ctrGenerateQueries()` produces URLs for CTGOV2/EUCTR/ISRCTN/CTIS at once; `load_into_db()` accepts newline-separated multi-URL input
- **Preview count**: `count_trials()` → `ctrLoadQueryIntoDb(only.count=TRUE)` before downloading
- **Incremental update**: `update_last_query()` → `ctrLoadQueryIntoDb(querytoupdate=N)` (supports `force_update`)
- **Post-download filtering**: phase/status/date/condition/intervention filters are applied in Python/pandas after extraction, not in R. EUCTR date filter falls back to `_id` year when `.startDate` is empty
- **Resume/checkpoint**: doc downloads save progress to `{db_dir}/{db_basename}_{path_slug}_doc_resume.json` where `path_slug = md5(abspath(documents_path))[:8]` (directory isolation). A `session` hash (`md5(sorted_trial_ids + "|" + abspath(documents_path))[:16]`) invalidates the checkpoint when the trial set changes. Written atomically via `os.replace()`, updated after each trial; files are validated on disk before a trial is marked completed
- **Timeout/stall handling**: `run_r_streaming(timeout=, stall_timeout=, on_timeout=)` — `stall_timeout` kills processes with no stdout activity; `on_timeout` callback lets the user extend up to `_MAX_TIMEOUT_CONTINUES=3` times before force-kill (raises `DownloadTimeoutError`)
- **Process tracking**: `bridge._current_process` holds the active R subprocess; `cancel()` → `kill()` + `wait(timeout=5)`
- **Concept functions**: `f.*` functions (e.g. `f.trialPhase`, `f.startDate`) standardize fields across registries; R output columns use `.` prefix (e.g. `.trialPhase`)
- **Timeout IPC**: cross-thread timeout dialog uses a `queue.Queue` on the widget instance — NOT in a Signal payload (PySide6 `Signal.emit(dict)` deep-copies, breaking `threading.Event` / mutable refs)
- **QWebEngine**: FDA and CDE use `QWebEnginePage`/`QWebEngineProfile` for scraping + download (bypasses FDA Akamai CDN bot detection and CDE RuiShu WAF). TOC/parser and downloader share one `QWebEngineProfile` (same cookies). These services **must run on the main thread** (Qt event loop). FDA uses rate-limited downloads (8–15s random delay, 60s cooldown after consecutive failures); CDE pre-scans the dir to skip existing files without delay

## Constants and Configuration

- `core/constants.py`: `APP_NAME`/`APP_VERSION`, filter mappings (`FILTER_PHASES`, `FILTER_STATUSES`), search options (`SEARCH_PHASES`, `SEARCH_RECRUITMENT`, `SEARCH_POPULATIONS`), concept-function defs (`CONCEPT_FUNCTIONS`), doc-type regexes (`DOC_TYPE_OPTIONS`), field-name constants (`CONDITION_FIELDS`, `INTERVENTION_FIELDS`), register defs (`SUPPORTED_REGISTERS`), `classify_registry(tid)`
- `core/exceptions.py`: `CtrdataError` hierarchy + `DownloadTimeoutError`
- GUI persistence is **QSettings** (Windows registry), orgs `ClinicalTrialDownloader`/`App` (theme, recent db) and `ctrdata_downloader`/`MainWindow` (file logging, guide opt-out). `config_manager.py`/`validators.py` exist and are covered by `tests/test_suite.py` but `ConfigManager` is **not** wired into the main app flow

## CtrdataBridge Public Methods (facade → R)

| Method | R Function | Purpose |
|--------|-----------|---------|
| `connect()` | `nodbi::src_sqlite()` | Database connection |
| `get_db_info()` | `DBI::dbGetQuery()` | Database metadata |
| `generate_queries()` | `ctrGenerateQueries()` | Multi-condition search URL generation |
| `count_trials()` | `ctrLoadQueryIntoDb(only.count=TRUE)` | Preview result count |
| `load_into_db()` | `ctrLoadQueryIntoDb()` | Download data (multi-URL) |
| `load_by_trial_id()` | `ctrLoadQueryIntoDb(queryterm=ID)` | Download single trial by ID |
| `update_last_query()` | `ctrLoadQueryIntoDb(querytoupdate=)` | Incremental update |
| `parse_query_url()` | `ctrGetQueryUrl()` | Parse search URL |
| `find_synonyms()` | `ctrFindActiveSubstanceSynonyms()` | Drug name synonyms |
| `open_in_browser()` | `ctrOpenSearchPagesInBrowser()` | Open in browser |
| `find_fields()` | `dbFindFields()` | Field discovery |
| `extract_to_dataframe()` | `dbGetFieldsIntoDf()` + `f.*` | Data extraction with filtering |
| `get_unique_ids()` | `dbFindIdsUniqueTrials()` | Cross-register dedup |
| `get_query_history()` | `dbQueryHistory()` | Query history |
| `scan_document_availability()` | `ctrLoadQueryIntoDb(only.count)` | Pre-scan which trials have docs |
| `download_documents_for_ids()` | `ctrLoadQueryIntoDb(documents.path=)` | Per-registry doc download w/ resume (see routing above) |

## Non-obvious Details

- `service/` is **active** (FDA/CDE services + Qt-free orchestration) — do not assume it's a placeholder. There is no `api/` or `repository/` directory
- `ctrdata_core.py` is a backward-compat shim re-exporting `CtrdataBridge` from the `ctrdata/` package; `CtrdataCore = CtrdataBridge` alias exists for old imports
- `rpy2` is not in `requirements.txt` and is never imported at runtime
- The GUI language is Chinese (all user-facing strings are Chinese); keep English filenames for FDA downloads (doc_type is NOT mapped to Chinese)
- `generate_queries()` R output uses tab-separated `QUERYURL\tname\turl`; `count_trials()` uses `COUNT\tregister\tcount`; batch doc download emits `PROGRESS\ti\ttotal\ttid\tstatus\terror` lines
- PySide6 UI uses `threading.Thread(daemon=True)` + Qt Signal/Slot for thread-safe R subprocess calls
- `CollapsibleCard` uses objectName-based QSS (`collapsibleHeader`, `collapsibleBody`) for theme compatibility
- ExportTab table right-click context menu: copy cell / copy row / copy selected / export selected CSV
- FDA tab operates independently — no database or R required, queries openFDA API directly, fetches all API pages then client-paginates (200/page) with cross-page selection keyed by `doc_url`
- CDE tab defaults to crawling all pages on search; with a start-date set, stops early when a page is entirely before the date
