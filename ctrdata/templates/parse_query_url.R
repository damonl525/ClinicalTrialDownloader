q <- ctrdata::ctrGetQueryUrl(url="{{ safe_url }}")
cat(jsonlite::toJSON(list(
    queryterm = as.character(q[1, "query-term"]),
    register = as.character(q[1, "query-register"])
), auto_unbox=TRUE))
