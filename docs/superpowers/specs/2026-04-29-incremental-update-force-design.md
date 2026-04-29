# Incremental Update Force Mode Design

## Problem

When a query downloaded 0 records (e.g. CTIS timeout, network failure), the
incremental update (`querytoupdate`) returns 0 immediately because
`ctrdata::ctrLoadQueryIntoDb()` compares against the last query timestamp.
Within the 7-day incremental window for EUCTR/CTIS, it finds "no changes" and
reports `n=0`, even though the user never got the data.

## Root Cause

`ctrLoadQueryIntoDb(querytoupdate=N)` defaults to `forcetoupdate=FALSE`, which
only retrieves records modified since the last query timestamp. If the original
query recorded 0 results, the incremental mechanism has no meaningful baseline
and returns 0 again.

The R package provides `forcetoupdate=TRUE` to re-run the query regardless of
timestamp, but the current Python/R template stack never passes this parameter.

## Solution

Auto-detect `query-records == 0` in the UI layer and pass `forcetoupdate=TRUE`
to R, forcing a full re-download for queries that never returned data.

## File Changes

### 1. `ctrdata/templates/update_last_query.R`

Add `forcetoupdate = {{ force }}` to the R function call:

```r
ctrdata::ctrLoadQueryIntoDb(
    querytoupdate = {{ update_val }},
    forcetoupdate = {{ force }},
    con = con, verbose = FALSE
)
```

`{{ force }}` resolves to R literal `TRUE` or `FALSE`.

### 2. `ctrdata/search_download.py` — `update_last_query()`

Add `force_update: bool = False` parameter. Render as R boolean:

```python
force = "TRUE" if force_update else "FALSE"
r_code = _render("update_last_query", db=db, col=col,
                  update_val=update_val, force=force)
```

### 3. `ctrdata/bridge.py` — `update_last_query()`

Add `force_update: bool = False` parameter and pass through:

```python
return _search.update_last_query(self, query_index, callback, timeout, force_update)
```

### 4. `ui/tabs/database_tab.py` — `_incremental_update()`

Before calling bridge, check `query-records` from history data:

```python
force_update = False
if self._history_data is not None and query_index - 1 < len(self._history_data):
    n_records = self._history_data[query_index - 1].get("query-records", 0)
    if n_records == 0 or n_records == "?":
        force_update = True
```

Adjust confirmation dialog to inform user when force mode is active:

```python
if force_update:
    msg = (f"查询 #{query_index} 上次未获取到数据（{n_records} 条）。\n\n"
           "将强制重新下载全部数据。")
else:
    msg = f"增量更新查询 #{query_index}？\n\n仅下载上次查询后有更新的试验数据。"
```

Pass `force_update` to bridge call:

```python
result = self.app.bridge.update_last_query(
    query_index=query_index, force_update=force_update
)
```

### Unchanged Files

- `service/download_service.py` — called by SearchTab without query index
  context, cannot determine record count. Remains `force_update=False`.
- `ui/tabs/search_tab.py` `_update_last_query()` — same reason.

## Behavior

| Scenario | `query-records` | `force_update` | R behavior |
|----------|-----------------|----------------|------------|
| Normal query with data | > 0 | `FALSE` | Incremental: only new/modified records |
| Query returned 0 records | 0 or "?" | `TRUE` | Force: re-run full query |
| SearchTab update (no index) | N/A | `FALSE` | Incremental (unchanged) |
