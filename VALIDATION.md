# Verification scope

The original private deployment passed four relocation/configuration tests, MCP tool discovery
for all four services, real Report Server catalog authentication and a separate Desktop launch.
The launcher fix was checked from C:\Windows\system32 on 2026-10-16.

This public source distribution excludes the private PBIX, credentials and internal endpoints.
Supply your own compatible report and configuration, then repeat setup and readiness checks.
Remote routing, STAIR, TLS/authentication and embedding permissions require environment-specific validation.

## Flexible Python selection — 2026-10-16

Windows PowerShell checks passed for explicit Python selection, existing environment reuse,
invalid explicit-path rejection without fallback, and automatic launcher discovery.
Local interpreters used: CPython3.12 and CPython3.15 x64. Installed dependency imports
passed on3.12; a complete dependency install and Power BI workflow on3.15 was not run.
Four existing deployment configuration tests also passed after this change.

## Progress tracking — 2026-10-16

Windows PowerShell parsing and the two-stage ValidateOnly path passed. Structured
readiness progress passed against all four local HTTP MCP services with a real
Report Server catalog read and no report writes or Desktop launch. The full Setup
was not rerun for these display changes.
