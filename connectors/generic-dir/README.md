# Generic directory pipe

Any folder a tool writes → one lane in `raw/tools/`. Set `SRC` and `LANE`, test once by hand, then schedule every ~15 minutes (launchd on macOS, cron on Linux). The default excludes keep credentials and logs out of the brain. If the same tool runs on several machines, suffix the lane per machine (`mytool-laptop`, `mytool-server`) so file sync never merges two writers.
