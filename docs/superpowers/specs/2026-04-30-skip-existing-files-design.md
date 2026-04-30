# Skip Existing Files During Download

**Date**: 2026-04-30
**Version**: v1.4.4
**Status**: Approved

## Problem

All three download modules (Extract tab R ctrdata, FDA QWebEngine, CDE QWebEngine) re-download files that already exist on disk. The root cause is identical across FDA and CDE downloaders: name-collision renaming runs **before** the skip check, producing a new `(2).pdf` filename that doesn't match the existing file, so the skip check never triggers. The Extract tab has no per-file skip logic at all.

## Requirements

1. **Skip condition**: filename match only (`os.path.exists(filepath)`) — no size or hash check
2. **Behavior**: always-on, no toggle or confirmation
3. **Feedback**: log each skip + include skip count in final statistics and UI labels
4. **Scope**: all three download paths (Extract tab, FDA tab, CDE tab)

## Design

### 1. FDA PDF Downloader (`service/fda_pdf_downloader.py`)

**`_download_next()` (line 130)**: Reorder the skip-vs-collision logic.

Current flow (broken):
```
generate filename → collision rename (adds (2) if exists) → skip check (unreachable) → download
```

Fixed flow:
```
generate filename → skip check (exists? → skip) → collision rename → download
```

Changes:
- Add `self._results["skipped"] = []` to `download()` init (line 94)
- Move `os.path.exists(filepath)` check (line 161) **before** collision renaming (line 150)
- On skip: append filepath to `results["skipped"]`, log `"文件已存在，跳过: {filename}"`, call `_advance()`
- `_finish_all()` log: add `"成功 %d, 跳过 %d, 失败 %d"`

### 2. CDE PDF Downloader (`service/cde_pdf_downloader.py`)

Identical fix to FDA downloader.

Changes:
- Add `self._results["skipped"] = []` to `download()` init (line 117)
- Move skip check before collision renaming in `_download_next()` (line 157)
- `_finish_all()` log: add skip count

### 3. Extract Tab Documents (`ctrdata/documents.py`)

**`_flatten_trial_docs()` (line 28)**: Add per-file skip during the move phase.

The R package downloads files into `documents_path/NCT01234567/Prot_000.pdf`, then `_flatten_trial_docs()` moves them to `documents_path/NCT01234567_Prot_000.pdf`. We cannot prevent R from downloading, but we can skip moving files whose destination already exists.

Changes:
- Before `shutil.move()`, check if `dst` already exists
- If exists: `os.unlink(src)` (delete the R-downloaded copy), increment skip counter, log
- Change return type from `None` to `int` (number of skipped files)

**`download_documents_for_ids()` (line 154)**: Report per-file skips via callback.

- After `_flatten_trial_docs()`, check returned skip count
- If > 0: callback with status `"file_skip"` and skip count
- Include file-level skip info in final return dict under key `"file_skips"` (dict of trial_id → count)

### 4. FDA Tab UI (`ui/tabs/fda_tab.py`)

**`_on_download_complete()` (line 622)**: Display skip count.

- Read `results.get("skipped", [])`
- Remove broken `skipped` calculation at line 634
- Result label: `"下载完成: {success} 个文件已保存, {skipped} 个已存在跳过"` (when skips > 0)
- Failure dialog: add skip count line

### 5. CDE Tab UI (`ui/tabs/cde_tab.py`)

**`_on_pdf_download_complete()` (line 556)**: Add skip display.

- Read `results.get("skipped", [])`
- Result label and failure dialog: same pattern as FDA tab

### 6. Export Tab UI (`ui/tabs/export_tab.py`)

**`_on_doc_progress()` (line ~920)**: Handle file-skip callback.

- New status type `"file_skip"`: log `"trial {tid}: {n} 个文件已存在跳过"`

## Edge Cases

| Case | Handling |
|------|----------|
| Empty file at destination | Skipped (filename match only, no size check) |
| R-downloaded temp file after skip | `os.unlink()` in `_flatten_trial_docs()` |
| Skip vs consecutive failure counter | Skips do not affect `_consecutive_failures` |
| Progress bar on skip | `_advance()` fires normally, progress increments |

## Files Changed (8 total)

| File | Type |
|------|------|
| `service/fda_pdf_downloader.py` | Core logic |
| `service/cde_pdf_downloader.py` | Core logic |
| `ctrdata/documents.py` | Core logic |
| `ui/tabs/fda_tab.py` | UI display |
| `ui/tabs/cde_tab.py` | UI display |
| `ui/tabs/export_tab.py` | UI display |
| `CHANGELOG.md` | Version tracking |
| `core/constants.py` | Version bump |
