con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
n_before <- 0L
tables <- DBI::dbListTables(con$con)
if ("{{ col }}" %in% tables) {
    n_before <- DBI::dbGetQuery(
        con$con,
        sprintf('SELECT COUNT(*) AS n FROM "%s"', con$collection)
    )$n[1]
    if (is.na(n_before)) n_before <- 0L
}
{{ delete_block }}
# Vacuum to reclaim disk space
tryCatch(DBI::dbExecute(con$con, "VACUUM"), error = function(e) NULL)
DBI::dbDisconnect(con$con)
cat(jsonlite::toJSON(list(
    ok = TRUE,
    deleted = as.integer(n_before - {{ n_after_expr }}),
    remaining = as.integer({{ n_after_expr }})
), auto_unbox=TRUE))
