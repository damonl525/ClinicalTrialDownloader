con <- nodbi::src_sqlite(dbname="{{ db }}", collection="{{ col }}")
r <- tryCatch({
    ctrdata::ctrLoadQueryIntoDb(
        queryterm = "{{ safe_id }}",
        con = con,
        documents.path = "{{ dp }}"{{ doc_re }}
    )
}, error = function(e) {
    list(error = as.character(e$message))
})
tryCatch(DBI::dbDisconnect(con$con), error = function(e) {})
n_val <- ifelse("n" %in% names(r), r$n, 0L)
err_val <- if (is.null(r$error)) "" else as.character(r$error)
cat(jsonlite::toJSON(list(
    ok = is.null(r$error),
    n = as.integer(n_val),
    error = err_val
), auto_unbox = TRUE))
