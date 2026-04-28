con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
{{ pre_scope_block }}
df <- ctrdata::dbGetFieldsIntoDf(
    con = con{{ fields_r }}{{ calc_r }},
    verbose = FALSE
)
{{ post_scope_cleanup }}
n_after_extract <- nrow(df)
{{ dedup_block }}
{{ scope_block }}
n_final <- nrow(df)
for (col_idx in seq_along(df)) {
    if (is.list(df[[col_idx]])) {
        df[[col_idx]] <- sapply(df[[col_idx]], function(x) {
            if (is.null(x) || length(x) == 0) return(NA_character_)
            jsonlite::toJSON(x, auto_unbox = TRUE)
        })
    }
}
write.csv(df, "{{ csv_path }}", row.names = FALSE, fileEncoding = "UTF-8")
{{ final_scope_cleanup }}
DBI::dbDisconnect(con$con)
cat(jsonlite::toJSON(list(ok = TRUE, rows = n_final, cols = ncol(df), n_after_extract = n_after_extract), auto_unbox=TRUE))
