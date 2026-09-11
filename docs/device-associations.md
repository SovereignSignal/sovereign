# Device associations in the Mac app

In Operations → Hosts, select a device and choose **Disassociate device…**. Confirm to remove it from the active device map, counts, connectivity warnings and device-specific backup/contribution warnings. Past notes stay in the archive. The current device and configured Hub cannot be disassociated.

Disassociated devices stay in a separate section of Hosts. **Associate again** restores the device to the active view, including any current warnings. The choice survives refresh, rediscovery and app restart; restoring it does not require connecting to the device.

This is an archive-scoped preference on the current Mac. It does not retire collection jobs, revoke device credentials, or change external fleet monitoring. Those operations retain their own configuration and access controls. No command is sent to a powered-off device.

The native bridge validates the selected archive, known device and protected devices before persisting the choice in the app preference domain. The shared status projection applies it across Home, System, Operations and Glance while keeping the underlying service evidence and archive files intact.

Validation: `node apps/console/tests/device-associations.cjs` and `python3 apps/console/test-device-associations.py --evidence /tmp/device-qa`. Native QA uses disposable archives and its own preference suite.
