con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
df <- ctrdata::dbGetFieldsIntoDf(
    con = con{{ fields_r }}{{ calc_r }},
    verbose = FALSE
)
n_after_extract <- nrow(df)
{{ dedup_block }}
{{ scope_block }}
n_final <- nrow(df)
# Convert list columns to JSON strings before writing CSV
# (dbGetFieldsIntoDf may return nested list columns for raw database fields)
for (col_idx in seq_along(df)) {
    if (is.list(df[[col_idx]])) {
        df[[col_idx]] <- sapply(df[[col_idx]], function(x) {
            if (is.null(x) || length(x) == 0) return(NA_character_)
            jsonlite::toJSON(x, auto_unbox = TRUE)
        })
    }
}
write.csv(df, "{{ csv_path }}", row.names = FALSE, fileEncoding = "UTF-8")
DBI::dbDisconnect(con$con)
cat(jsonlite::toJSON(list(ok = TRUE, rows = n_final, cols = ncol(df), n_after_extract = n_after_extract), auto_unbox=TRUE))
