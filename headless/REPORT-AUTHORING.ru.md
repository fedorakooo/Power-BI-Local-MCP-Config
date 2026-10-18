# Создание динамических отчётов через MCP

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
- `inspect_headless_report`: страницы, привязки визуалов и revision.
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
с заранее зарегистрированным адресом назначения и одноразовым operator approval.
Существующий каталог никогда не перезаписывается: конфликт означает остановку.
После создания инструмент скачивает PBIX и сравнивает SHA256; отображение визуалов
проверяется отдельно. При неопределённом результате approval потребляется, повтор
без проверки каталога и нового согласования запрещён.

Оператор регистрирует destination один раз (пример; измените folder/name/actor):

```powershell
Set-Location C:\PowerBI-MCP\services\powerbi-reportserver-mcp
.\.venv\Scripts\python.exe -m pbirs_mcp.admin --config config.local.json enroll-new --actor fedaraka --alias sales-new --folder '/Fedaraka MCP Validation' --name 'Fedaraka Dynamic Sales'
```

Перезапустите MCP. После проверки конкретного build оператор выдаёт разрешение:

```powershell
.\.venv\Scripts\python.exe -m pbirs_mcp.admin --config config.local.json approve-create --actor fedaraka --report sales-new --file 'C:\PowerBI-MCP\services\powerbi-reportserver-mcp\runtime\release\REVIEWED-BUILD.pbix'
```

Для одной команды из любого каталога используйте `scripts/Approve-NewReport.ps1`
с `-Destination sales-new -FileName REVIEWED-BUILD.pbix -ExpectedSha256 <проверенный SHA256>`.
Wrapper передаёт ожидаемый hash операторской CLI; при несовпадении approval не выдаётся.

Разрешение связывает пользователя MCP, destination, полный путь отчёта и SHA256
файла; действует 15 минут. Операторская CLI не предоставляется агенту как MCP.
Новые destinations сохраняются при повторном Setup для того же Report Server.
В STAIR после обновления сервера обновите список tools и явно включите новые
инструменты в настройках агента — автоматического подключения новых tools нет.
