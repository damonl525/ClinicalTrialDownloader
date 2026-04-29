con <- nodbi::src_sqlite(
    dbname="{{ db }}",
    collection="{{ col }}"
)
err_msg <- NULL
result <- tryCatch({
    suppressWarnings(suppressMessages({
        ctrdata::ctrLoadQueryIntoDb(
            querytoupdate = {{ update_val }},
            forcetoupdate = {{ force }},
            con = con, verbose = FALSE
        )
    }}))
}, error = function(e) {
    err_msg <<- as.character(e$message)
    NULL
})
DBI::dbDisconnect(con$con)

if (!is.null(err_msg)) {
    cat(sprintf("ERROR\t%s\n", err_msg))
    cat(jsonlite::toJSON(list(
        ok = FALSE,
        error = err_msg,
        n = 0L,
        success = I(character(0)),
        failed = character(0)
    ), auto_unbox = TRUE))
} else {
    n_val <- ifelse("n" %in% names(result), result$n, 0L)
    success_ids <- if ("success" %in% names(result)) as.character(result$success) else character(0)
    failed_ids <- if ("failed" %in% names(result)) as.character(names(result$failed)) else character(0)

    cat(jsonlite::toJSON(list(
        ok = TRUE,
        n = n_val,
        success = I(success_ids),
        failed = failed_ids
    ), auto_unbox = TRUE))
}
