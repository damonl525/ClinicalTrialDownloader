con <- nodbi::src_sqlite(dbname="{{ db }}", collection="{{ col }}")
result <- tryCatch({
    df <- ctrdata::dbGetFieldsIntoDf(
        con = con,
        fields = c("documentSection.largeDocumentModule.largeDocs.hasProtocol"),
        verbose = FALSE
    )
    protocol_ids <- character(0)
    n_total <- nrow(df)
    if (n_total > 0) {
        hp_col <- "documentSection.largeDocumentModule.largeDocs.hasProtocol"
        if (hp_col %in% names(df)) {
            ids_col <- as.character(df$`_id`)
            hp_data <- df[[hp_col]]
            for (i in seq_len(n_total)) {
                val <- hp_data[[i]]
                if (is.list(val)) {
                    if (any(sapply(val, function(v) isTRUE(v) || identical(tolower(as.character(v)), "true")))) {
                        protocol_ids <- c(protocol_ids, ids_col[i])
                    }
                } else if (!is.null(val) && length(val) > 0) {
                    if (isTRUE(val) || identical(tolower(as.character(val)), "true")) {
                        protocol_ids <- c(protocol_ids, ids_col[i])
                    }
                }
            }
        }
    }
    list(ok = TRUE, ids = as.list(protocol_ids), total = n_total)
}, error = function(e) {
    list(ok = FALSE, error = as.character(e$message), ids = list(), total = 0L)
})
tryCatch(DBI::dbDisconnect(con$con), error = function(e) {})
cat(jsonlite::toJSON(result, auto_unbox = TRUE))
