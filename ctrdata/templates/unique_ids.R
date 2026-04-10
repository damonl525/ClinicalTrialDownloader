con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
ids <- ctrdata::dbFindIdsUniqueTrials(con = con, verbose = FALSE)
DBI::dbDisconnect(con$con)
cat(jsonlite::toJSON(as.character(ids)))
