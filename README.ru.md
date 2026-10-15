# Fedaraka: переносимая установка Power BI MCP

Самостоятельный пакет: Microsoft Modeling MCP, наши Report Server MCP, Desktop MCP,
Authoring MCP, Supergateway и Caddy. Главный запуск — `Start-PowerBI.ps1` в корне.

## 1. Подготовьте Windows

- Windows x64, стабильный **CPython x64 3.10 или новее**, Node.js LTS с npm.
- Первая установка требует доступа к Microsoft Downloads, npm, PyPI, PowerShell Gallery
  и официальному дистрибутиву Caddy. Зависимости зафиксированы lock-файлами.
- С машины должен открываться `http://report-server.example.com/Reports`. Подготовьте отдельную
  Windows-учётную запись Report Server с правами чтения и публикации целевого отчёта.
- Скрипт устанавливает Desktop **optimized for Report Server**, September 2026,
  **2.158.1177.0**, проверенный с сервером **1.27.9770.30560**. Для другой версии сервера
  сначала согласуйте Desktop; установщик проверяет точную версию, подпись и SHA256.
- Для управления Desktop нужен вошедший пользователь и разблокированный сеанс.
  Это интерактивная установка, а не headless Windows Service.

## 2. Скопируйте пакет

Скопируйте исходный код и добавьте собственный PBIX так, чтобы расположение выглядело следующим образом:

```text
C:\PowerBI-MCP\Start-PowerBI.ps1
C:\PowerBI-MCP\deployment.example.json
C:\PowerBI-MCP\scripts\
C:\PowerBI-MCP\services\powerbi-reportserver-mcp\
C:\PowerBI-MCP\reports\Fedaraka Server Automated.pbix
```

Не переносите `.venv`, `node_modules`, `runtime`, `generated`, локальные конфиги
и XML с учётными данными: они создаются заново. PBIX с данными не включён в публичный репозиторий. Добавьте свой совместимый отчёт
в reports/ и настройте report_file перед установкой.
Для переноса более свежих изменений сначала сохраните и проверьте рабочий PBIX,
затем поместите его в `reports`: пакет не экспортирует открытый Desktop автоматически.

## 3. Укажите сервер и отчёт

```powershell
Copy-Item C:\PowerBI-MCP\deployment.example.json C:\PowerBI-MCP\deployment.local.json
notepad C:\PowerBI-MCP\deployment.local.json
```

| Поле | Значение / назначение |
|---|---|
| `portal` | `http://report-server.example.com/Reports` |
| `report_id` | `11111111-1111-4111-8111-111111111111`, пример GUID; замените реальным GUID своего отчёта |
| `report_alias` | `staging`, имя для публикации/backup |
| `project_alias` | `rs-automation`, имя для Desktop |
| `report_file` | Относительный путь к PBIX внутри `reports/` |
| `frontend_port` | `8012`; внутренние порты — `8013–8016` |
| `allowed_addresses` | По умолчанию только `127.0.0.1` и `::1` |
| `enable_publication` | `true`: публикация с отдельным одноразовым одобрением |

Обязательно укажите реальный адрес сервера, GUID отчёта и соответствующий PBIX вместо примеров. Новый отчёт
автоматически не создаётся. Рабочая копия появляется в
`services\powerbi-reportserver-mcp\runtime\release`; повторный Setup её не перезаписывает.

## 4. Первая установка — одна команда

Откройте PowerShell **от имени администратора под тем же пользователем**, который
будет работать с Desktop. Сохраните работу и закройте Desktop, если нужна его установка.
После принятия лицензий Microsoft выполните:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\PowerBI-MCP\Start-PowerBI.ps1 -Setup -AcceptMicrosoftEula
```

Скрипт создаёт Python-окружение, устанавливает зависимости и Desktop RS, настраивает
четыре HTTP MCP, firewall и задачу Планировщика. Затем проверяет MCP, вход в Report Server
и открытие PBIX. В локальном Windows-диалоге введите учётные данные Report Server.
Пароль защищён Windows DPAPI для этой машины и пользователя; в JSON он не записывается.

Если Python не найден, добавьте `-Python "C:\полный\путь\python.exe"`.
Точная версия3.12 больше не требуется. Приоритет выбора: явный `-Python`, существующая
`.venv`, установленные версии из `py -0p` (версия по умолчанию первой), затем Python из PATH.
Системная версия Python не изменяется; Store-алиасы в PATH пропускаются.
Установщик проверяет версию и архитектуру, установку зафиксированных зависимостей,
`pip check` и импорт модулей Windows/MCP. Новая версия Python может пройти первый этап,
но не поддерживаться отдельной зависимостью — её установка тогда остановится.
Полный сценарий Power BI проверен на3.12; обнаружение и выбор также проверены на3.15.
Чтобы заменить Python уже установленного пакета, используйте новую папку установки.
Для просмотра установленных версий выполните `py -0p`.

Если pnpm уже установлен другой версии, выполните `npm install --global pnpm@11.25.0`.
После изменения `deployment.local.json` повторите Setup. Для смены учётной записи
добавьте `-ResetCredential`. Первое выполнение без локального JSON создаёт его из примера.

## 5. Обычный запуск — одна команда

```powershell
powershell.exe -NoProfile -File C:\PowerBI-MCP\Start-PowerBI.ps1
```

Команда запускает шлюзы, проверяет четыре MCP и открывает PBIX через MCP.
Отчёт не публикуется при запуске. Задача `Fedaraka-PowerBI-MCP-<идентификатор папки>`
также запускает шлюзы при входе пользователя.

Дополнительные параметры той же команды:

- `-ValidateOnly`: проверить конфигурацию без установки.
- `-NoDesktop`: запустить и проверить MCP без открытия Desktop.
- `-Status`: состояние задачи и последняя успешная проверка; это не новая live-проверка.
- `-Stop`: остановить шлюзы этой папки; Desktop останется открытым.

## 6. Подключите клиент

Готовые секции для Codex находятся в `generated\codex-mcp.toml`. Добавьте их в
MCP-конфигурацию клиента, заменяя одноимённые секции, а не весь конфиг.
Перезапустите MCP-подключения / клиент; не оставляйте дубли прежних серверов.

| Сервер | Streamable HTTP URL |
|---|---|
| Modeling | `http://127.0.0.1:8012/fedaraka-powerbi-modeling/mcp` |
| Report Server | `http://127.0.0.1:8012/fedaraka-powerbi-reportserver/mcp` |
| Authoring | `http://127.0.0.1:8012/fedaraka-powerbi-authoring/mcp` |
| Desktop | `http://127.0.0.1:8012/fedaraka-powerbi-desktop/mcp` |

Для удалённого клиента замените `127.0.0.1` на DNS/IP Windows-машины.
Добавьте фактические исходящие IP клиента/STAIR в `allowed_addresses` и повторите Setup.
Разрешите TCP **8012 к Windows** от этих источников и доступ Windows к Report Server
(сейчас TCP80). Внутренние8013–8016 закрыты для удалённых подключений.

Режим без API-ключа ограничен IP и предназначен для доверенной тестовой сети.
Перед эксплуатацией вне неё нужны HTTPS и аутентификация на входе.
STAIR подключаем отдельным следующим этапом; сетевой маршрут до Windows потребуется проверить.

## 7. Проверьте отчёт и публикацию

Первый запрос агенту:

```text
Используй powerbi_desktop_local и powerbi_reportserver_local без STAIR.
Вызови get_dashboard_preview(project="rs-automation", page_name="Page 1") и покажи изображение.
Вызови get_report_link(report="staging") и верни ссылки на отчёт и embed.
Не изменяй, не сохраняй и не публикуй отчёт в этой проверке.
```

Дальше следуйте `services\powerbi-reportserver-mcp\TEST-PROMPT.md`:
изменение модели → проверка визуала → один `save_report` → backup сервера →
одобрение → `publish_reviewed_pbix` → скачивание и сравнение SHA256.

`save_report` — один MCP-инструмент; внутри Save вызывается через Windows UI Automation.
Изменение модели само по себе не добавляет визуал: используйте инструменты Desktop.
Authoring MCP для современных PBIP/PBIR присутствует, но проекты регистрируются отдельно;
он не является проверенным путём публикации PBIR в этот Report Server.

Публикация требует одноразового одобрения оператора для конкретного файла, его SHA256
и текущего SHA256 отчёта на сервере. Команда выдачи есть в `TEST-PROMPT.md`; выполняйте её
из `services\powerbi-reportserver-mcp`. Стартовый скрипт одобрений не выдаёт.
При неопределённом результате сохранения/публикации не повторяйте запись автоматически.

Этот «клауд» — ваш on-premises Report Server. Ссылка/iframe требуют сетевого доступа
пользователя и прав Windows; `rs:embed=true` не делает отчёт публичным.

## Диагностика и повторная сборка

- `runtime\last-startup.json`: последняя успешная проверка четырёх MCP.
- `services\powerbi-reportserver-mcp\runtime`: защищённые учётные данные, журналы,
  резервные копии, одобрения и рабочий PBIX. Не включайте в установочный архив.
- `VALIDATION.md`: выполненные проверки и их ограничения.
- `scripts\build_bundle.py`: сборка чистого ZIP по списку разрешённых файлов.

Пример конфигурации использует8012. Вспомогательные тестовые запросы с названиями мер,
страниц и ожидаемыми значениями относятся к частному проверочному отчёту: адаптируйте
их к своему PBIX. В публичный репозиторий этот отчёт не включён.
