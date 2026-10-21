# Rebuild the hub

One screen. Needs: a Mac with the Command Line Tools installed, the recovery key (kept outside every archive; the owner holds two copies), and reach to one vault remote and one kit target.

The machine also needs what the jobs call and no archive carries. A rehearsal on a clean machine found each of these missing:
- Homebrew, with `python`, `rsync` and `poppler`, and the services the hub runs beside it (`ollama`; `gitea` if a local git remote is used).
- The judge model named in `hub.json` (`ollama pull <model>`, tens of GB). The curator refuses any endpoint that is not loopback.
- Any agent the instance jobs run on. If `hub.json` `instance_jobs` name an interpreter inside another tool's virtualenv, install that tool first.

1. Template and front door:
   `git clone <template remote> ~/sovs-brain-template && mkdir -p ~/brain-bin && ln -s ~/sovs-brain-template/bin/sov ~/brain-bin/sov`
2. The vault, from any remote (the exchange, the canonical, the off-site mirror):
   `git clone <vault remote> "<vault path>"`
3. The kit, from any kit target (newest `*.kit`), opened with the key:
   `sov hub kit-restore --capsule <file>.kit --destination ~/hub-restore --key-file <key>`
4. Put the restored pieces back where the hub reads them:
   `mkdir -p ~/.local/state/sovereign && cp ~/hub-restore/state/*.json ~/.local/state/sovereign/ && cp ~/hub-restore/pointers/.brain-* ~/`
   then each file under `~/hub-restore/notify/` and `~/hub-restore/include/` to the path `hub.json` names for it (`cp -p` keeps the mode: a file that was executable on the old hub comes back `0700`, everything else `0600`).
   `state/connectors.json` is what marks this machine as the hub; an older kit may not carry it.
5. The jobs, previewed then applied:
   `sov hub jobs install` (read the plan), then `sov hub jobs install --apply`
6. The tools on this machine, one at a time: `sov connect <tool>` (read the plan), then `--apply`. Each smoke-tests its own read and write wire against the restored vault.
7. Prove it: `sov hub jobs status` lists every job; `sov status --json` shows the hub; the first nightly proves the model.

What to expect afterwards: a clone gives every file a new modification time, so the curator sees old material as newly touched. Content hashes keep anything already judged from being judged again, but items that sat behind the watermark come back into its window, and the first days of ticks work through them. Anything written since the last vault commit is not in the clone.

Rollback of a reinstall: `sov hub jobs uninstall --apply` parks the plists under `sovereign-retired/`.

The kit never contains the recovery key or anything under the vault. Without the key a kit is noise; without the vault remote there is nothing to curate. Keep those two recoverable on their own. A job that lives outside the manifest (a hand-kept plist and its scripts) is restored only if `kit.include` names its files.

Listing an extra file: add its absolute path to `kit.include` in `hub.json` (a folder carries everything under it). The next kit picks up the file as it is that night, so a later edit to a listed script rides along without touching `hub.json`. A listed path that is missing fails the kit, preview and nightly alike, and two different files that would land under one name (case aside) fail rather than one overwriting the other. List what a hand-kept job calls, not only the job: a wrapper that mounts a share through a small compiled helper needs the helper and its source listed beside the wrapper and its plist, or the rebuilt job falls back to whatever the helper replaced. For example, a small helper that mounts a network share goes in as two entries, binary and source; on a different chip, rebuild the binary from the source before the first run.
