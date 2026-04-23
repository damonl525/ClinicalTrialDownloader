# FDA TOC Page pdfFiles Extraction Design

## Context

The FDA tab constructs review PDF URLs by expanding TOC.html links into 7 possible suffixes. We cannot verify which URLs actually exist because FDA's AkamaiGHost CDN blocks all automated HTTP requests (HEAD/GET) with abuse detection.

The TOC.html page contains a JavaScript object `pdfFiles` that lists exactly which PDF files exist (key: document type, value: 1=exists, 0=missing). Combined with `pdfBaseName`, we can construct only confirmed URLs.

**Key discovery:** `PySide6-WebEngineWidgets` (already installed) uses Chromium to load TOC pages — bypassing FDA's bot detection because it's a real browser engine.

## Approach

Use hidden `QWebEnginePage` instances to load each TOC URL, extract `pdfFiles` + `pdfBaseName` via JavaScript, and expand only confirmed PDFs. Fall back to blind 7-suffix expansion on any failure.

## File Changes

```
core/constants.py           # Add FDA_PDFFILES_MAP
service/fda_toc_parser.py   # NEW: QWebEnginePage-based TOC parser
service/fda_service.py      # Remove broken verification, add pdffiles expansion
ui/tabs/fda_tab.py          # Wire TOC parsing into search flow, add logging
```

No new pip dependencies. `PySide6-WebEngineWidgets` 6.10.0 is already installed.

## Module 1: Constants — `core/constants.py`

### New constant: `FDA_PDFFILES_MAP`

Maps `pdfFiles` JavaScript keys to URL suffixes and Chinese labels.

```python
# key: (url_suffix, chinese_label, is_review_doc)
FDA_PDFFILES_MAP = {
    # Review documents (is_review_doc=True)
    "multidisciplineR": ("MultidisciplineR", "综合审评", True),
    "medR":             ("MedR",             "医学审评", True),
    "statR":            ("StatR",            "统计审评", True),
    "pharmR":           ("PharmR",           "药理毒理审评", True),
    "chemR":            ("ChemR",            "化学审评", True),
    "clinPharmR":       ("ClinPharmR",       "临床药理审评", True),
    "otherR":           ("OtherR",           "其他审评", True),
    "sumR":             ("SumR",             "综述报告", True),
    "crossR":           ("CrossR",           "交叉审评", True),
    "integratedR":      ("IntegratedR",      "综合审评", True),
    "riskR":            ("RiskR",            "风险评估", True),
    "microR":           ("MicroR",           "微生物审评", True),
    "nameR":            ("NameR",            "名称审评", True),
    # Administrative documents (is_review_doc=False)
    "approv":           ("Approv",           "批准信", False),
    "lbl":              ("Lbl",              "标签", False),
    "adminCorres":      ("AdminCorres",      "行政信函", False),
    "otherActionLtrs":  ("OtherActionLtrs",  "其他行动信函", False),
    "oeList":           ("OEList",           "OE清单", False),
    "memo":             ("Memo",             "备忘录", False),
    "rems":             ("Rems",             "REMS", False),
    "rems1":            ("Rems1",            "REMS补充", False),
}
```

URL construction rule: `{toc_base}{url_suffix}.pdf`
Example: base=`761467Orig1,Orig2s000` + suffix=`MultidisciplineR` → `761467Orig1,Orig2s000MultidisciplineR.pdf`

## Module 2: TOC Parser — `service/fda_toc_parser.py` (NEW)

### Class: `FdaTocParser(QObject)`

Uses hidden `QWebEnginePage` to load FDA TOC pages and extract JavaScript variables.

**Must run on the main thread** (Qt requirement — QWebEnginePage needs the event loop).

```python
class FdaTocParser(QObject):
    parse_complete = Signal(dict)      # {toc_url: TocPageData | None}
    parse_progress = Signal(int, int)  # completed_count, total_count
    parse_error = Signal(str)          # overall fatal error (e.g. WebEngine unavailable)

    def parse(self, toc_urls: list[str]):
        """Start async parsing of TOC URLs. Emits parse_complete when all done."""

    def cancel(self):
        """Abort all pending page loads."""
```

### Data structure: `TocPageData`

```python
@dataclass
class TocPageData:
    pdf_files: dict[str, int]   # {key: 1|0}
    pdf_base_name: str          # e.g. "761467Orig1,Orig2s000"
    drug_name: str | None       # from JS variable drugName
    company_name: str | None    # from JS variable companyName
    approval_date: str | None   # from JS variable approvalDate
```

### Parsing flow

1. Deduplicate TOC URLs (same URL may appear in multiple API result rows)
2. Extract `toc_base` from each URL (everything before `TOC.html`) for matching to API rows
2. Create up to 3 `QWebEnginePage` instances for parallel loading
3. Each page: `load(QUrl(toc_url))` → wait for `loadFinished` → `runJavaScript('JSON.stringify({f: pdfFiles, b: pdfBaseName, d: drugName, c: companyName, a: approvalDate})')`
4. Parse JSON result into `TocPageData`
5. When all pages done → emit `parse_complete` with full mapping
6. Timeout: 20 seconds per page. On timeout → mark as error, continue with remaining.

### Concurrency

- Max 3 concurrent `QWebEnginePage` instances (avoid memory pressure from Chromium)
- Queue remaining URLs, start next when a slot opens
- All pages share the default `QWebEngineProfile` (session cookies shared)

### Error handling per page

| Condition | Result |
|-----------|--------|
| `loadFinished(ok=False)` | Mark as error |
| `loadFinished(ok=True)` but `pdfFiles` is undefined | Mark as error |
| JavaScript extraction returns null/empty | Mark as error |
| Timeout (20s) | `page.stop()`, mark as error |

Error entries in the result dict: `{toc_url: None}` — caller falls back to blind expansion for that TOC.

## Module 3: Service Changes — `service/fda_service.py`

### Remove (broken/unused)

- `verify_review_urls()` — FDA abuse detection blocks HEAD requests
- `_head_check()` — always returns 404
- `_get_url_suffix()` — no longer needed
- `_clean_row()` — no longer needed

### Modify: `expand_toc_urls()`

Keep as-is for **fallback use only**. No behavioral changes.

### New method: `expand_from_pdffiles()`

```python
def expand_from_pdffiles(
    self,
    rows: list[dict],
    toc_data: dict[str, TocPageData],
) -> list[dict]:
    """Expand TOC rows using parsed pdfFiles data.

    For TOC URLs with successful parse: expand only confirmed PDFs.
    For TOC URLs with failed parse (None): fall back to blind 7-suffix expansion.
    Direct PDF rows: keep as-is.
    """
```

Logic:
1. Separate rows into `direct_rows` (non-TOC) and `toc_rows` (TOC.html/.cfm URLs)
2. Group `toc_rows` by `doc_url` (which IS the TOC URL)
3. For each TOC group:
   - If `toc_data[toc_url]` is a valid `TocPageData` → iterate `pdfFiles`, only generate rows where value=1. Use `pdf_base_name` from `TocPageData` to construct URLs. Map each key through `FDA_PDFFILES_MAP` for suffix + Chinese label.
   - If `toc_data[toc_url]` is None (parse failed) → generate all 7 suffix rows using existing `FDA_REVIEW_SUFFIXES` constant (blind fallback)
4. Construct URL: `{pdf_base_name}{suffix}.pdf` (from TocPageData) or `{toc_base}{suffix}.pdf` (from URL extraction in fallback)
5. Merge direct_rows + expanded_rows → return

## Module 4: UI Changes — `ui/tabs/fda_tab.py`

### Signal changes

**Remove:**
- `_verify_complete = Signal(list, int)`
- `_verify_error = Signal(str)`

**Add:**
- `_toc_parse_complete = Signal(dict)` — receives {toc_url: TocPageData}
- `_toc_parse_error = Signal(str)` — overall parser error

### Flow change in `_on_search_complete()`

```
Current:
  rows from API → check _is_constructed → verify via HEAD (BROKEN) → table

New:
  rows from API → check for TOC URLs → FdaTocParser.parse() → expand_from_pdffiles() → table
                              ↓ no TOC URLs
                           populate table directly
```

Detailed steps:

1. Receive search result (`rows`, `total`)
2. If no results → show "未找到结果" (unchanged)
3. Check if any row has a TOC URL (`.html` or `.cfm` ending)
4. If no TOC rows → `_populate_table(rows)` directly (unchanged)
5. If TOC rows exist:
   a. Collect unique TOC URLs
   b. Update label: "正在解析审评文档目录 (0/{N})..."
   c. Create `FdaTocParser`, connect signals
   d. Call `parser.parse(toc_urls)`
   e. Disable search button during parsing

### New handler: `_on_toc_parse_complete(toc_data)`

1. Call `FdaSearchService.expand_from_pdffiles(rows, toc_data)`
2. `_populate_table(expanded_rows)`
3. Update result label with counts
4. Re-enable search button

### New handler: `_on_toc_parse_error(error_msg)`

1. Log the error
2. Fall back to `FdaSearchService.expand_toc_urls(rows)` (blind expansion)
3. `_populate_table(fallback_rows)`
4. Show warning: "目录解析失败，已展示所有可能的审评文档（部分链接可能不存在）"

### Progress display

During TOC parsing, update result label as pages complete:
- "正在解析审评文档目录 (1/3)..."
- "正在解析审评文档目录 (2/3)..."
- "正在解析审评文档目录 (3/3)..."

Connect `FdaTocParser.parse_progress` signal to update the label.

## Module 5: Logging — All Files

All FDA tab operations are logged via Python's `logging` module. The existing `QtLogHandler` (attached to root logger in `main_window.py`) automatically routes these to the "运行日志" dialog.

### Log points in `service/fda_service.py`

```python
logger.info("FDA搜索: drug_name=%s, 参数=%s", drug_name, params)
logger.info("FDA搜索完成: %d 条API结果, 展开为 %d 条文档", total, len(rows))
logger.warning("FDA搜索失败: %s", error)
```

### Log points in `service/fda_toc_parser.py`

```python
logger.info("开始解析FDA审评目录: %d 个TOC页面", len(toc_urls))
logger.info("TOC页面解析成功: %s → 发现 %d 个可用文档", url, count)
logger.warning("TOC页面解析失败: %s, 原因: %s", url, reason)
logger.info("FDA审评目录解析完成: %d/%d 成功", success, total)
```

### Log points in `ui/tabs/fda_tab.py`

```python
logger.info("FDA搜索请求: %s", params_summary)
logger.info("FDA搜索结果: %d 条, 其中 %d 条含TOC目录", total, toc_count)
logger.info("FDA目录解析完成: 展开为 %d 条确认文档", expanded_count)
logger.info("FDA: 在浏览器中打开 %d 个审评文档", count)
logger.warning("FDA操作失败: %s", error_msg)
```

### Log format

All entries appear in the runtime log dialog as:

```
[10:45:32] ℹ [INFO] service.fda_toc_parser: 开始解析FDA审评目录: 2 个TOC页面
[10:45:45] ℹ [INFO] service.fda_toc_parser: TOC页面解析成功: 761467TOC → 发现 8 个可用文档
[10:45:50] ℹ [INFO] ui.tabs.fda_tab: FDA目录解析完成: 展开为 15 条确认文档
```

No changes to the logging infrastructure itself — just adding `logger.info/warning/error()` calls at the points listed above.

## Graceful Degradation Summary

| Scenario | Behavior |
|----------|----------|
| All TOC pages parsed successfully | Precise expansion — only confirmed PDFs |
| Some TOC pages fail | Failed pages → blind 7-suffix expansion; successful pages → precise |
| All TOC pages fail | All → blind 7-suffix expansion |
| `PySide6-WebEngineWidgets` not installed | Skip TOC parsing entirely → blind expansion |
| FDA search returns no TOC URLs | Direct display (no expansion needed) |

## Acceptance Criteria

1. Search for "Keytruda" → TOC pages parsed → table shows only confirmed PDFs
2. No "验证后无可用链接" regression — confirmed PDFs always appear
3. If TOC parsing fails → table still shows results (fallback expansion)
4. All operations logged to "运行日志" dialog
5. Existing non-TOC results (direct PDFs) display unchanged
6. Right-click context menu, checkboxes, batch open still work
7. Pagination still works
