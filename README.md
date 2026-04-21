# Clinical Trial Data Downloader

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![R](https://img.shields.io/badge/R-4.0%2B-green.svg)](https://www.r-project.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PySide6](https://img.shields.io/badge/PySide6-6.5%2B-orange.svg)](https://doc.qt.io/qtforpython/)

Desktop GUI for searching, downloading, and exporting clinical trial data from international registries. Built with Python/PySide6 + R `ctrdata` package.

## Features

### Multi-Registry Support
- ClinicalTrials.gov (CTGOV2)
- EU Clinical Trials Register (EUCTR)
- ISRCTN
- EU CTIS

### Three-Step Workflow
1. **Database** -- Connect to SQLite, view query history, incremental updates
2. **Search & Download** -- Multi-condition search, paste URL, or download by trial ID; multi-register search with result count preview
3. **Extract & Export** -- Field extraction with concept functions, multi-dimensional filtering, CSV export, document download

### Smart Search
- Multi-condition form search (keyword, phase, recruitment status, population)
- Simultaneous multi-register queries via `ctrGenerateQueries()`
- Result count preview before downloading
- URL paste and trial ID direct download

### Seamless Data Pipeline
- Auto-navigate to Export tab after search download
- Auto-extract with progress feedback
- No manual tab switching needed

### Post-Download Filtering
- Trial phase, recruitment status
- Date range (start date)
- Condition / intervention keywords
- Register-based filtering

### Document Download
- PDF downloads (protocols, SAPs, statistical analysis, etc.)
- Batch download in single R session (eliminates per-trial cold-start overhead)
- Resume/checkpoint support with UI prompt on interrupted downloads
- Configurable per-trial timeout via Settings
- Document type filtering (protocol, SAP, or all)

### Progress & Feedback
- Unified progress bars with ETA estimation
- Per-trial progress with elapsed/remaining time
- Cancel support for all long operations (search, extract, download)
- Download result summary dialog with success/fail/skip details

### Data Table
- Sortable columns with persisted widths
- Right-click context menu (copy cell, row, selection, export selected)
- FDA review document matching and download

### UI & Settings
- Dark/Light/System theme switching
- R environment auto-detection with setup guidance
- Persistent settings (theme, paths, timeout, search state, column widths)
- Collapsible card layout for organized content

## System Requirements

### Python
- Python 3.10+
- PySide6 6.5+
- pandas, qtawesome, pyqtdarktheme, darkdetect (optional)

### R
- R 4.0+
- Packages: `ctrdata`, `nodbi`, `RSQLite`

### OS
- Windows (primary)
- macOS/Linux (partial, requires manual R setup)

## Installation

```bash
# Install Python dependencies
pip install -r requirements.txt
```

```r
# Install R packages (in R console)
install.packages(c("ctrdata", "nodbi", "RSQLite"))
```

## Quick Start

```bash
# Launch PySide6 UI (default)
python main.py

# Launch legacy tkinter UI
python main.py --ui legacy
```

### Operation Flow
1. **Database**: Enter filename, click "Connect" -- SQLite DB created automatically
2. **Search**: Enter keywords, select registers, click "Generate Query" -> "Download"
3. **Export**: Auto-extracts after download -> filter -> export CSV -> download documents

## Architecture

```
main.py                          # Entry point
ui/
  main_window.py                 # Main window (shared state hub)
  tabs/
    database_tab.py              # Tab 1: DB connection & history
    search_tab.py                # Tab 2: Search & download
    export_tab.py                # Tab 3: Extract, filter, export, docs
  widgets/
    progress.py                  # ProgressPanel (bar + ETA + cancel)
    collapsible_card.py          # CollapsibleCard layout
  theme.py                       # QSS theme system
  settings_dialog.py             # Settings (theme, paths, timeout)
ctrdata/
  bridge.py                      # CtrdataBridge -- Python-to-R facade
  process.py                     # R subprocess management (streaming + cancel)
  search_query.py                # Query generation & URL parsing
  search_download.py             # Data download (single/multi URL)
  extract.py                     # Field extraction -> DataFrame
  documents.py                   # Document download with resume
  templates/                     # R script templates
core/
  constants.py                   # All mappings, options, field definitions
  exceptions.py                  # CtrdataError hierarchy
service/
  extract_service.py             # Extraction + doc download service
  download_service.py            # Search download service
  fda_service.py                 # FDA review matching & download
```

**Data flow**: Python UI -> `CtrdataBridge` -> `Rscript.exe` subprocess -> `ctrdata` R package -> API calls -> SQLite / PDF files on disk.

## Build

```bash
pip install pyinstaller
python build.py            # Build executable
python build.py --dev      # Dev mode (fast)
python build.py --release  # Release mode (full deps)
```

## Tech Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| GUI | PySide6 6.5+ | Qt for Python (LGPL) |
| Data | pandas | Filtering & export |
| R bridge | subprocess + JSON | Avoids rpy2 encoding issues |
| Theme | pyqtdarktheme + QSS | Dark/Light/System |
| Icons | qtawesome | FontAwesome |
| Database | SQLite + nodbi | Lightweight storage |
| Tests | pytest | Unit test suite |

## License

MIT License. See [LICENSE](LICENSE).

## Acknowledgements

- **Ralf Herold** & `ctrdata` team -- clinical trial data retrieval
- **Qt Team** & PySide6 -- cross-platform GUI framework
- **Pandas Team** -- data processing

---

**Author**: Damon Liang
