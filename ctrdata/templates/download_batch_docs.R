con <- nodbi::src_sqlite(
  dbname = "{{ db }}",
  collection = "{{ col }}"
)

trial_ids <- jsonlite::fromJSON('{{ trial_ids_json }}')
n_total <- length(trial_ids)
results <- vector("list", n_total)

for (i in seq_along(trial_ids)) {
  tid <- trial_ids[i]
  cat(sprintf("PROGRESS\t%d\t%d\t%s\tstart\t\n", i, n_total, tid))
  flush.console()

  r <- tryCatch({
    suppressWarnings(suppressMessages({
      ctrdata::ctrLoadQueryIntoDb(
        queryterm = tid,
        con = con,
        documents.path = "{{ dp }}"
        {{ doc_re }}
      )
    }))
  }, error = function(e) {
    list(error = as.character(e$message))
  })

  n_val <- ifelse("n" %in% names(r), r$n, 0L)
  err_val <- if (is.null(r$error)) "" else as.character(r$error)
  status <- if (nchar(err_val) > 0) "error" else "ok"

  cat(sprintf("PROGRESS\t%d\t%d\t%s\t%s\t%s\n", i, n_total, tid, status, err_val))
  flush.console()

  results[[i]] <- list(
    trial_id = tid,
    ok = (status == "ok"),
    n = as.integer(n_val),
    error = err_val
  )
}

tryCatch(DBI::dbDisconnect(con$con), error = function(e) {})
cat(jsonlite::toJSON(results, auto_unbox = TRUE))
