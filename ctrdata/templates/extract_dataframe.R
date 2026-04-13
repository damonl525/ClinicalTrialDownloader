con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
df <- ctrdata::dbGetFieldsIntoDf(
    con = con{{ fields_r }}{{ calc_r }},
    verbose = FALSE
)
{{ dedup_block }}
{{ scope_block }}
write.csv(df, "{{ csv_path }}", row.names = FALSE, fileEncoding = "UTF-8")
DBI::dbDisconnect(con$con)
cat(jsonlite::toJSON(list(ok = TRUE, rows = nrow(df), cols = ncol(df)), auto_unbox=TRUE))
