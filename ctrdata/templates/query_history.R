con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
hist <- ctrdata::dbQueryHistory(con = con, verbose = FALSE)
DBI::dbDisconnect(con$con)
if (is.null(hist) || nrow(hist) == 0) {
    cat(jsonlite::toJSON(list(ok = TRUE, empty = TRUE), auto_unbox=TRUE))
} else {
    write.csv(hist, "{{ csv_path }}", row.names = FALSE, fileEncoding = "UTF-8")
    cat(jsonlite::toJSON(list(ok = TRUE, rows = nrow(hist)), auto_unbox=TRUE))
}
