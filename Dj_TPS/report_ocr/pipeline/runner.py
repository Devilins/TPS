"""Обходит ROI-карту шаблона и прогоняет OCR по каждой числовой ячейке.
Не знает ничего про Django/БД — просто возвращает список результатов,
таск сам решает, что с ними делать (сохранить, сравнить с CRM и т.д.)."""
from dataclasses import dataclass, field

import cv2

from .digits import ocr_cell


@dataclass
class CellResult:
    section: str
    field_name: str
    sub_field: str
    extracted_value: str
    confidence: float | None
    crop_png: bytes = field(repr=False)


def _encode_crop(warped_img, box, pad=6) -> bytes:
    x0, y0 = max(0, box["x0"] + pad), max(0, box["y0"] + pad)
    x1, y1 = box["x1"] - pad, box["y1"] - pad
    crop = warped_img[y0:y1, x0:x1]
    ok, buf = cv2.imencode(".png", crop)
    return buf.tobytes() if ok else b""


def _process_box(warped_img, section, field_name, sub_field, box) -> CellResult:
    value, conf = ocr_cell(warped_img, box)
    return CellResult(section, field_name, sub_field, value, conf, _encode_crop(warped_img, box))


def run_roi_map(warped_img, roi: dict) -> list[CellResult]:
    results: list[CellResult] = []

    if "Дата Отчёта" in roi:
        results.append(_process_box(warped_img, "Дата Отчёта", "Дата Отчёта", "", roi["Дата Отчёта"]))

    for meta_name in ("Администратор", "Фотограф"):
        if meta_name in roi:
            results.append(_process_box(warped_img, "Мета", meta_name, "", roi[meta_name]))

    for section in ("Техника", "Расходники"):
        for name, cells in roi.get(section, {}).items():
            results.append(_process_box(warped_img, section, name, "начало_дня", cells["начало_дня"]))
            results.append(_process_box(warped_img, section, name, "конец_дня", cells["конец_дня"]))

    for name, box in roi.get("Касса", {}).items():
        results.append(_process_box(warped_img, "Касса", name, "", box))

    # таблицы со свободными строками ("Вычеты ЗП", "Личные кассы") — берём только
    # числовые столбцы (сумма/касса), имена сотрудников (рукописные, не цифры) не трогаем
    for section, numeric_cols in (
        ("Вычеты ЗП наличными", ["Сумма"]),
        ("Личные кассы фотографов", ["Касса"]),
    ):
        block = roi.get(section)
        if not block:
            continue
        for i, row in enumerate(block.get("строки", [])):
            for col in numeric_cols:
                if col in row:
                    results.append(
                        _process_box(warped_img, section, f"{col} (строка {i+1})", "", row[col])
                    )

    return results
