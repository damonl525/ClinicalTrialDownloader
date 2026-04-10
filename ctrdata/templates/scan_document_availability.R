con <- nodbi::src_sqlite(dbname="{{ db }}", collection="{{ col }}")
tryCatch({
    suppressWarnings({
        ctrdata::ctrLoadQueryIntoDb(
            queryterm = "{{ safe_url }}",
            con = con,
            documents.path = "{{ dp }}",
            documents.regexp = NULL,
            euctrprotocolsall = FALSE,
            verbose = FALSE
        )
    })
}, error = function(e) {
    cat(paste0("SCAN_ERROR\t", as.character(e$message), "\n"))
})
tryCatch(DBI::dbDisconnect(con$con), error = function(e) {})
