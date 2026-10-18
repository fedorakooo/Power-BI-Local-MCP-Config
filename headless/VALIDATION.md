# Headless backend validation — 2026-10-16

## Confirmed locally

| Check | Result |
|---|---|
| SQL Server 2025 Enterprise Developer, separate SSAS Tabular test instance | Installed; service running, manual startup |
| Synthetic model creation and processing through TOM | Passed |
| DAX base ratio / manager-filtered ratio | 0.4816 / 0.4979 |
| Add a new measure through TOM SaveChanges | Passed; new measure = 0.4916 |
| Real stdio MCP initialize/list/call | Passed |
| Stale source revision | Rejected without compilation |
| Source -> thin PBIX compilation through MCP | Passed |
| ZIP, absence of embedded DataModel, report/connection equality | Passed |
| Desktop RS opens exact compiled thin PBIX, clean state | Passed |
| Official Bridge screenshot, inspected visually | KPI 49.16%, Manager slicer, no error shown |
| GUI Save or clicking Desktop Save | Not used |
| Five guard tests (model, target, password, cloud reference, enrollment) | Passed |

The test uses synthetic data, not a migrated customer model. Current report sources contain only the lab page. This is a replacement build architecture, not a way to flush unsaved changes from an arbitrary Desktop process.

Verified rendered artifact SHA256:

`ae720c740b7f7498ad28add4dd5326b0e9c5a09eadd32d2bfbcdae7c11ee7501`

The original seed PBIX retained SHA256:

`ba44a423162888f742a956f76410c13b344aa95aa984ba8838aebcd13edc623e`

Evidence files are private under `generated/headless-poc/`: `ssas-evidence.json`, `mcp-evidence.json`, `headless-preview.png`, build logs and source snapshots. The public repository does not include lab PBIX binaries, SQL media, third-party tools, client libraries, local host configuration or credentials.

## Remaining gates

- SQL Setup returned 3010 (reboot required). The service and tests work in the current session, but post-reboot readiness remains unverified. No automatic reboot was performed.
- Current SSAS port was dynamically assigned. A deployed environment needs a controlled stable endpoint, memory sizing and explicit network policy.
- Deploy the real customer model with compatible partitions, data sources and measures; preserve unsaved work before migration.
- Set least-privilege SSAS read/write identities and Report Server Windows authentication/delegation as required by the topology.
- Validate the thin-report compiler output on the customer's exact Report Server version and render it from a separately enrolled test report.
- Exercise approved publication and model/report rollback. No upload of the lab report to the production Report Server has been performed.
- Register the new MCP/gateway/toolset only after these integration checks. Current STAIR toolsets remain on the previous configuration.
- Review pbi-tools AGPL-3.0 licensing before packaging/distribution for customers. No modified compiler code or compiler binary is bundled here.

## Unified bootstrap verification, 2026-10-16

`Start-Headless.ps1 -Setup -TestBuild` completed locally using the already installed
`PBIMCPTEST` instance. A separate pinned Python environment was created; cached compiler
and .NET archives were hash-verified and extracted; SSAS clients were loaded successfully.
The generated HTTP MCP at `127.0.0.1:8020/mcp` passed initialize, tools/list, inspect,
stale-revision rejection and actual thin PBIX compilation.

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File Start-Headless.ps1 -Restart -TestBuild`
also passed under Windows PowerShell 5.1. It reused the SSAS database and sources, stopped
only its recorded MCP process and created another verified artifact. DAX results were
0.4816 (base), 0.4979 (Cara), and 0.4916 (updated measure).

Three setup tests passed: preserving edited report layout on rerun, leaving existing-mode
sources unchanged, and refusing to adopt an unmarked source. Five existing headless scope
tests passed. Fresh SQL installation through this new wrapper, the combined `-WithPowerBIStack`
path on a new machine, remote access, automatic startup, and Report Server upload/rendering
were not exercised by this bootstrap verification. The earlier dedicated SQL installer and
Desktop RS rendering proof are separate evidence, not claims that these paths were tested here.

### Missing PowerShell runtime regression

The bootstrap now searches PATH and the standard PowerShell 7 installation directory,
and provisions a private PowerShell 7.6.7 x64 during `-Setup` if no suitable runtime exists.
The archive SHA256 is pinned to the official Microsoft GitHub release; the extracted
executable must have a valid Microsoft Authenticode signature and pass a runtime probe.
The real download/extraction/probe completed under Windows PowerShell 5.1. The private
runtime then passed the SSAS DAX check and HTTP MCP thin-report build. Discovery tests
also cover rejecting Windows PowerShell 5.1, permitting provisioning only during Setup,
and refusing to silently substitute an invalid explicit `-PowerShell7` path.

### Headless proxy route

The new managed Caddy route was tested locally with real Caddy and FastMCP processes.
Initialize, tools/list, inspect and actual thin PBIX compilation passed through
`/fedaraka-powerbi-headless/mcp`. Reapplying the route produced no configuration change.
Three regression tests cover IP-handle placement, preserving the existing deny response,
Host header rewriting, port changes, and rejecting unmanaged/unrestricted templates.
The target Windows server still needs to pull and apply this version; these local tests
do not establish reachability from STAIR or Report Server publication/rendering.

### Integrated STAIR publication and lifecycle regression (2026-10-18)

On the enrolled synthetic test installation, STAIR discovered the five MCP routes.
Its agent backed up the test report, published the previously reviewed thin PBIX
once with an operator-issued approval, then downloaded it again and verified its
SHA256. An independent download also matched the approved artifact (66,841 bytes,
valid ZIP, no embedded DataModel). No Desktop Save or recompilation was used for
this publication. Rendering and Report Server's SSAS access remain unverified;
upload verification is not a rendering test or a claim of customer readiness.

An earlier outage left Caddy listening while every backend had stopped. The task
reported STATUS_CONTROL_C_EXIT; the initiating cause was not established. The
supervisor now uses pythonw and starts Caddy through a parent-pipe guard. A real
Windows process regression closes the guard's parent pipe and verifies that both
guard and child exit. This fix was tested locally; target rollout is separate.
