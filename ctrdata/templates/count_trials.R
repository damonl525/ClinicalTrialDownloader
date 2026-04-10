con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
{{ count_blocks }}
DBI::dbDisconnect(con$con)
