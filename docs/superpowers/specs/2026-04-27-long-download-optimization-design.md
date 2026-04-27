# Design: Long-Running Document Download Optimization

**Date**: 2026-04-27
**Status**: Approved
**Affects**: Document download pipeline (Export Tab)

## Problem

Downloading documents for thousands of Phase 3 trials (2020-present) will fail due to:

1. **Total timeout hardcoded at 7200s (2 hours)** — insufficient for 3000+ trials at 30-60s each
2. **No per-trial timeout in R batch template** — one hung trial stalls the entire batch
3. **No on_timeout callback in batch mode** — timeout kills R process with no user recourse
4. **Resume only records completed trials** — killed trials are retried but in-progress status is lost

## Approach

Switch from batch R session (`download_documents_batch`) to per-trial loop (`download_documents_for_ids`), which runs each trial in an isolated R subprocess with full timeout control.

## Design

### 1. Engine Switch: Batch → Per-Trial

**File**: `ctrdata/bridge.py`

Change `download_documents_for_ids()` to delegate to `_docs.download_documents_for_ids()` instead of `_docs.download_documents_batch()`.

Per-trail mode already exists with full protection:
- Each trial calls `download_one_trial_doc()` → independent R process
- `per_trial_timeout` actually enforced via `run_r_streaming(timeout=..., stall_timeout=...)`
- Timeout marks trial as failed, continues to next
- Resume file updated after each trial

Tradeoff: ~3-5s R cold-start per trial. Negligible vs 30-60s download time per trial.

### 2. Timeout Parameter Adjustments

| Parameter | Before | After | Location |
|-----------|--------|-------|----------|
| `timeout_total` default | 7200 (2h) | 86400 (24h) | `documents.py:100` |
| Settings max range | 600s | 900s | `settings_dialog.py:79` |
| `per_trial_timeout` | 180s (unused) | From Settings (default 120s) | Already wired |

The `on_timeout` callback is not needed in per-trial mode — each trial has its own `stall_timeout`, and the Python for-loop has no global timeout kill.

### 3. Resume Enhancement: In-Progress Tracking

**File**: `ctrdata/documents.py`

Resume file structure gains `in_progress` field:

```json
{
  "completed": ["NCT0001", "NCT0002"],
  "in_progress": [],
  "failed": {"NCT0099": "TIMEOUT(120s): ..."},
  "skipped_explicitly": [],
  "total": 5000,
  "session": "a1b2c3d4e5f67890"
}
```

Behavior:
- Before `download_one_trial_doc()`: add tid to `in_progress`, save resume
- On success: move from `in_progress` to `completed`, save resume
- On failure: move from `in_progress` to `failed`, save resume
- On recovery: `remaining` excludes `completed`, includes `in_progress` (retry)

`ctrLoadQueryIntoDb()` is idempotent — retrying an in-progress trial won't duplicate files.

### 4. Progress & Error Handling (No Changes Needed)

Per-trail loop already emits `callback(i, total, tid, status, error)` with the same format as batch mode. ExportTab's signal handlers work without modification:

- `_on_doc_progress()` — updates progress bar + ETA
- `_on_doc_complete()` — shows `DocResultDialog`
- `_cancel_doc_download()` — kills current R process, resume preserved

## File Changes Summary

| File | Change | Lines |
|------|--------|-------|
| `ctrdata/bridge.py` | Switch delegation target | ~5 |
| `ctrdata/documents.py` | `timeout_total` default + in_progress resume | ~25 |
| `ui/settings_dialog.py` | SpinBox max range 600→900 | ~1 |

**Total**: ~30 lines, 3 files. No UI changes, no R template changes, no new dependencies.

## Out of Scope

- Batch/fast-path mode (removed, may revisit if per-trial overhead is measurable)
- Pause/resume button (existing cancel + resume flow sufficient)
- Parallel trial downloads (would complicate resume and increase server load)
