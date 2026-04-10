con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
total_n <- 0L
total_success <- character(0)
total_failed <- character(0)
{{ download_blocks }}
DBI::dbDisconnect(con$con)
cat(jsonlite::toJSON(list(
    ok = TRUE,
    n = total_n,
    success = as.character(total_success),
    failed = as.character(total_failed)
), auto_unbox = TRUE))
