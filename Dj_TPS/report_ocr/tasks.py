import json
import logging
import os

import cv2
import numpy as np
from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone

from .integration import field_key, get_personal_cashbox_total, get_system_report_data
from .models import FieldResult, ReportUpload
from .pipeline.markers import MarkersNotFound, detect_and_warp
from .pipeline.runner import run_roi_map

logger = logging.getLogger(__name__)

_ROI_DIR = os.path.join(os.path.dirname(__file__), "pipeline", "roi_maps")
_ROI_CACHE: dict[str, dict] = {}
_PERSONAL_CASHBOX_SECTION = "Личные кассы фотографов"


def _build_personal_cashbox_total(upload, cell_results):
    """Построчно «Личные кассы фотографов» не сверяем (имена на бланке не распознаются) —
    вместо этого одна синтетическая строка ИТОГО: сумма распознанных касс по всем строкам
    таблицы vs integration.get_personal_cashbox_total()."""
    rows = [r for r in cell_results if r.section == _PERSONAL_CASHBOX_SECTION]
    if not rows:
        return None

    extracted_total = 0
    for r in rows:
        try:
            extracted_total += int(r.extracted_value)
        except (TypeError, ValueError):
            pass

    try:
        system_total = get_personal_cashbox_total(upload.location, upload.report_date)
    except NotImplementedError:
        return None

    extracted_value = str(extracted_total)
    system_value = str(system_total)
    confidences = [r.confidence for r in rows if r.confidence is not None]
    return FieldResult(
        upload=upload,
        section=_PERSONAL_CASHBOX_SECTION,
        field_name="ИТОГО",
        sub_field="",
        extracted_value=extracted_value,
        confidence=min(confidences) if confidences else None,
        system_value=system_value,
        is_match=(extracted_value == system_value),
    )


def _load_roi_map(template_key: str) -> dict:
    if template_key not in _ROI_CACHE:
        path = os.path.join(_ROI_DIR, f"{template_key}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Нет ROI-карты для шаблона {template_key!r} (ожидался файл {path})"
            )
        with open(path, encoding="utf-8") as f:
            _ROI_CACHE[template_key] = json.load(f)
    return _ROI_CACHE[template_key]


@shared_task(bind=True, max_retries=0)
def process_report(self, upload_id: int):
    """Полный цикл: фото -> выравнивание по меткам -> OCR по ROI -> сверка с CRM.
    concurrency=1 на воркере — процесс тяжёлый, не рассчитан на параллельные задачи
    на 1 ядре (см. обсуждение ресурсов сервера)."""
    upload = ReportUpload.objects.select_related("location").get(id=upload_id)
    upload.status = ReportUpload.STATUS_PROCESSING
    upload.save(update_fields=["status"])

    try:
        template_key = upload.get_template_key()
        roi = _load_roi_map(template_key)

        img = cv2.imread(upload.photo.path)
        if img is None:
            raise ValueError("Не удалось прочитать файл фото")

        # уменьшаем перед обработкой — экономит память и время на слабом сервере
        h, w = img.shape[:2]
        if max(h, w) > 1600:
            scale = 1600 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))

        warped = detect_and_warp(img)
        cell_results = run_roi_map(warped, roi)

        try:
            system_data = get_system_report_data(upload.location, upload.report_date)
        except NotImplementedError:
            logger.warning("get_system_report_data не подключён — сохраняю без сверки")
            system_data = {}

        upload.fields.all().delete()  # на случай повторной обработки того же upload
        field_objs = []
        for r in cell_results:
            system_value = system_data.get(field_key(r.field_name, r.sub_field), "")
            is_match = (r.extracted_value == system_value) if system_value else None
            fr = FieldResult(
                upload=upload,
                section=r.section,
                field_name=r.field_name,
                sub_field=r.sub_field,
                extracted_value=r.extracted_value,
                confidence=r.confidence,
                system_value=system_value,
                is_match=is_match,
            )
            if r.crop_png:
                fname = f"{r.section}_{r.field_name}_{r.sub_field}.png".replace(" ", "_").replace("/", "-")
                fr.crop_image.save(fname, ContentFile(r.crop_png), save=False)
            field_objs.append(fr)

        total_row = _build_personal_cashbox_total(upload, cell_results)
        if total_row is not None:
            field_objs.append(total_row)

        FieldResult.objects.bulk_create(field_objs)

        upload.status = ReportUpload.STATUS_DONE

    except MarkersNotFound as e:
        upload.status = ReportUpload.STATUS_ERROR
        upload.error_message = f"Не нашёл угловые метки на фото: {e}. Переснимите ровнее/при лучшем свете."
    except Exception as e:  # noqa: BLE001 — таск обязан не падать молча, статус должен дойти до пользователя
        logger.exception("Ошибка обработки отчёта %s", upload_id)
        upload.status = ReportUpload.STATUS_ERROR
        upload.error_message = str(e)
    finally:
        upload.processed_at = timezone.now()
        upload.save()
