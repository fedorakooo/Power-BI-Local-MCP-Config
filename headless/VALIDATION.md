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
