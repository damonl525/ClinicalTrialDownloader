con <- nodbi::src_sqlite(dbname="{{ db }}", collection="{{ col }}")

n_total <- 0L

# --- CTGOV2: hasProtocol check (existing logic) ---
ctgov_result <- tryCatch({
    df <- ctrdata::dbGetFieldsIntoDf(
        con = con,
        fields = c("documentSection.largeDocumentModule.largeDocs.hasProtocol"),
        verbose = FALSE
    )
    n_total <<- nrow(df)
    protocol_ids <- character(0)
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
                } else if (is.logical(val) && length(val) > 0) {
                    if (any(val, na.rm = TRUE)) {
                        protocol_ids <- c(protocol_ids, ids_col[i])
                    }
                } else if (!is.null(val) && length(val) > 0) {
                    if (any(grepl("true", as.character(val), ignore.case = TRUE))) {
                        protocol_ids <- c(protocol_ids, ids_col[i])
                    }
                }
            }
        }
    }
    list(ids = protocol_ids, count = length(protocol_ids))
}, error = function(e) {
    list(ids = character(0), count = 0L)
})

# --- ISRCTN: check attachedFiles filenames (isolated) ---
isrctn_result <- tryCatch({
    df_af <- ctrdata::dbGetFieldsIntoDf(
        con = con, fields = c("attachedFiles"), verbose = FALSE
    )
    isrctn_ids <- character(0)
    # dbGetFieldsIntoDf flattens nested fields with dot notation
    af_col <- "attachedFiles.attachedFile"
    if (nrow(df_af) > 0 && af_col %in% names(df_af)) {
        for (i in seq_len(nrow(df_af))) {
            af <- df_af[[af_col]][[i]]
            if (is.null(af) || length(af) == 0) next
            names_str <- ""
            if (is.data.frame(af) && "name" %in% names(af)) {
                names_str <- paste(af$name, collapse = " ")
            } else if (is.list(af)) {
                if (!is.null(af$name)) {
                    names_str <- as.character(af$name)
                } else {
                    for (j in seq_along(af)) {
                        if (is.list(af[[j]]) && !is.null(af[[j]]$name)) {
                            names_str <- paste(names_str, af[[j]]$name)
                        }
                    }
                }
            }
            if (grepl("\\bprotocol\\b|\\bprot\\b", names_str, ignore.case = TRUE)) {
                isrctn_ids <- c(isrctn_ids, as.character(df_af$`_id`[i]))
            }
        }
    }
    list(ids = isrctn_ids, count = length(isrctn_ids))
}, error = function(e) {
    list(ids = character(0), count = 0L)
})

# --- Combine results (deduplicated) ---
all_ids <- unique(c(ctgov_result$ids, isrctn_result$ids))
result <- list(
    ok = TRUE,
    ids = as.list(all_ids),
    total = n_total,
    ctgov_count = ctgov_result$count,
    isrctn_count = isrctn_result$count
)
tryCatch(DBI::dbDisconnect(con$con), error = function(e) {})
cat(jsonlite::toJSON(result, auto_unbox = TRUE))
