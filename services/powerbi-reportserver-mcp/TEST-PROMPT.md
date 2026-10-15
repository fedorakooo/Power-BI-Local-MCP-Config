# Prompts for a fresh Codex chat

Reload Codex MCP connections or open a fresh chat after installing the configuration.
STAIR is not required for these tests.

## Read-only verification and image

```text
Use powerbi_modeling_local, powerbi_desktop_local and powerbi_reportserver_local directly, without STAIR.
Target only the open report “Fedaraka Server Automated - Power BI Desktop (September 2026)”.
Discover the exact instance and use its returned connectionName for all model calls.
Read #Measures[Fedaraka MCP Win Rate %] and run one DAX ROW query for its unfiltered
value and CALCULATE of that measure with dim_SaleTeams[manager] = "Cara Losch".
Expect approximately 48.16% and 49.79%.
Call get_dashboard_preview(project="rs-automation", page_name="Page 1") and show its image.
Call get_report_link(report="staging") and return the report URL and embed URL.
Download a staging backup and report its SHA256. The validated release SHA256 is
ba44a423162888f742a956f76410c13b344aa95aa984ba8838aebcd13edc623e;
report a mismatch explicitly rather than assuming the report is unchanged.
Do not modify, refresh, save, publish or restore anything during this check.
```

## Save through one MCP tool

```text
Use powerbi_desktop_local directly; do not use STAIR or Computer Use.
For project rs-automation, call get_dashboard_preview on Page 1 to obtain the current
saved PBIX hash. Then call save_report(project="rs-automation", expected_sha256=<that hash>)
exactly once. Do not issue clicks, key presses, coordinate actions or Save As commands.
Show status, resulting SHA256, backup_id and save_invocations.
Require saved_verified, has_unsaved_changes=false and save_invocations=1.
If the outcome is uncertain, inspect state and report it; do not retry Save automatically.
Capture and show a new get_dashboard_preview image afterwards.
Do not publish or restore in this test.
```

Saving can change the file SHA256 even if the displayed values remain the same.
A later publication requires approval for the new artifact hash and the current
server hash; old or consumed approvals cannot be reused.

## Publish a reviewed artifact

The operator first downloads a current staging backup and issues a one-use approval:

```powershell
.\.venv\Scripts\python.exe -m pbirs_mcp.admin approve --actor fedaraka --report staging --action publish --file "<absolute release PBIX path>" --expected-current-sha256 "<current server SHA256>"
```

Then provide the returned approval ID with this prompt:

```text
Use powerbi_reportserver_local. Publish only the reviewed release file
Fedaraka Server Automated.pbix to alias staging with approval_id=<OPERATOR_APPROVAL_ID>.
Call publish_reviewed_pbix once, then download_report_backup and verify the server
SHA256 matches the reviewed local file. Return the report and embed links.
On any uncertain response, inspect the server content and stop; do not retry the write.
Do not overwrite alias sales or change permissions, data sources or refresh schedules.
```

Operator approval issuance is deliberately outside the agent's MCP toolset.
