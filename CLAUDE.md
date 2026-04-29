# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Clinical trial data downloader GUI (Python/PySide6 + R ctrdata package). Downloads structured trial data from ClinicalTrials.gov, EU CTR, ISRCTN, CTIS via the R `ctrdata` package, then extracts, filters, and exports to CSV with optional document downloads.

## Commands

```bash
# Run the application (PySide6 UI, default)
python main.py

# Run legacy tkinter UI
python main.py --ui legacy

# Run tests
python tests/test_suite.py
python -m pytest tests/ -v

# Install Python dependencies
pip install -r requirements.txt

# Install R dependencies (manual, in R console)
install.packages(c("ctrdata", "nodbi", "RSQLite"))

# Lint (ruff, no config file)
ruff check .
```

## Architecture

**Five-tab GUI:**

1. **Tab 1 — Database** (`ui/tabs/database_tab.py`): Connect to SQLite via `nodbi::src_sqlite()`, query history with incremental update buttons
2. **Tab 2 — Search & Download** (`ui/tabs/search_tab.py`): Three search modes — form search (ctrGenerateQueries), paste URL, by trial ID. Multi-register support with preview count
3. **Tab 3 — Extract & Export** (`ui/tabs/export_tab.py`): Extract with `f.*` concept functions → filter (phase/status/date/condition/intervention) → export CSV → download documents for filtered trials only
4. **Tab 4 — FDA** (`ui/tabs/fda_tab.py`): Independent tab — search openFDA directly (no R/database needed), parse TOC.html via QWebEngine to list available PDFs, batch download review documents
5. **Tab 5 — CDE** (`ui/tabs/cde_tab.py`): Search CDE (国家药监局药审中心) drug listing, download review reports and package insert PDFs via QWebEngine (bypasses RuiShu WAF)

**Data flow:** `main.py` → `MainWindow` (`ui/main_window.py`) holds shared state (`self.bridge`, `self.filtered_ids`, `self.current_data`, `self.current_search_ids`) and passes itself to tab constructors via `app` parameter.

**UI layer:** `ui/` — PySide6 (LGPL). Dark/light/system theme via `pyqtdarktheme`. QSS design system in `ui/theme.py`. QSettings for persistence.

**Legacy:** `gui/` — Original tkinter UI, accessible via `--ui legacy`. `ctrdata_gui.py` is the legacy main window.

## R Integration (Critical Design)

**Does NOT use rpy2** — Windows encoding conflicts with V8 engine. Uses subprocess:

- `CtrdataBridge` (`ctrdata_core.py`) calls `Rscript.exe` via `subprocess`
- R code is written to temp `.R` files (avoids Windows command-line encoding issues)
- Data exchange: R outputs JSON for structured results; uses temp CSV files for tabular data
- `_run_r_streaming()` uses `Popen` + `readline()` with Qt Signal/Slot for thread-safe UI updates (PySide6) or `root.after(0, callback)` (legacy tkinter)
- `_r_escape()` handles string escaping for embedding Python values in R code

## Key Patterns

- **Two-phase download**: Phase 1 downloads data only (`documents.path=NULL`), Phase 2 downloads documents for filtered trials only (per-trial independent R subprocess, each with own timeout isolation)
- **Multi-register search**: `generate_queries()` calls `ctrGenerateQueries()` to produce URLs for CTGOV2/EUCTR/ISRCTN/CTIS simultaneously; `load_into_db()` supports multi-URL download
- **Preview count**: `count_trials()` calls `ctrLoadQueryIntoDb(only.count=TRUE)` before downloading
- **Incremental update**: `update_last_query()` calls `ctrLoadQueryIntoDb(querytoupdate=N)` to update specific historical queries
- **Post-download filtering**: All filters (phase, status, date, condition, intervention) are applied in Python/pandas after extraction, not in R
- **Resume/checkpoint**: Document downloads save progress to `{db_basename}_{path_hash}_doc_resume.json` via atomic `os.replace()`, filename includes `documents_path` hash for directory isolation, updated after each trial. Validates files exist on disk before marking trial as completed
- **Process tracking**: `self._current_process` stores the active R subprocess; `cancel()` calls `kill()` + `wait(timeout=5)`
- **Concept functions**: `f.*` functions (e.g., `f.trialPhase`, `f.startDate`) standardize fields across registries. R output columns use `.` prefix (e.g., `.trialPhase`)
- **Timeout IPC**: Cross-thread timeout dialog uses `queue.Queue` on widget instance (NOT in Signal payload — PySide6 `Signal.emit(dict)` deep-copies the dict, breaking `threading.Event` and mutable references)
- **QWebEngine**: FDA and CDE tabs use `QWebEnginePage`/`QWebEngineProfile` for web scraping and download (bypasses CDN bot detection and WAF)

## Constants and Configuration

- `core/constants.py`: All filter mappings (`FILTER_PHASES`, `FILTER_STATUSES`), search parameter options (`SEARCH_PHASES`, `SEARCH_RECRUITMENT`, `SEARCH_POPULATIONS`), concept function definitions (`CONCEPT_FUNCTIONS`), document type regexes (`DOC_TYPE_OPTIONS`), field name constants (`CONDITION_FIELDS`, `INTERVENTION_FIELDS`), register definitions (`SUPPORTED_REGISTERS`)
- `core/exceptions.py`: `CtrdataError` hierarchy

## CtrdataBridge Methods

| Method | R Function | Purpose |
|--------|-----------|---------|
| `connect()` | `nodbi::src_sqlite()` | Database connection |
| `get_db_info()` | `DBI::dbGetQuery()` | Database metadata |
| `generate_queries()` | `ctrGenerateQueries()` | Multi-condition search URL generation |
| `count_trials()` | `ctrLoadQueryIntoDb(only.count=TRUE)` | Preview result count |
| `load_into_db()` | `ctrLoadQueryIntoDb()` | Download data (supports multi-URL) |
| `load_by_trial_id()` | `ctrLoadQueryIntoDb(queryterm=ID)` | Download single trial by ID |
| `update_last_query()` | `ctrLoadQueryIntoDb(querytoupdate=)` | Incremental update |
| `parse_query_url()` | `ctrGetQueryUrl()` | Parse search URL |
| `find_synonyms()` | `ctrFindActiveSubstanceSynonyms()` | Drug name synonyms |
| `open_in_browser()` | `ctrOpenSearchPagesInBrowser()` | Open in browser |
| `find_fields()` | `dbFindFields()` | Field discovery |
| `extract_to_dataframe()` | `dbGetFieldsIntoDf()` + `f.*` | Data extraction with filtering |
| `get_unique_ids()` | `dbFindIdsUniqueTrials()` | Cross-register dedup |
| `get_query_history()` | `dbQueryHistory()` | Query history |
| `download_documents_for_ids()` | `ctrLoadQueryIntoDb(documents.path=)` | Document download with resume |

## Non-obvious Details

- `api/`, `repository/`, and `service/` directories are mostly empty placeholders — don't assume they're active
- `config_manager.py` and `validators.py` exist but `ConfigManager` is not wired into the main app flow
- `service/export_service.py` has an `ExportService` class but tabs call `CtrdataBridge.export_csv()` directly
- `rpy2` was removed from `requirements.txt` — never imported at runtime
- `CtrdataCore = CtrdataBridge` alias exists at bottom of `ctrdata_core.py` for backwards compatibility
- The GUI language is Chinese (all user-facing strings are in Chinese)
- `generate_queries()` R output uses tab-separated `QUERYURL\tname\turl` format for Python parsing
- `count_trials()` R output uses `COUNT\tregister\tcount` format
- `load_into_db()` accepts multi-URL input (newline-separated) for multi-register download
- PySide6 UI uses `threading.Thread(daemon=True)` + Qt Signal/Slot for thread-safe R subprocess calls
- `CollapsibleCard` uses objectName-based QSS (`collapsibleHeader`, `collapsibleBody`) for theme compatibility
- Settings dialog (`ui/settings_dialog.py`) uses QSettings for persistence (Windows registry)
- Table right-click context menu in ExportTab: copy cell, copy row, copy selected, export selected CSV
- FDA tab operates independently — no database or R environment required, queries openFDA API directly
- CDE tab uses QWebEngine to bypass RuiShu (瑞数) WAF; reuses a single `QWebEnginePage` for session persistence
- CTIS registry has no public API (web scraping only), downloads are inherently slow and timeout-prone
