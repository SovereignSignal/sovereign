# Generic directory pipe

Any folder a tool writes → one lane in `raw/tools/`.

The short way, which needs no schedule of its own:

```bash
sov relay add ~/Documents/MyTool        # one more source on the machine's single mover
sov relay list                          # what it carries, and where
sov relay remove MyTool                 # take it off again
```

The mover is one rsync job however many folders you add, because rsync takes many sources and one destination. It is installed the moment the first pipe is declared, on either platform (a launchd agent on macOS, a systemd user timer on Linux), and it goes again when you remove the last thing it carries. `sov relay add` refuses a folder whose name collides with a source you already declared, and one inside the destination: two sources sharing a name merge into one directory at exit 0, and a source under the destination loops.

The long way is still here: copy `mirror.sh`, set `SRC` and `LANE`, and test once by hand. The default excludes keep credentials and logs out of the archive. If the same tool runs on several machines, suffix the lane per machine (`mytool-laptop`, `mytool-server`) so file sync never merges two writers.
