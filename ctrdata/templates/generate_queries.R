urls <- ctrdata::ctrGenerateQueries(
    {{ params }}
)
for (name in names(urls)) {
    cat(sprintf("QUERYURL\t%s\t%s\n", name, urls[name]))
}
