# VM backup monitoring

Backups → Copies reads Proxmox over the existing SSH connection. It asks
Proxmox for enabled backup storage and lists each storage's backup content,
including NFS/NAS and Proxmox Backup Server storage. Enabled jobs are matched to
the guests returned by each job's `included_volumes` endpoint. A job elsewhere
in the cluster does not establish coverage for a VM.

The latest recorded backup, destination, job coverage and observation time are
shown separately. A backup under 48 hours old with known inventory and schedule
coverage reads **backed up**. An unreadable storage or unknown job selection
reads **unknown**, retaining any backup evidence that was found. Older status
services that omit the new coverage fields also read unknown. Backup presence
does not establish that a restore has been tested.

Select a VM and choose **Backup not required** to stop its backup alerts. The VM
stays visible with a neutral **not required** status. **Require backup** restores
monitoring. This reversible preference is saved for the selected archive on
this Mac, keyed by Proxmox node and VM ID. It does not edit Proxmox jobs, delete
backups, remove the device or suppress unrelated device/collector alerts. All
VMs are monitored by default; absence from a job never automatically opts a VM
out of monitoring.

The probe uses read-only `pvesh get` commands and requires Python 3 on the
Proxmox node. Per-node probes run concurrently. The remote collector has a
shared 4.5-second deadline inside the six-second SSH budget; timed-out storage
queries remain partial observations. Complete reads are cached for 15 minutes,
failed/partial reads for two minutes. The legacy local-dump cache is invalidated
by the new schema version.
