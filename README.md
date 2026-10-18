# Power-BI-Local-MCP-Config

By **Aliaksandr Fedaraka**. Windows deployment and configuration for Power BI MCP automation.

Includes custom Desktop and Report Server MCP services, pinned Microsoft Modeling MCP and
Desktop Bridge dependencies, and Supergateway HTTP transport behind an IP-restricted Caddy proxy.

## Setup

For the new Desktop-free SSAS/thin-report experiment, use the single entry point
[`Start-Headless.ps1`](Start-Headless.ps1). See [Russian setup commands and limits](headless/SETUP.ru.md).
It can also start the existing four MCP services and Supergateway/Caddy with `-WithPowerBIStack`.
With that flag, the headless MCP also receives a route through the existing IP-restricted
Caddy frontend. Its backend stays on loopback; platform connectivity and authentication
must still be verified before production use.

See the [step-by-step Russian instructions](README.ru.md).

1. Copy this repository to `C:\PowerBI-MCP`.
2. Install stable Windows CPython x64 (3.10 or newer) and Node.js LTS.
3. Use the included `reports/Fedaraka Server Automated.pbix`, or supply another compatible PBIX.
4. Copy `deployment.example.json` to `deployment.local.json`; replace the example portal,
   report GUID and report file with your values.
5. Run elevated under the Windows user who will operate Desktop, after accepting Microsoft licenses:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-PowerBI.ps1 -Setup -AcceptMicrosoftEula
```

Subsequent start:

```powershell
powershell.exe -NoProfile -File C:\PowerBI-MCP\Start-PowerBI.ps1
```

To restart gateways and free all five configured ports first:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-PowerBI.ps1 -Restart
```

When the scheduled task is stopped, ordinary startup also stops remaining deployment
processes and frees listeners on frontend_port through frontend_port+4 before starting.
Cleanup terminates listener processes on these ports, including other applications using
them, and verifies the ports are free. It refuses protected Windows processes, the calling
process/ancestors and Power BI Desktop/model processes. Run elevated if the listener owner
requires it. An already-running gateway task is reused unless -Restart is specified.

Generated client settings: `generated/codex-mcp.toml`.

## One-command startup and STAIR URLs

After Setup, start/restart all MCP gateways and print externally advertised URLs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-PowerBI.ps1 -Restart -PublicHost windows-mcp.example.com
```

Use the Windows MCP machine's real DNS/IP for PublicHost. The command checks all four
services, the Report Server catalog and Desktop, then prints four Streamable HTTP URLs
through the shared frontend port. It saves `generated/stair-endpoints.json` and remembers
PublicHost for subsequent runs. If none was supplied or saved, it advertises the local
computer name; confirm that STAIR can resolve it. Internal backend ports are informational
and remain blocked for remote access.

For initial STAIR network access, apply the known egress sources with one Setup command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-PowerBI.ps1 -Setup -AcceptMicrosoftEula -PublicHost windows-mcp.example.com -StairAddresses "192.0.2.10,192.0.2.11"
```

Replace example addresses with actual STAIR egress IPs/CIDRs. This updates the proxy and
Windows firewall allowlist; loopback is retained. External routing/firewalls must also
permit the frontend TCP port. Endpoint export does not prove connectivity from STAIR.
The current trusted-network pilot uses authentication=None; see the HTTPS/authentication
operational limits before wider exposure. Register each URL as a separate STAIR toolset
using the names printed by the launcher.

## Progress tracking

The launcher shows a PowerShell progress bar and numbered text messages: 16 stages
for Setup, four for startup, two for validation. Nested bars show prerequisite checks,
permissions, Python installation/check/import operations, configuration files, credentials,
task/firewall operations and MCP readiness. Imports identify each of ten modules.
Caddy has download/checksum/extract phases and a separate byte-based download bar
when the server provides Content-Length. Without a known size, it reports bytes received
without inventing a percentage. Windows TLS fallback uses Windows download reporting.
Desktop RS reports download, hash, signature, installation and final verification;
the Microsoft installer wait reports elapsed seconds with an indeterminate bar.
MCP checks identify initialization, tool discovery, upstream catalog access and Desktop
launch/Bridge readiness, with remaining startup deadlines during retries.
Stage percentages count completed operations, not time; only download bars measure bytes.
Pip/pnpm retain their own package/download output during installation.
On failure the current stage is printed and bars are cleared. Text messages remain
available when progress rendering is disabled or output is redirected.

## Python selection

There is no exact Python 3.12 requirement. Selection order is an explicit `-Python`
path, an existing deployment environment, the Python launcher's installed runtimes
(default first), then real Python executables on PATH. Microsoft Store aliases are
skipped on PATH. No Python installation or system-default change is performed.

```powershell
py -0p
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-PowerBI.ps1 -Setup -AcceptMicrosoftEula -Python "C:\path\to\python.exe"
```

Runtime eligibility (stable CPython 3.10+, Windows x64) is checked first. Setup then
installs the pinned dependencies, runs `pip check`, and imports the Windows/MCP modules.
An eligible interpreter is not a guarantee that every pinned dependency supports it.
The full Power BI workflow was validated on 3.12; discovery/selection was additionally
checked with installed 3.15. Changing an existing deployment's Python requires a new
deployment folder; the launcher does not silently replace its environment.

## Operational limits

### Gateway startup diagnostics

If all four MCP services pass but Desktop readiness times out, inspect the existing
Desktop instances without relaunching the report:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\scripts\Test-Desktop.ps1
```

The command reports process IDs, session IDs, main-window titles, enrolled paths,
Desktop version, PBIX hash/ZIP entries, WebView2 registrations, recent application faults
and official Bridge status. If Desktop has exited, add `-Launch` to open the enrolled
report once and monitor its initial exit code for up to20seconds. It refuses to launch
when any Desktop instance is already running. Run it in the intended unlocked Windows
user session; it does not accept dialogs or terminate the launched application.
Check the unlocked interactive session for first-run dialogs
and confirm the enrolled PBIX is actually loaded. `-NoDesktop` checks the four MCP
services and upstream Report Server independently of the Desktop readiness gate.

If MCP initializes but `list_reports` fails, test the upstream independently:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\scripts\Test-ReportServer.ps1
```

This reports the actual generated portal, a TCP check, and one read-only authenticated
catalog request using the saved credential. It catches unchanged example URLs and reports
HTTP status or WebException network status without printing passwords or upstream bodies.
It does not require a gateway restart. Correct portal/report settings in deployment.local.json
and rerun Setup when configuration is wrong; changing only the example JSON has no effect.

For a readiness timeout or `All connection attempts failed`, run:

```powershell
powershell.exe -NoProfile -File C:\PowerBI-MCP\Start-PowerBI.ps1 -Diagnose
```

This read-only command reports the scheduled task state/result, local listeners,
required executable paths and bounded gateway log tails. It does not print credentials
or full configuration files. Readiness failures also invoke these diagnostics automatically.
The supervisor records startup errors and child exit codes in `runtime/supervisor.log`
under the service folder. Requesting a scheduled task start does not prove the gateway
is listening; MCP readiness remains the success gate.

Startup migrates this installation's exact legacy scheduled task action to
`pythonw.exe`, avoiding a supervisor console window. A Caddy guard watches the
supervisor's stdin pipe and stops the proxy if its parent disappears. Normal
shutdown closes the child pipes before terminating unresponsive processes.
Apply with `Start-Headless.ps1 -Restart -WithPowerBIStack` for the combined stack,
or `Start-PowerBI.ps1 -Restart` for the Desktop stack alone. The task still uses
the deployment user's interactive logon; this does not make it a Windows service.
`0xC000013A` indicates interruption, without identifying its cause.

If the supervisor reports `child_start_failed` for Caddy with WinError5, while Caddy
runs in elevated PowerShell, update the repository. Older installers retained a protected
temporary-directory DACL when moving caddy.exe; current Setup inherits the bin folder's
permissions and explicitly grants the deployment user read/execute. Repair an existing
installation from elevated PowerShell under that same user:

```powershell
$deploymentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls 'C:\PowerBI-MCP\services\powerbi-reportserver-mcp\runtime\bin\caddy.exe' /grant:r "${deploymentUser}:RX"
powershell.exe -NoProfile -File C:\PowerBI-MCP\Start-PowerBI.ps1
```

### Corporate TLS certificates

Caddy downloads use verified Python TLS with system roots plus certifi. If Python
reports a certificate-chain validation failure on Windows, the installer retries
through Windows PowerShell/.NET certificate validation. Both paths verify TLS;
the official archive SHA512 is checked before replacing the executable.

If your proxy's CA is not trusted, ask your administrator to configure Windows trust
or supply an approved PEM bundle for this process:

```powershell
$env:POWERBI_MCP_CA_BUNDLE = 'C:\certificates\corporate-ca.pem'
```

Repeat Setup after updating trust. The variable applies to the Caddy Python downloader,
not every tool in the installation. GitHub release assets and redirects must also be reachable.

Desktop requires an unlocked interactive Windows session. The Save MCP tool invokes Windows
UI Automation internally. Publication follows the configured actor/report policy:
operator-issued one-use approval by default, or explicitly enabled automatic publication.
The HTTP transport defaults to loopback access; remote use requires explicit network rules
and HTTPS/authentication appropriate to your environment.

The owner-authorized validation PBIX, including its report data, is included publicly.
Saved credentials, local configurations and runtime environments are excluded.
Microsoft dependencies remain governed by their respective licenses.
See [verification scope](VALIDATION.md).

Headless MCP also supports creating and revising new SSAS live reports with KPI
cards, column charts and slicers. See [report authoring](headless/REPORT-AUTHORING.ru.md)
for the bounded model schema, tools, new-report destination enrollment and required
operator publication approval or explicitly enabled actor/report-scoped automatic
publication. In automatic mode no approval ID is needed; artifact/current-server
hashes, backups and persistent guards against uncertain retries remain enforced.
Source creation alone does not publish a report.
