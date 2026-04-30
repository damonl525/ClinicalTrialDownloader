con <- nodbi::src_sqlite(dbname="{{ db }}", collection="{{ col }}")
result <- tryCatch({
    ids <- DBI::dbGetQuery(con$con, 'SELECT "_id" FROM "{{ col }}"')$`_id`
    list(ok = TRUE, ids = as.list(ids), count = length(ids))
}, error = function(e) {
    list(ok = FALSE, error = as.character(e$message), ids = list(), count = 0L)
})
tryCatch(DBI::dbDisconnect(con$con), error = function(e) {})
cat(jsonlite::toJSON(result, auto_unbox = TRUE))
