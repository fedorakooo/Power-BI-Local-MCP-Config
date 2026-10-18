# Reliable server startup

The existing reports, model data, catalog destinations and MCP URLs stay unchanged.
After the ordinary installation has been validated, run elevated PowerShell as the
installation owner:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Reliable.ps1 -Setup
```

Enter that Windows account's password in the local credential dialog. Task Scheduler
stores it in its protected credential store; it is not written into project files.
The current installation uses user-scoped DPAPI Report Server credentials, so the
background task must retain the same Windows identity. Password changes require
rerunning this setup. A dedicated least-privilege service identity requires a separate
credential/ACL migration; this script does not silently grant new catalog permissions.

Setup pins the existing PBIMCPTEST listener port, enables automatic SSAS startup,
backs up msmdsrv.ini before modifying it, and restarts only that SSAS instance.
Existing published reports keep their connection strings valid because the current
port is retained. The background MCP task starts at boot in a noninteractive session.
The Desktop endpoint starts separately at user logon: opening, visual editing and
native Save still require an unlocked Desktop. Server-side report creation, build and
publication do not require Desktop.

A SYSTEM watchdog runs every five minutes. It checks the SSAS listener, Windows
services, all four background MCP inventories and authenticated catalog access.
After two failures, it can restart only the enrolled background task, at most once
per ten minutes. It never repeats Save, publication, restore, refresh or model writes.
Read `runtime/background-health.json` for the latest health state. These local checks
are not external alert delivery or an SLA.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Reliable.ps1 -Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Reliable.ps1 -Restart
```

Production release gates remain explicit: an appropriately licensed SSAS instance
(Developer is test-only), approved authentication/TLS for remote MCP transport,
external alert routing and recovery evidence, protected off-machine model/source
backups, and a real host-reboot acceptance test. IP allowlisting is retained; this
setup does not claim that HTTP without user authentication is suitable for every
production environment. No new data source or refresh schedule is introduced for
the synthetic DATATABLE model, whose data is already embedded in SSAS.

Daily encrypted SSAS backups and report-source snapshots are registered at 02:00
server local time, with 14-day retention. The backup encryption credential is
user-DPAPI protected in runtime/model-backup-credential.xml; it must be separately
escrowed by the operator for disaster recovery. Backups stay on this server until an
approved off-machine destination is supplied. Read runtime/last-model-backup.json.
The watchdog never deletes publication journals or reviewed report backups.

## Target validation — 2026-10-18

- PBIMCPTEST was changed from Manual to Automatic startup and its existing port
  62386 was pinned in msmdsrv.ini. That instance restarted successfully with the
  same endpoint; existing report connection strings remained valid.
- Background tasks ran with Password logon in Windows Session 0. Desktop's
  separate task stayed in Session 1. Catalog access worked through the background
  MCP using the existing protected user credential.
- The scheduled encrypted model backup completed with exit code 0. An isolated
  restore verified synthetic measures 0.4816 and 0.4916; the temporary database was
  removed and the enrolled source database was not overwritten.
- Fault injection terminated only the enrolled headless HTTP child. The background
  group exited, while the Desktop listener kept the same PID. Two health cycles
  were invoked through the SYSTEM scheduled task for this test; the watchdog
  requested recovery and all background MCP protocol/catalog checks passed again.
  This proves watchdog recovery, not a one-minute Task Scheduler restart guarantee.
- STAIR run 1496 built/published the unchanged managed report through background
  MCP. Independent catalog download matched build SHA256
  91b811177c71ce5d8b1829fa04def06f8c8e5dabc66a598f0134b5648e421290;
  the ZIP had one page, four visuals and no embedded DataModel. No new visual
  rendering test was performed.
- The operator will reboot the host themselves. Boot-trigger behavior has not yet
  been accepted by an actual reboot test. SQL remains Developer, HTTP/IP-allowlist
  transport is unchanged, backups remain local, and external alert delivery is not
  configured. This deployment is not yet a fully accepted production release.

Microsoft references: [fixed Analysis Services ports](https://learn.microsoft.com/en-us/analysis-services/instances/configure-the-windows-firewall-to-allow-analysis-services-access),
[encrypted model backup/restore](https://learn.microsoft.com/en-us/analysis-services/multidimensional-models/backup-and-restore-of-analysis-services-databases).
