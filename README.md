# Power-BI-Local-MCP-Config

By **Aliaksandr Fedaraka**. Windows deployment and configuration for Power BI MCP automation.

Includes custom Desktop and Report Server MCP services, pinned Microsoft Modeling MCP and
Desktop Bridge dependencies, and Supergateway HTTP transport behind an IP-restricted Caddy proxy.

## Setup

See the [step-by-step Russian instructions](README.ru.md).

1. Copy this repository to `C:\PowerBI-MCP`.
2. Install Python 3.12 and Node.js LTS.
3. Supply your own Report Server compatible PBIX in `reports/`.
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

Generated client settings: `generated/codex-mcp.toml`.

## Operational limits

Desktop requires an unlocked interactive Windows session. The Save MCP tool invokes Windows
UI Automation internally. Publication requires an operator-issued one-use approval.
The HTTP transport defaults to loopback access; remote use requires explicit network rules
and HTTPS/authentication appropriate to your environment.

PBIX data, saved credentials, local configurations and runtime environments are excluded.
Microsoft dependencies remain governed by their respective licenses.
See [verification scope](VALIDATION.md).
