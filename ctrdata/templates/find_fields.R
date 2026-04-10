con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
fields <- ctrdata::dbFindFields(
    namepart = "{{ pattern }}",
    con = con, sample = TRUE, verbose = FALSE
)
DBI::dbDisconnect(con$con)
cat(jsonlite::toJSON(sort(unique(as.character(fields)))))
