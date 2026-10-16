# Verification scope

The original private deployment passed four relocation/configuration tests, MCP tool discovery
for all four services, real Report Server catalog authentication and a separate Desktop launch.
The launcher fix was checked from C:\Windows\system32 on 2026-10-16.

The owner-authorized validated PBIX was subsequently added to the public repository.
Credentials and internal endpoints remain excluded. Supply your own server configuration,
then repeat setup and readiness checks.
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

## Caddy certificate-chain handling — 2026-10-16

Regression tests passed for Python certificate failure selecting Windows validation,
failed Windows validation stopping the download, and SHA512 failure preserving the
existing binary. A real official Caddy archive download and SHA512 verification passed.
The Windows PowerShell HTTPS helper also downloaded the official checksum manifest.
The reported second-machine trust environment has not been tested remotely.

## Nested operation progress — 2026-10-16

Windows PowerShell parsing and ValidateOnly passed with the shared structured-event renderer.
The four configuration tests and two Caddy regression tests passed. Real Caddy download
and checksum verification produced 21 phase/byte progress events. All ten dependency imports
completed with individual progress. Desktop RS's already-installed fast path emitted valid
progress; a fresh MSI installation was not rerun. Task/firewall operations were not repeated
solely to test their display labels.

## Caddy execute permissions — 2026-10-16

Reproduced a protected executable DACL with owner BUILTIN/Administrators after moving
the binary from an elevated Python TemporaryDirectory. The installer now copies verified
bytes into a fresh file in the destination bin directory before atomic replacement,
so destination directory permissions are inherited. Setup also explicitly grants the
interactive deployment user read/execute on caddy.exe.

The two Caddy regression tests passed, a real archive download passed SHA512 verification,
and the installed file's AreAccessRulesProtected changed from true to false.
A temporary interactive scheduled task with RunLevel Limited successfully executed
the fixed caddy.exe version command; the validation task was then removed.

## Upstream Report Server diagnosis — 2026-10-16

The independent PowerShell upstream test passed TCP and saved-credential catalog access
against the existing local deployment, returning only a report count. A closed local
TCP port produced network_status=ConnectFailure with no upstream response body.
Readiness now preserves a failed list_reports result and stops repeating the upstream
catalog call once that tool reports failure.
