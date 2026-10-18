# Единый запуск headless-решения

Проект: STAIR. Статус: экспериментальная локальная реализация.

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

- Windows x64 и стабильный CPython x64 3.10+.
- Для тестового SSAS нужен PowerShell 7.4+ x64. Скрипт ищет его в PATH и стандартной
  папке установки; при отсутствии `-Setup` скачивает отдельную PowerShell 7.6.7
  в `tools/headless/`, проверяет закреплённый SHA256 архива и подпись Microsoft.
- Установка SSAS: повышенные права администратора, достаточно места для ISO и установки,
  доступ к Microsoft, GitHub, NuGet и Python package index.
- Для старого Power BI стека также Node.js LTS и его настройки `deployment.local.json`.
- SQL Server Developer разрешён только для разработки и тестирования. Для production нужен
  подходящий лицензированный SSAS. pbi-tools распространяется под AGPL-3.0; проверьте
  требования лицензии перед использованием у заказчика.

Python установите заранее. Windows PowerShell 5.1 остаётся на месте; отдельная PowerShell
не меняет PATH и системную оболочку. Скрипт не принимает лицензии SQL Server за оператора.
При нестандартных путях используйте `-Python` и `-PowerShell7`.

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

Если опубликованный отчёт сообщает «Не удалось подключиться к серверу служб Analysis
Services», выполните на сервере под владельцем установки:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\scripts\Diagnose-ReportServerSSAS.ps1
```

Это только диагностика: службы и текущий порт тестового SSAS, источник опубликованного
отчёта без секретов, DAX под оператором, роли базы и ограниченные строки журналов.
Можно добавить `-RequestId <GUID>` из ошибки. Успешный DAX под администратором
не подтверждает права пользователя отчёта. Скрипт не меняет роли, аутентификацию,
порты и опубликованный PBIX. Вывод с именами учётных записей предназначен для
внутренней диагностики; не публикуйте его в открытом репозитории.

Если подтверждено отсутствие доступа конкретного Windows-пользователя к тестовой базе,
`scripts/Grant-HeadlessLabReader.ps1` позволяет оператору явно добавить его в роль Read.
Запускайте через установленный PowerShell 7 с `-Server localhost:<текущий порт>`,
`-ClientDirectory C:\PowerBI-MCP\tools\headless\as-client` и `-Member 'COMPUTER\user'`.
Сначала можно указать `-ValidateOnly`. Скрипт работает только с базой
`PowerBIMcpHeadlessLab`, проверяет её маркер synthetic-test-data-only и не выдаёт
права администратора сервера. Он не настраивает роли заказчика или Windows SSO.

```powershell
powershell.exe -NoProfile -File C:\PowerBI-MCP\Start-Headless.ps1 -Status
powershell.exe -NoProfile -File C:\PowerBI-MCP\Start-Headless.ps1 -Stop
```

Остановка затрагивает только процесс headless MCP этой установки, подтверждённый путём,
PID, временем создания и командной строкой. SSAS, Desktop и чужие процессы не останавливаются.
`-Restart` перезапускает MCP; обычный запуск также обновляет конфигурацию и заменяет свой процесс.

При `-WithPowerBIStack` Headless MCP запускает существующая задача планировщика
вместе с четырьмя другими MCP и Caddy. Это позволяет завершить SSH-команду без
завершения Headless-процесса. `-Status` показывает режим gateway-supervised и
наличие слушателя; лог — `services/powerbi-reportserver-mcp/runtime/stair-powerbi-headless.log`.
`-Stop -WithPowerBIStack` останавливает весь стек. Задача по-прежнему зависит от
интерактивного входа владельца установки; независимость от выхода пользователя
не заявляется. Отдельный режим без `-WithPowerBIStack` использует detached-процесс
и не предназначен для запуска из Windows OpenSSH с последующим отключением.

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
`-WithPowerBIStack` также добавляет маршрут `/stair-powerbi-headless/mcp` в существующий
Caddy, внутри действующего списка разрешённых IP. Перед применением конфигурация проверяется
через `caddy validate`; предыдущая версия сохраняется в `Caddyfile.before-headless`.

## 5. Результат и подключение

Backend endpoint по умолчанию: `http://127.0.0.1:8020/mcp`.
При запуске с `-WithPowerBIStack` проверяется MCP через proxy:
`http://127.0.0.1:8012/stair-powerbi-headless/mcp` (порт берётся из deployment.local.json).
Скрипт также печатает публичный адрес headless MCP рядом с четырьмя существующими URL.

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
Backend 8020 доступен только с этой машины. При `-WithPowerBIStack` удалённые клиенты используют
существующий frontend Caddy и его список разрешённых IP; дополнительные открытые порты не нужны.
Новый MCP **не регистрируется автоматически в STAIR**. Доступ из кластера, персональная
аутентификация и разрешения агента проверяются отдельно. Текущий пилотный frontend использует
сетевой allowlist без отдельного API key; для production требуется согласованная аутентификация.
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
