# TPS — контекст проекта для Claude Code

> Снимок на 2026-10-20 (ветка `auto_rep`, HEAD `9139443`). Прочитай целиком перед любой доработкой.
> Если доработка меняет модели, правила расчёта, права или инфраструктуру — в конце работы обнови
> соответствующий раздел этого файла. Подробности по OCR-модулю — в `Dj_TPS/report_ocr_app/CLAUDE.md`,
> по планированию выездных (`schauto`) — в `Dj_TPS/schauto/CLAUDE.md`.

## 1. Что это и для кого

**TPS (Take Photo ERP System)** — внутренняя ERP сети фотостудий в детских развлекательных центрах.
Бренды/точки: Laserland, Joki Joya (в коде `JJ`), Бигвол. Прод: `https://takephoto-erp.ru`.

Что делает: график смен и выходов/отпусков, продажи (касса), наличные на точке, расходники и фототехника,
расчёт зарплат (по дням и по неделям), выдача ЗП наличными, финотчётность, сверка отчётов точек
(в т.ч. по фото бумажных бланков — OCR), Telegram-бот.

Владелец проекта — Александр Кривов (SRE/DevOps, опытный инженер): объяснения на уровне продвинутого
разработчика, базовое Django/Docker/Celery не разжёвывать. Общение, UI, комментарии в коде, тексты
ошибок и сообщения `ImplEvents` — **на русском**.

## 2. Раскладка репозитория

```
TPS/                        git root (origin: github.com/Devilins/TPS) — здесь этот файл
├── Dj_TPS/                 корень Django-проекта: manage.py, Dockerfile, docker-compose.yml,
│   │                       pyproject.toml (РЕАЛЬНЫЙ poetry-проект), .env (gitignored)
│   ├── Dj_TPS/             пакет конфигурации: settings.py, urls.py, celery.py
│   ├── tph_system/         ОСНОВНОЕ приложение: models.py, views.py (~2700 строк), funcs.py (расчёты),
│   │                       forms.py, filters.py, tables.py, signals.py, middleware.py,
│   │                       tph_urls.py, management/commands/, templates/, static/
│   ├── users/              логин/смена пароля/lockout (django-axes); своих моделей нет
│   ├── report_ocr/         сверка бумажных отчётов по фото (Celery + OpenCV + TFLite)
│   ├── report_ocr_app/     ТОЛЬКО документация по report_ocr (CLAUDE.md, README, TESTING_STATUS, TEST_REP_OCR_MAC)
│   ├── schauto/            полуавтоматическое планирование выездных фотографов (центры, маршруты, импорт заказов из
│   │                       Google-таблицы, распределение); контекст и решения — schauto/CLAUDE.md
│   ├── fastbot.py          Telegram-бот (aiogram) + FastAPI; отдельный процесс, в docker-compose его НЕТ
│   ├── docker/nginx/       nginx.conf (TLS, rate-limit 5 r/s)
│   └── *.sh, cronjobs      скрипты и cron прод-сервера
├── main.py, pyproject.toml, poetry.lock   в корне — артефакты PyCharm, не используются (untracked)
```

`manage.py` и все команды запускать из `TPS/Dj_TPS`. `tph_system/migrations/OLD/` — архив, не использовать.

## 3. Стек

Python 3.12 (Docker; локально .venv на 3.13), Django 5.1, DRF + simplejwt, django-filter, django-tables2
(+tablib/openpyxl — экспорт в Excel), django-axes (10 неудач → блок по username на ~5 мин), debug_toolbar,
Postgres 16, Redis 7 + Celery (воркер `-c 1`), OpenCV headless + `ai-edge-litert` (TFLite) для OCR,
aiogram + FastAPI для бота. Фронт: серверные шаблоны, Bootstrap 5.3 (CDN), свой
`tph_system/static/tph_system/css/styles.css`, Fengyuan Chen datepicker, FontAwesome.
`LANGUAGE_CODE=ru`, `TIME_ZONE=Europe/Moscow`, `USE_TZ=True`. **Автотестов нет** (`tests.py` пустые), кроме тестов `schauto` (`tests.py`, `test_*.py`)
(у dev-роли Postgres нет CREATEDB — как их гонять, см. `schauto/CLAUDE.md` §7).

## 4. Модель данных (`tph_system/models.py`)

Почти у каждой модели есть `user_edited` (FK→User, PROTECT) и `date_upd`.

| Модель | Суть |
|---|---|
| `Staff` | сотрудник; `st_username`→`auth.User` — связка «пользователь ↔ сотрудник» (на ней держится «видеть только своё»); `dism_status` Работает/Уволен; для `schauto`: `staff_type` (Штат/Выездной/Ретушер), `skill_score` 1–10, `retouches_own`, `max_orders_per_day` |
| `Store` | точка; `short_name` — «функциональное» имя, **не менять** (от него зависят имена параметров Settings и признак JJ); статус Действующая/Закрытая/Техническая |
| `Schedule` | смена: staff+store+date, `position` (роль), `work_time`; unique(staff,date,store) — в день можно на нескольких точках |
| `WorkVacSchedule` | статус дня сотрудника: Работает/Отпуск/Отгул/Больничный, `time_availiable` (опечатка в имени — не «чинить»); unique(staff,date) |
| `Sales` | продажа: store, date, `staff` (админ), `photographer`, `sale_type`, `photo_count` (кол-во фото ИЛИ часов), `payment_type`, `sum`, email/телефон клиента |
| `CashStore` | наличные на точке за день: `cash_mrn` (утро, вводится) и `cash_evn` (вечер, пересчитывается); unique(store,date) |
| `CashWithdrawn` | выдача ЗП наличными; `week_beg_rec` — понедельник недели, за которую выдали |
| `Salary` / `SalaryWeekly` | ЗП за день (c `cnt_logs` — логом расчёта) / за неделю (`to_pay` = ЗП − выдано) |
| `FinStatsMonth` / `FinStatsStaff` | финансы по компании / по сотрудникам за месяц |
| `CheckReports` | статус проверки отчёта точки за день (ОК/Были ошибки/Не проверено); unique(store,date); право `export_joki_week` |
| `ConsumablesStore`, `Tech` | расходники и фототехника на точке (`cons_short` — функциональное имя, не менять) |
| `Settings` | пары param/value — **все ставки и пороги расчёта ЗП** и пороги остатков |
| `ImplEvents` | журнал системных событий и ошибок (см. §7) |
| `RefsAndTips`, `TelegramUser` | подсказки на главной; пользователи бота (+JWT-токены). `ConsumablesSales` — не используется |
| `schauto.Venue` / `Route` | центр, куда ездят выездные (отдельно от `Store`; сложность 1–10; необязательная связь со `Store`) и направленные маршруты между центрами на общественном транспорте (все варианты) |
| `schauto.PhotoOrder` / `StaffAlias` / `VenueAlias` | заказ из строки Google-таблицы (без ПДн клиента; таблицы две — Laserland и Joki Joya), имена из ячеек «Фотограф»/«Ретушер» → `Staff`, фрагменты адресов выездов → `Venue`. Остальное — по этапам в `schauto/CLAUDE.md` |
| `schauto.PlanRun` / `Assignment` | расчёт распределения выездных за период (черновик → применён) и его назначения по частям заказов с объяснениями, правками и статусами записи в таблицу и в `Schedule`; при применении пишет в Google-таблицы и в `Schedule` (только после проверок) |
| `report_ocr.ReportUpload` / `FieldResult` | загрузка фото бланка (unique(location, report_date)) и результат по каждому полю |

## 5. Бизнес-правила (самое важное, легко сломать)

**Роли** (`Schedule.position`): Администратор, Фотограф, Универсальный фотограф, Выездной фотограф,
Видеограф; только для JJ — Супер универсал (JJ), Админ-ретушер (JJ), Ретушер (JJ); по умолчанию
«Роль не указана» — сотрудник сам выбирает роль в начале смены (`position_select`).

**Расчёт ЗП** — `tph_system/funcs.py::sal_calc(time_start, time_end, one_staff_calc)`:
- В продажах `staff` = администратор, `photographer` = фотограф. Для смены сотрудника касса делится на
  `sales_ph` (он фотограф, не админ), `sales_adm` (он админ, не фотограф), `sales_univ` (и то и другое).
  Заказные типы (`Заказной фотосет`, `Заказ выездной`, `Заказная видеосъемка`) в кассу для процентов не входят —
  платятся почасово (`photo_count` = часы) по Settings.
- Порядок веток: заказы → универсал+админ / универсал / админ → фотограф → «касса 0» (минималка по роли) →
  доплата админу за сопровождение заказов → **выездной (обнуляет и пересчитывает всё)** → **блок JJ
  (тоже обнуляет), если `'JJ' in store.short_name`**, роль не выездной и касса не нулевая.
  При правке правил смотреть ВСЕ ветки, иначе поздняя ветка перезапишет результат.
- **JJ: самостоятельные продажи основных ролей** (константа `JJ_SELF_SUPUNIV_ROLES`: Фотограф, Универсальный фотограф,
  Ретушер (JJ), Админ-ретушер (JJ); выездные не входят). Продажи, где сотрудник и админ, и фотограф (`sales_univ`, без
  заказных), считаются отдельным блоком после цепочки JJ: `ЗП = max(К_осн × % роли + К_сам × JJ_stnd_perc_supuniv,
  минималка роли)`; порога и минималки супер универсала тут нет; `cash_box` = К_осн + К_сам. Без самостоятельных
  продаж расчёт роли прежний (с порогом `JJ_min_border_*`). В цепочке `elif sales_univ` для этих ролей отключён.
- Выходные: `weekday() in (5, 6)`. Результат — `Salary.update_or_create(store, staff, date)` + `cnt_logs`
  (строка вида `A (x * y) + …`, хвостовой `+` срезается) + запись в `ImplEvents`.
- Ставки/пороги берутся только через `param_gets(name)` из `Settings` (значение → `int`). Нет параметра или
  дубль → `ImplEvents 'Param_Gets_Error'` и значение 0 (расчёт не падает, а молча считает с нулём).
- Параметры, привязанные к точке: `{short_name}_order_ph_wknd|budn`, `{short_name}_admin_incr_perc_pay_wknd`,
  `{short_name}_phot_few_incr_perc_pay_wknd|budn`. **Новая точка ⇒ завести эти параметры в Settings.**
  Остальные группы: `admin_*`, `phot_*`, `univ_*`, `order_ph_out*`, `video_order_ph_out`, `JJ_*`, `cons_*`, `stcst_*`.
- Недельный расчёт `sal_weekly_update`: сумма `Salary` за пн–вс минус `CashWithdrawn` с
  `week_beg_rec`=понедельник → `SalaryWeekly`. Сохранение `CashWithdrawn` (сигнал `post_save`) пересчитывает неделю.
  Выдачи без `week_beg_rec` порождают `ImplEvents 'Week_Beg_Rec_Empty'`.
- `fin_stats_calc` / `fin_stats_staff_calc` — помесячно; `reports_list_update` — создаёт `CheckReports`
  на каждую точку, у которой в этот день есть график.

**Наличные.** `cash_mrn` вводится утром (`m_cash_add`, `cash_evn = cash_mrn`). Дальше `cash_evn` меняется
через `F()` при создании/изменении/удалении продажи с оплатой «Наличные» и при создании/изменении/удалении
`CashWithdrawn`. Нет записи `CashStore` за день → `ImplEvents` «Бизнес ошибка». Главная и «Сверка отчетов»
сверяют `cash_mrn` сегодня с `cash_evn` предыдущей записи (для JJ сверка всегда «ОК»).

**Расходники.** Продажа магнитов (`Вин. магн.`/`Ср. магн.`/`Бол. магн.`) уменьшает `ConsumablesStore.count`
с `cons_short == sale_type` (create/update/delete). Остальные типы расходники не трогают.
Пороги «заканчивается» на главной — Settings `cons_others`, `cons_mgn`, `cons_check_lists`, `cons_cards`, `cons_paints`.

**Валидации `SalesForm`** (не ломать): дата не в будущем; `cl_email` и `cl_phone` (11 цифр) фактически
обязательны (`clean_*` падает на пустом); `sum`>0, `photo_count`>0; для «Предоплаченный заказ» ≤ 8 ч;
«Заказной фотосет»/«Заказ выездной» — только с оплатой «Предоплаченный заказ»; и админ, и фотограф должны быть
в `Schedule` этой точки на эту дату; магнитов не больше остатка.

## 6. Права доступа

- Функции: `@login_required` + `@permission_required(perm='app.codename', raise_exception=True)`.
  CBV: `PermissionRequiredMixin, LoginRequiredMixin` + `permission_required` + `permission_denied_message`.
  Пункты меню в `base.html` скрываются через `perms.tph_system.*`.
- Роли пользователей — это группы/права, настроенные в админке (в коде групп нет).
- **Кастомные права не объявлены в `Meta.permissions`** (кроме двух ниже) — это строки `auth_permission` в БД,
  заведённые вручную: `view_main_page`, `main_page_view_cards`, `main_page_edit_tips`, `user_sales_view_all`,
  `consumables_view_all_stores`, `tech_view_all_stores`, `view_all_salary`, `view_all_staff_schedule`,
  `view_all_cashwithdrawn`, `reports_view`, `reports_boss_view`, `calculate_salary`, `calculate_finstatsmonth`.
  Объявлены в коде (с миграцией): `tph_system.export_joki_week`, `report_ocr.view_all_report_uploads`.
  `schauto`: стандартные права моделей (`schauto.view_venue` открывает раздел и пункт меню «Выездные», `add_/change_/delete_` `venue`/`route`, `view_photoorder`)
  и объявленные в коде `schauto.import_orders` (загрузка заказов из таблиц + сопоставления) и `schauto.run_planning` (расчёт распределения; просмотр расчётов — `schauto.view_planrun`, стандартное); остальные права добавятся с этапами планирования.
  Новое кастомное право — предпочтительно через `Meta.permissions` + миграция, и напомнить выдать его группе.
- Паттерн «без права видит только своё»: `user_sales_view_all`, `view_all_salary`, `view_all_staff_schedule` и т.п.
  Без них — только своя точка/сегодня/свои записи (через `Staff.st_username`).

## 7. Конвенции кода (писать так же)

- Списочные страницы — функции-вьюхи (фильтр + форма создания на той же странице + пагинация), update/delete —
  CBV. URL — в `tph_urls.py` (`from .views import *`), имена маршрутов snake_case.
- Паттерн списка: если нет GET-параметров — `redirect` на дефолтный фильтр; `current_filter_params =
  request.GET.urlencode()` прокидывается в шаблоны, ссылки и `get_success_url()`, чтобы возвращаться с теми же
  фильтрами; `django_filters.FilterSet` в `filters.py`; `Paginator(…, 25)`; экспорт csv/xlsx через
  `django_tables2` + `tables.py` (`export_to_excel_template`, `standard_export`, `export_joki_week`).
- Мультивыбор в фильтрах: `NonEmptyMultipleChoiceFilter` (filters.py; значения через ИЛИ, пустые игнорируются —
  старые ссылки `?x=` не ломаются) + `CheckboxSelectMultiple`, в шаблоне — выпадающий список с чекбоксами через
  `{% include 'tph_system/includes/filter_multiselect.html' with field=… label=… %}`. Сейчас так сделаны «Что продали»
  и «Тип оплаты» в продажах; для других фильтров переиспользовать.
- Шаблоны: `{% extends 'tph_system/base.html' %}`, Bootstrap 5, карточки `.card.shadow`, таблицы
  `table-sm table-hover table-bordered align-middle` со sticky-шапкой, даты — `FengyuanChenDatePickerInput`
  (формат `dd.mm.yyyy`, `dt_format`). Новый раздел ⇒ пункт меню в `base.html` под `perms`.
- **Любая бизнес-операция пишет `ImplEvents`** (`event_type`, `event_message`, `status` ∈ Успешно / Бизнес ошибка /
  Системная ошибка / Удаление записи, `solved` Да/Нет). Нерешённые ошибки показываются счётчиками на главной и на
  странице «Ошибки в работе системы». Новые операции делать так же.
- Сигналы (`signals.py`): `pre_save` любой модели с `user_edited` ставит текущего пользователя (thread-local через
  `CurrentUserMiddleware`); `pre_delete` пишет удаляемый объект в `ImplEvents` JSON-ом; `post_save(CashWithdrawn)`
  пересчитывает неделю.
- Изменения продаж/наличных/расходников — внутри `@atomic` (`form_valid` Sales Create/Update/Delete).
- Коммиты на русском, префикс `PROD - …` (уедет в прод) или `TEST - …`. Миграции коммитить вместе с моделями.
  Коммитить/пушить только по просьбе владельца.

## 8. Инфраструктура и эксплуатация (прод)

- Сервер Linux, проект в `/home/devilins/TPS/Dj_TPS`. `docker-compose.yml`: `tps_postgres` (Postgres 16.4, данные
  `~/.pg/pg_data/tps`, порт **7198 наружу**), `tps` (команда: `makemigrations && migrate && collectstatic &&
  runserver 0.0.0.0:8000`), `tps_celery_worker` (`-c 1 --prefetch-multiplier=1`), `tps_redis`, `tps_nginx`
  (80/443, `/static` и `/media` из именованных томов), `tps_certbot` (renew каждые 12 ч).
  Именованные тома `static`/`media` получают префикс compose-проекта (`dj_tps_*`).
- Cron на хосте (актуальный — нижний блок в `cronjobs`; верхний формат `/etc/cron.d` устарел):
  22:00 `tps_backup.sh` (pg_dump → gzip в `Dj_TPS/pg_backups`); 20:50 `job_sal_calc.sh` (`run_sal_calc` за сегодня);
  20:55 `job_fin_stats.sh` (`run_fin_stats` вчера–сегодня); чт 20:00 и вс 20:45 `job_sal_weekly.sh`
  (`run_sal_weekly` от −9 до −7 дней). Скрипты вызывают `docker compose exec tps … manage.py run_*`.
- Management commands: `run_sal_calc`, `run_sal_weekly`, `run_fin_stats <YYYY-MM-DD> <YYYY-MM-DD>`, `run_qr_gen_tech`.
- **Деплой ручной**, прод-сервер не связан с git-репозиторием (со слов владельца); `rebuild_tps.sh` —
  stop/удаление контейнера и образа `dj_tps-tps`/up. Владелец решил пока ничего не менять в деплое —
  **не предлагать CI/CD и перестройку без запроса.**
- Из-за `makemigrations` в команде контейнера миграции, которых нет в git, генерируются на сервере —
  поэтому все миграции обязательно коммитить.
- `.env` (gitignored): `SECRET_KEY`, `DEBUG`, `POSTGRES_*`, `ALLOWED_HOSTS` (через пробел), `DJANGO_SETTINGS_MODULE`,
  `NGINX_EXTERNAL_PORT`; опционально `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` (по умолчанию `redis://redis:6379/0`),
  `SCHAUTO_SHEET_ID_LL`/`SCHAUTO_SHEET_ID_JJ` (ID Google-таблиц заказов для `schauto`; прод-ID в `.env` закомментированы), `SCHAUTO_GOOGLE_CREDENTIALS_FILE` (путь к JSON-ключу сервисного аккаунта: чтение заказов из таблиц и запись исполнителей; без ключа загрузка читает таблицы по публичной ссылке, медленнее; ключ в репозиторий не класть);
  для бота `TELEGRAM_BOT_TOKEN`, `DJANGO_API_URL`. Значения секретов не выводить и не коммитить.
- `init-letsencrypt.sh` **стирает `docker/certbot/conf/*`** — не запускать на проде с живыми сертификатами.

## 9. OCR-модуль `report_ocr` (кратко)

Страницы `/reports/ocr/…`. Поток: загрузка фото → Celery `process_report` (concurrency 1: сервер 1 ядро/1 ГБ) →
`pipeline/markers.detect_and_warp` (4 угловые метки) → `pipeline/runner.run_roi_map` (ROI-карты
`roi_maps/laserland.json`, `joki_joya.json`; шаблон по `'JJ' in short_name`) → `pipeline/digits` (своя CNN на MNIST,
TFLite) → `integration.get_system_report_data` (сверка с `Sales`/`CashStore`/`Tech`/`ConsumablesStore`) →
`FieldResult` (+ `crop_image`, `confirmed_value` как будущий обучающий датасет). Без права
`view_all_report_uploads` — только сегодняшние точки своей смены и фиксированная сегодняшняя дата.
Архитектурные решения не менять без запроса — причины в `report_ocr_app/CLAUDE.md`. Локально на Mac TFLite-рантайм
не ставится → воркер в Docker (`report_ocr_app/TEST_REP_OCR_MAC.md`).

## 10. Известные особенности и долг (проверено по коду; без запроса не чинить, но учитывать)

1. `funcs.py:36` — `Settings` читаются **один раз при импорте модуля** в список `s`: правки в таблице Settings не
   видны уже запущенному процессу (web, celery) до перезапуска; cron-команды (новый процесс) видят актуальные.
   Плюс запрос к БД на импорте — падает на пустой БД до первой `migrate`.
2. `settings.py`: `DEBUG = True` захардкожен (`DEBUG` из `.env` игнорируется); debug_toolbar и раздача static/media
   подключены безусловно; `LOGGING.error_file.filename` — абсолютный путь машины разработчика (в git — Windows
   `C:/Users/alexi/…`, локально сейчас Mac), в контейнере нужен `/app/django_errors.log`; файловый/почтовый логгер
   ошибок работает только при `DEBUG=False`. Локальную правку пути в коммит не брать «как есть».
3. На проде работает dev-сервер `runserver`.
4. `tph_system/tasks.py` (django-background-tasks) — legacy, не используется (расчёты идут cron + management
   commands); вызывает `sal_calc`/`sal_weekly_update` с 2 аргументами при 3 обязательных, а на импорте
   планирует задачи. Не опираться.
5. **API без прав (по коду, запросом не проверял):** `TelegramUserViewSet` и `SingleUserViewSet` не задают
   `permission_classes`, а в `REST_FRAMEWORK` нет `DEFAULT_PERMISSION_CLASSES` ⇒ DRF-дефолт `AllowAny`.
   `/api/tuser/` отдаёт `access_token`/`refresh_token`, `/api/get_user/<username>/` — данные пользователя. Бот
   ходит в `tuser/<id>/` без токена, так что закрытие потребует правки `fastbot.py`.
6. `Staff.objects.get(st_username=request.user)` без обработки `DoesNotExist` в `sales`, `salary`,
   `salary_weekly` и др. — 500 у пользователя без привязанного `Staff` (например, суперпользователь).
7. `TelegramUser.__str__` возвращает несуществующий `self.name`.
8. `sal_calc` — одна огромная функция с копипастой по ролям; осторожно с правками (см. §5).
9. Опечатки в именах полей (`time_availiable`, `ConStore…`) — не переименовывать без миграции и необходимости.
10. В git закоммичены: два реальных фото `media/report_ocr/uploads/2026/09/23/*.jpg`, `report_ocr_app.zip`, `.idea/`.
11. Postgres торчит наружу на 7198; nginx отдаёт `/media/` целиком.

## 11. Текущее состояние работы (на 2026-10-20)

- Ветка `auto_rep` (есть `origin/auto_rep`), на 2 коммита впереди `master` (`master`=`ed1bb64`; впереди `1db019e`, `9139443`).
- **Не закоммичено:** доработки `report_ocr` (forms/models/views/templates, смена URL `/report-ocr/` → `/reports/ocr/`
  в `Dj_TPS/urls.py`), документация `report_ocr_app/*`, правка `fin_stats/reports.html`, локальная правка пути лога
  в `settings.py`, `.idea/*`.
- **Миграции есть только на диске, не в git:** `tph_system/0007_alter_schedule_position.py`,
  `tph_system/0008_checkreports_export_joki_week.py`, `report_ocr/0002_reportupload_view_all_permission.py`.
  Модель с правом `export_joki_week` уже закоммичена в `9139443` без миграции — при коммите не забыть `git add`.
- **`schauto` (этапы 0–3) написан, не закоммичен; применён только к локальной dev-БД:** новое приложение `Dj_TPS/schauto/`, `INSTALLED_APPS` и
  `SCHAUTO_SHEET_IDS` в `settings.py`, `path("schauto/")` в `Dj_TPS/urls.py`, поля `Staff` (+форма, фильтр, `staff.html`),
  пункт меню «Выездные» в `base.html`; миграции `tph_system/0009_staff_planning_fields.py`, `schauto/0001_initial.py`,
  `schauto/0002_venue_brand_tab_unique.py`, `schauto/0003_orders_and_aliases.py`, `schauto/0004_slots_and_active_store.py`, `schauto/0005_venue_address.py`, `schauto/0006_plan_runs_and_assignments.py`, `schauto/0007_plan_apply.py`, `schauto/0008_plan_rollback.py`, `schauto/0009_retoucher_cell.py`, `schauto/0010_plan_confirmed.py`, `schauto/0011_photo_order_team.py`, `schauto/0012_assignment_alternatives_label.py` (все обязательно `git add`; в `pyproject.toml`/`poetry.lock` добавлен `gspread`). Права: `schauto.import_orders` и `schauto.run_planning` объявлены в коде (группам выдать `view_planrun` и `run_planning`). Этапы 3–5 — экран «Распределить» `/schauto/plan/`: расчёт, правка исполнителей, проверка, применение (запись в Google-таблицы и в `Schedule`) и откат применения. 
  В `Dj_TPS/.env` (gitignored): рабочие ID **копий** двух Google-таблиц заказов, прод-ID — закомментированы (боевые таблицы для разработки не использовать). Дальше — по этапам в `schauto/CLAUDE.md` §8.
- Ссылка на OCR в меню `base.html` пока не добавлена (владелец добавит сам).
- Открытые вопросы по OCR (тюнинг порога меток `_RELAXED_MIN_STD`, точность CNN, дообучение) — в конце
  `report_ocr_app/TESTING_STATUS.md`.

## 12. Локальный запуск и проверка

Из `TPS/Dj_TPS`: `poetry run python manage.py runserver` (в PyCharm — конфигурация `runserver`; `.env`
подхватывается `load_dotenv()`). Нужен локальный Postgres с копией прод-БД. Для OCR — Redis и Celery-воркер:
`celery -A Dj_TPS worker -c 1 --prefetch-multiplier=1 --loglevel=info` (Windows: `-P solo`; Mac: воркер в Docker).
Перед коммитом: `manage.py check` и `manage.py makemigrations --check`. Тестов нет — проверка вручную.
