syns <- ctrdata::ctrFindActiveSubstanceSynonyms("{{ safe_sub }}")
cat(jsonlite::toJSON(as.character(syns), auto_unbox=FALSE))
