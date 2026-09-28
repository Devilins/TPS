# report_ocr — сверка бумажных отчётов

Готовый Django-app. Пайплайн (детекция меток → выравнивание → OCR по ROI)
уже написан и проверен на реальных фото — здесь только обвязка.

## Что нужно сделать, чтобы завести у себя

1. **Скопировать папку `report_ocr/`** в корень основного проекта (рядом с
   другими вашими app).

2. **settings.py**:
   ```python
   INSTALLED_APPS = [
       ...
       "report_ocr",
   ]
   MEDIA_URL = "/media/"
   MEDIA_ROOT = BASE_DIR / "media"   # если ещё не настроено

   CELERY_WORKER_CONCURRENCY = 1
   CELERY_WORKER_PREFETCH_MULTIPLIER = 1   # см. обсуждение ресурсов сервера — 1 ядро/1Гб
   ```

3. **корневой urls.py**:
   ```python
   urlpatterns = [
       ...
       path("report-ocr/", include("report_ocr.urls")),
   ]
   if settings.DEBUG:
       urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
   ```

4. **`report_ocr/models.py`** — сейчас `ReportUpload.location` ссылается на
   `"locations.Location"` заглушкой. Замените на вашу реальную модель точки
   (`from myapp.models import Location`, `location = models.ForeignKey(Location, ...)`).
   Этой модели также нужен способ определить бренд/шаблон бланка — метод
   `get_template_key()` в `models.py` сейчас читает `location.brand`; поправьте
   под ваше реальное поле (возможно, у вас уже есть что-то вроде `location.network`).

5. **`report_ocr/integration.py`** — единственное место с бизнес-логикой,
   которое нужно дописать: `get_system_report_data(location, date)` должна
   собрать эталонные значения из ваших моделей продаж/расходников/техники.
   Формат возврата и пример — в докстринге функции.

6. **Миграции**:
   ```bash
   python manage.py makemigrations report_ocr
   python manage.py migrate
   ```

7. **Celery worker** (важно — concurrency=1, сервер слабый):
   ```bash
   celery -A your_project worker -Q report_ocr -c 1 --prefetch-multiplier=1
   ```
   (или без отдельной очереди, если у вас один воркер на всё)

## Joki Joya

ROI-карта пока только для Laserland (`pipeline/roi_maps/laserland.json`).
Как будет готова карта для Joki Joya — кладёте её туда же файлом
`joki_joya.json` (тот же формат), и `get_template_key()` должен возвращать
`"joki_joya"` для точек этого бренда — больше ничего менять не надо,
`tasks.py` подхватит новый файл сам.

## Как это работает

1. Куратор на странице `/report-ocr/upload/` выбирает точку, дату, прикладывает фото.
2. `views.upload_view` сохраняет `ReportUpload` и ставит `tasks.process_report`
   в очередь Celery — форма не ждёт обработки, сразу отдаёт страницу отчёта.
3. Таск: выравнивает фото по 4 угловым меткам (`pipeline/markers.py`),
   прогоняет каждую числовую ячейку из ROI-карты через сегментацию цифр +
   свою CNN (`pipeline/digits.py`), сравнивает с `get_system_report_data`,
   сохраняет `FieldResult` на каждое поле — включая вырезанную картинку
   ячейки (для ревью и как будущий обучающий пример).
4. На `/report-ocr/report/<id>/` куратор видит все поля, отсортированные так,
   что вверху — то, что просит внимания (`needs_review`: низкая уверенность
   OR расхождение с CRM). Подтверждает или правит значение — это пишется в
   `confirmed_value` и одновременно является идеально размеченным примером
   для будущего дообучения модели (см. `FieldResult.crop_image` +
   `confirmed_value` — тот самый механизм сбора обучающих данных из
   реального использования, а не из ручной разметки старых фото).

## Известные ограничения (уже заложено ожидаемо, не баги)

- Поля "Дата Отчёта", "Администратор", "Фотограф" распознаются той же
  цифровой моделью и для букв/дат дают мусор — это ожидаемо (см. историю
  проекта), для них просто не проставляется `system_value`/сверка;
  куратор правит вручную как текст, эти поля не блокируют обработку.
- Таблицы "Вычеты ЗП наличными" и "Личные кассы фотографов" — сегментация
  иногда цепляет шум бумаги на пустых строках; распознаётся с низкой
  уверенностью, что корректно уводит их в `needs_review`.
