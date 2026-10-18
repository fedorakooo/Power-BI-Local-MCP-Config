# Создание динамических отчётов через MCP

## Автоматическая публикация без approval_id

Оператор может один раз включить автоматический режим для конкретного агента и
зарегистрированных aliases. Тогда запрос в чате достаточен для публикации;
ручная команда approve-create/approve и передача ID больше не требуются.
Режим по умолчанию для остальных агентов и отчётов остаётся с approval.

```powershell
Set-Location C:\PowerBI-MCP\services\powerbi-reportserver-mcp
.\.venv\Scripts\python.exe -m pbirs_mcp.admin --config config.local.json publication-policy --actor stair --mode automatic --report staging --report sales-new --action publish --action create
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-Headless.ps1 -Restart -WithPowerBIStack
```

Агент сначала вызывает `get_publication_policy`. В automatic-режиме он передаёт
`expected_sha256` из результата сборки. При обновлении также нужен
`expected_current_sha256` из свежего `download_report_backup`; его агент получает
сам. Новое создание по-прежнему не перезаписывает существующий каталог.

Каждая автоматическая запись получает серверный журнал в
`runtime/automatic-operations/`. Состояния pending/uncertain/verification_mismatch
блокируют следующие автоматические записи этого alias, включая после рестарта.
Оператор должен проверить реальный каталог/хэши, затем архивировать разрешённую
запись журнала после устранения причины. Агент не удаляет журнал и не сбрасывает
блокировку. Восстановление из backup сохраняет прежний approval-порядок.
Политика переживает повторный Setup для того же Report Server.

Вернуть ручной режим можно CLI `publication-policy --actor stair --mode approval
--report staging --report sales-new`, затем перезапустить MCP.

Headless MCP умеет создавать новый thin-report на зарегистрированной модели SSAS,
редактировать его страницы и визуалы, затем компилировать новый PBIX без Desktop Save.
Модель данных уже должна существовать. Это не импорт произвольного источника данных
и не универсальная миграция старых PBIX. Динамичность означает live-запросы к SSAS
при открытии отчёта и взаимодействии с фильтрами; непрерывный streaming не заявляется.

## Инструменты

- `list_report_workspace`: модели, разрешённые поля, проекты, типы визуалов.
- `create_dynamic_report`: новые страницы/визуалы на выбранной модели; существующий
  проект не перезаписывается. Используются только общие metadata/theme ресурсы
  совместимости, старые страницы и визуалы не копируются.
- `update_dynamic_report`: полный новый список страниц, текущая revision и backup
  предыдущего layout. Работает только с проектами, созданными этим инструментом.
- `inspect_headless_report`: страницы, привязки визуалов и revision. Для созданных
  MCP-проектов также возвращает `editable_pages` — полную спецификацию с заголовками,
  полями, порядком, координатами и размерами визуалов. Используйте её как основу
  обновления и сохраняйте неизменяемые страницы точно; не восстанавливайте их
  геометрию по предположениям.
- `build_headless_report`: новая уникальная сборка PBIX с проверкой layout,
  подключения и SHA256.

Поддержаны `card`, `columnChart`, `slicer`, строковые категории и числовые меры;
холст 1280x720, до 8 страниц и 20 визуалов
на странице. Публикация и права SSAS — отдельные операции. Созданные проекты
хранятся в `headless/created-reports/` и исключены из Git.

Лабораторная модель регистрируется автоматически при `Start-Headless.ps1`.
Для своей модели оператор задаёт `creation_profiles` в headless.deployment.local.json:
совместимый source, report_version, connection_string без пароля и schema с
разрешёнными таблицами, columns и measures. Агент не задаёт адрес сервера или DAX
через инструменты создания визуалов.

## Публикация нового отчёта

Report Server MCP дополнен `publish_new_reviewed_pbix`. Инструмент работает только
с заранее зарегистрированным адресом назначения. В стандартном режиме нужен
одноразовый operator approval; в автоматическом режиме выше он не нужен.
Существующий каталог никогда не перезаписывается: конфликт означает остановку.
После создания инструмент скачивает PBIX и сравнивает SHA256; отображение визуалов
проверяется отдельно. При неопределённом результате approval потребляется, повтор
без проверки каталога и нового согласования запрещён.

Оператор регистрирует destination один раз (пример; измените folder/name/actor):

```powershell
Set-Location C:\PowerBI-MCP\services\powerbi-reportserver-mcp
.\.venv\Scripts\python.exe -m pbirs_mcp.admin --config config.local.json enroll-new --actor stair --alias sales-new --folder '/STAIR MCP Validation' --name 'STAIR Dynamic Sales'
```

Перезапустите MCP. После проверки конкретного build оператор выдаёт разрешение:

```powershell
.\.venv\Scripts\python.exe -m pbirs_mcp.admin --config config.local.json approve-create --actor stair --report sales-new --file 'C:\PowerBI-MCP\services\powerbi-reportserver-mcp\runtime\release\REVIEWED-BUILD.pbix'
```

Для одной команды из любого каталога используйте `scripts/Approve-NewReport.ps1`
с `-Destination sales-new -FileName REVIEWED-BUILD.pbix -ExpectedSha256 <проверенный SHA256>`.
Wrapper передаёт ожидаемый hash операторской CLI; при несовпадении approval не выдаётся.

Разрешение связывает пользователя MCP, destination, полный путь отчёта и SHA256
файла; действует 15 минут. Операторская CLI не предоставляется агенту как MCP.
Новые destinations сохраняются при повторном Setup для того же Report Server.
В STAIR после обновления сервера обновите список tools и явно включите новые
инструменты в настройках агента — автоматического подключения новых tools нет.
