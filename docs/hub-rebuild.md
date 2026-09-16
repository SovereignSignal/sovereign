# Rebuild the hub

One screen. Needs: a Mac with the Command Line Tools installed, the recovery key (kept outside every archive; the owner holds two copies), and reach to one vault remote and one kit target.

1. Template and front door:
   `git clone <template remote> ~/sovs-brain-template && mkdir -p ~/brain-bin && ln -s ~/sovs-brain-template/bin/sov ~/brain-bin/sov`
2. The vault, from any remote (the exchange, the canonical, the off-site mirror):
   `git clone <vault remote> "<vault path>"`
3. The kit, from any kit target (newest `*.kit`), opened with the key:
   `sov hub kit-restore --capsule <file>.kit --destination ~/hub-restore --key-file <key>`
4. Put the restored pieces back where the hub reads them:
   `mkdir -p ~/.local/state/sovereign && cp ~/hub-restore/state/hub.json ~/.local/state/sovereign/ && cp ~/hub-restore/pointers/.brain-* ~/`
   then each file under `~/hub-restore/notify/` and `~/hub-restore/include/` to the path `hub.json` names for it.
5. The jobs, previewed then applied:
   `sov hub jobs install` (read the plan), then `sov hub jobs install --apply`
6. Prove it: `sov hub jobs status` lists every job; `sov status --json` shows the hub; the first nightly proves the model.

Rollback of a reinstall: `sov hub jobs uninstall --apply` parks the plists under `sovereign-retired/`.

The kit never contains the recovery key or anything under the vault. Without the key a kit is noise; without the vault remote there is nothing to curate. Keep those two recoverable on their own.
