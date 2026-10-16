# Единый запуск headless-решения

Автор: Aliaksandr Fedaraka. Статус: экспериментальная локальная реализация.

## Что делает скрипт

`Start-Headless.ps1` настраивает отдельное Python-окружение, скачивает закреплённые версии
pbi-tools Core 1.2.0, .NET 8.0.32 и SSAS-клиентов, подготавливает исходники тонкого отчёта,
запускает HTTP MCP и проверяет настоящий MCP handshake, список инструментов и чтение проекта.
`-TestBuild` дополнительно собирает новый PBIX через HTTP MCP и проверяет отклонение устаревшей ревизии.

В режиме `lab` скрипт использует только экземпляр `PBIMCPTEST` и синтетическую базу
`PowerBIMcpHeadlessLab`. Повторный запуск проверяет данные DAX, сохраняет визуальные правки
исходников и обновляет подключение при изменении динамического порта SSAS.
Ожидаемые значения: базовая мера 48.16%, изменённая мера 49.16%.

## 1. Требования

- Windows x64, стабильный CPython x64 3.10+ и PowerShell 7 для тестового SSAS.
- Установка SSAS: повышенные права администратора, достаточно места для ISO и установки,
  доступ к Microsoft, GitHub, NuGet и Python package index.
- Для старого Power BI стека также Node.js LTS и его настройки `deployment.local.json`.
- SQL Server Developer разрешён только для разработки и тестирования. Для production нужен
  подходящий лицензированный SSAS. pbi-tools распространяется под AGPL-3.0; проверьте
  требования лицензии перед использованием у заказчика.

При отсутствии Python или PowerShell установите их заранее; скрипт не принимает лицензии
за оператора. При нестандартных путях используйте `-Python` и `-PowerShell7`.

## 2. Первый запуск на новой тестовой машине

Откройте **PowerShell от администратора**. Для новой копии репозитория:

```powershell
git clone https://github.com/fedorakooo/Power-BI-Local-MCP-Config.git C:\PowerBI-MCP
```

После ознакомления и согласия с лицензией SQL Server Developer:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Headless.ps1 -Setup -InstallTestSSAS -AcceptSqlServerLicense -TestBuild
```

Один этот запуск создаст приватный `headless.deployment.local.json` из примера, скачает
и проверит установщик Microsoft, при необходимости установит только SSAS Tabular,
создаст синтетическую модель и отчёт, запустит MCP и соберёт проверочный PBIX.
Если установка SQL требует перезагрузки, она не выполняется автоматически.
После разрешённой оператором перезагрузки повторите команду запуска.

## 3. Повторный запуск / остановка

```powershell
git -C C:\PowerBI-MCP pull
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Headless.ps1 -Restart -TestBuild
```

Для обновления зависимостей после изменения репозитория используйте `-Setup`.
Лабораторный экземпляр имеет ручной запуск; скрипт запускает его и обнаруживает TCP-порт.
После перезапуска SSAS снова запустите скрипт для обновления подключения в тестовом отчёте.

```powershell
powershell.exe -NoProfile -File C:\PowerBI-MCP\Start-Headless.ps1 -Status
powershell.exe -NoProfile -File C:\PowerBI-MCP\Start-Headless.ps1 -Stop
```

Остановка затрагивает только процесс headless MCP этой установки, подтверждённый путём,
PID, временем создания и командной строкой. SSAS, Desktop и чужие процессы не останавливаются.
`-Restart` перезапускает MCP; обычный запуск также обновляет конфигурацию и заменяет свой процесс.

## 4. Поднять и существующие четыре MCP + Supergateway/Caddy

Сначала заполните `deployment.local.json` по основной инструкции: реальный portal,
report GUID, разрешённые адреса STAIR, пути и учётные данные Windows.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Headless.ps1 -Setup -InstallTestSSAS -AcceptSqlServerLicense -WithPowerBIStack -AcceptMicrosoftEula -TestBuild
```

Для уже установленного стека:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Headless.ps1 -Restart -WithPowerBIStack -TestBuild
```

Этот вариант вызывает прежний `Start-PowerBI.ps1 -NoDesktop`: он запускает Modeling,
Report Server, Authoring, Desktop MCP, их Supergateway и Caddy и печатает URL.
Power BI Desktop автоматически не открывается. GUI-инструментам по-прежнему нужен интерактивный
сеанс. Headless MCP запускается отдельно, с собственным Streamable HTTP транспортом SDK.

## 5. Результат и подключение

Локальный endpoint по умолчанию: `http://127.0.0.1:8020/mcp`.

- `runtime/headless/mcp-client.json` — настройки клиента MCP;
- `runtime/headless/codex.mcp.toml` — фрагмент для MCP-конфигурации Codex;
- `runtime/headless/mcp-evidence.json` — результат HTTP MCP проверки и сборки;
- `runtime/headless/ssas-evidence.json` — проверка DAX тестовой модели;
- `runtime/headless/stdout.log`, `stderr.log` — журналы;
- `headless/config.local.json` — сгенерированная конфигурация сервиса;
- `headless/projects/headless-lab/` — редактируемый тестовый проект;
- `services/powerbi-reportserver-mcp/runtime/release/` — собранные PBIX.

Инструменты: `inspect_headless_report` и `build_headless_report`. Сначала получите `revision`
через inspect, затем передайте её в `expected_revision` при build.
Endpoint доступен только с этой машины. Новый MCP **не добавляется автоматически в Caddy или STAIR**;
для удалённого доступа нужен отдельно проверенный proxy с аутентификацией и сетевыми правилами.
Скрипт не создаёт задачу автозапуска headless MCP после входа или перезагрузки.

## 6. Существующий SSAS заказчика

Скопируйте `headless.deployment.example.json` в `headless.deployment.local.json` и укажите:

```json
{
  "mode": "existing",
  "http_port": 8020,
  "ssas_server": "",
  "source_root": "C:\\Reports\\SalesThinProject",
  "connection_string": "Data Source=ssas.example.com:23831;Initial Catalog=SalesAnalytics;Cube=Model",
  "report_version": "1.28",
  "project": "sales-report"
}
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Headless.ps1 -Setup -TestBuild
```

Исходники должны быть заранее подготовленным legacy PbixProj с `Report/report.json`,
`Connections.json`, `Version.txt` и ресурсами. PBIP/PBIR автоматически не конвертируется.
Подключение должно точно совпадать с зарегистрированной строкой, без паролей и cloud references.
Этот режим не меняет чужую SSAS, не мигрирует модель и не подтверждает доступность её данных.

## Ограничения проверки

Скрипт не публикует тестовую сборку на Report Server автоматически. Публикация выполняется
существующим Report Server MCP после проверки совместимости, прав SSAS и утверждения артефакта.
Локальный HTTP MCP тест не подтверждает рендеринг в Report Server, доступ пользователей или работу STAIR.
Для произвольного клиентского PBIX сначала нужна миграция встроенной модели в SSAS и подготовка тонкого отчёта.
Это не универсальный production-ready установщик для любого исходного PBIX.
