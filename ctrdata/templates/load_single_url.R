con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
{{ query_block }}
DBI::dbDisconnect(con$con)

n_val <- ifelse("n" %in% names(result), result$n, 0L)
success_ids <- if ("success" %in% names(result)) as.character(result$success) else character(0)
failed_ids <- if ("failed" %in% names(result)) as.character(names(result$failed)) else character(0)
warn_msg <- if ("error" %in% names(result)) as.character(result$error) else ""

cat(jsonlite::toJSON(list(
    ok = TRUE,
    n = n_val,
    success = I(success_ids),
    failed = failed_ids,
    warning = warn_msg
), auto_unbox = TRUE))
