con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
n <- 0L
tables <- DBI::dbListTables(con$con)
if ("{{ col }}" %in% tables) {
    n <- DBI::dbGetQuery(
        con$con,
        sprintf('SELECT COUNT(*) AS n FROM "%s"', con$collection)
    )$n[1]
    if (is.na(n)) n <- 0L
}
DBI::dbDisconnect(con$con)
cat(jsonlite::toJSON(list(
    connected = TRUE,
    path = "{{ db }}",
    collection = "{{ col }}",
    total_records = as.integer(n)
), auto_unbox=TRUE))
