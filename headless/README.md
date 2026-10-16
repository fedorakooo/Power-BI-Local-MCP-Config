# Headless Report Server experiment

Status: experimental. Local SSAS model deployment, DAX, MCP thin-PBIX compilation and Desktop RS rendering verified. Real customer-model migration and Report Server upload/rendering remain to be verified.

## Architecture

1. An SSAS Tabular database hosts model metadata and data. Model deployments/processing use TOM/XMLA instead of saving a Desktop process.
2. A legacy report-only PbixProj contains report definitions, resources and an explicit SSAS live connection.
3. A pinned external compiler produces a thin PBIX without Power BI Desktop or UI automation.
4. The existing Report Server MCP backs up, publishes an approved artifact and verifies its server SHA256.

This requires a migration from a PBIX with an embedded model. Removing DataModel from a ZIP is not a model migration. A compiled package does not prove that SSAS queries or Report Server rendering work.

## Verified local proof, 2026-10-16

Using pbi-tools Core 1.2.0 and a private .NET 8.0.32 runtime, an isolated copy of the seed report was compiled to a thin PBIX. The first page display name was changed in source to `Headless build validation`. Verified ZIP integrity, five report pages, exact report-layout equality with the edited source, absence of an embedded model, and unchanged original seed hash. The connection is an example placeholder; the output must not be published as a functioning report.

Private experiment files and evidence live in `generated/headless-poc/`; they are not distributed or tracked. Report metadata/settings in this packaging-only proof are generic upstream sample values, not a production migration of the original settings.

A separate SQL Server 2025 Enterprise Developer SSAS Tabular instance `PBIMCPTEST` was then installed locally with the user's explicit license acceptance. The synthetic database `PowerBIMcpHeadlessLab` returned 48.16%; a new measure deployed through TOM returned 49.16%. The new MCP built a one-page live-connected PBIX, and Desktop RS rendered 49.16% and the Manager slicer. No Desktop Save was used. Preserving the original report configuration/theme was necessary: an earlier test with an incomplete configuration failed rendering and was not considered successful.

See [VALIDATION.md](VALIDATION.md) for evidence boundaries and [config.example.json](config.example.json) for the optional MCP configuration.

## Optional headless MCP

The standalone entry point below is not automatically registered in STAIR.
`Start-Headless.ps1 -WithPowerBIStack` configures its HTTP route inside the existing
IP-restricted Caddy frontend; see [setup instructions](SETUP.ru.md).

```powershell
Set-Location C:\PowerBI-MCP\services\powerbi-reportserver-mcp
& .\.venv\Scripts\python.exe -m pbirs_mcp.headless_build --config C:\PowerBI-MCP\headless\config.local.json
```

Tools: `inspect_headless_report(project)` and `build_headless_report(project, expected_revision)`.

Enroll the source folder and exact SSAS connection, pin the external compiler SHA256, and supply its .NET runtime. Builds run from a reviewed snapshot and create a new release filename. The tool rejects embedded model projects, stale revisions, changed connection targets, passwords and cloud-artifact references. It verifies the compiled report definition and connection against source before exposing the release. It does not deploy a model or publish the report.

## Prepare an SSAS test instance

Download SQL Server Developer media from Microsoft's official downloads page, verify the Microsoft signature, and review its license terms. Developer is for development/testing; do not use this test setup as the customer production license plan.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Install-TestSSAS.ps1 -MediaRoot C:\SQLMedia -ValidateOnly
# After the operator has accepted the SQL Server license:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Install-TestSSAS.ps1 -MediaRoot C:\SQLMedia -AcceptSqlServerLicense
```

The script installs only Analysis Services in Tabular mode as a separate `PBIMCPTEST` instance, using a virtual service account and manual startup. It refuses an existing instance. Model deployment, memory sizing, network access, consumer read roles and Report Server authentication require separate configuration and verification.

## Gates before enabling this backend in MCP

- Real SSAS endpoint and database, Windows identities, least-privilege model roles.
- Schema/DAX/partition compatibility and a validated data-loading path; do not blindly deploy Desktop-only metadata.
- Headless model deploy/process/query verification against representative test data.
- Headless thin PBIX build, preserving supported report settings/resources and validated connection metadata.
- Upload to a separate enrolled Report Server test report and verify actual rendering and hash.
- Backup/rollback for both the SSAS model and report. Model and report publication are separate operations, not an atomic transaction.
- Compiler version pinning and redistribution/license review: pbi-tools is AGPL-3.0, third-party software, not a Microsoft-supported PBIX build API. It is not automatically bundled by the existing installer.

## Sources

- Desktop Bridge methods (no Save method in the documented list): https://learn.microsoft.com/en-us/power-bi/developer/agentic/power-bi-desktop-bridge-overview
- Compiler limitation: https://pbi.tools/cli/usage-core.html
- Report Server SSAS live connections: https://learn.microsoft.com/en-us/power-bi/report-server/data-sources
- SSAS setup: https://learn.microsoft.com/en-us/analysis-services/instances/install-windows/install-analysis-services
- SQL Server Developer download: https://www.microsoft.com/en-us/sql-server/sql-server-downloads
