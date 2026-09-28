"""
Детекция 4 угловых меток на бланке и выравнивание перспективы к каноническому
прямоугольнику. Ничего не декодирует (не ArUco-ID) — печать мелких битовых
паттернов на дешёвой печати искажается (см. историю проекта), поэтому ищем
просто тёмные квадратные силуэты по контрасту и определяем угол по положению.

Протестировано на реальных сфотографированных бланках (не только на рендерах).
"""
import itertools
import math

import cv2
import numpy as np

PX_PER_MM = 12
PAGE_W_MM, HALF_H_MM = 210, 148.5
MARKER_MM = 7
TARGET_ASPECT = PAGE_W_MM / HALF_H_MM

# центры меток в мм — как считали при вставке в docx (см. insert_markers.py)
_CENTERS_MM = {
    "TL": (3 + MARKER_MM / 2, 3 + MARKER_MM / 2),
    "TR": (200 + MARKER_MM / 2, 3 + MARKER_MM / 2),
    "BR": (200 + MARKER_MM / 2, 138.5 + MARKER_MM / 2),
    "BL": (3 + MARKER_MM / 2, 138.5 + MARKER_MM / 2),
}


class MarkersNotFound(Exception):
    """Не удалось надёжно найти все 4 угловые метки на фото."""


_STRICT_MIN_STD = 38.0
# ослабленный порог — на случай, если угол листа освещён более рассеянно/неравномерно
# и не проходит строгий порог (см. диагностику: реальное фото давало std~33 в тени
# от неровного света в одном из углов). Пробуем только если строгого прохода не хватило
# на 4 метки — чтобы не терять защиту от ложных срабатываний на тенях/текстуре стола
# в обычном случае.
_RELAXED_MIN_STD = 25.0
_DEDUPE_DIST_PX = 15  # ближе этого расстояния — считаем дублем одной и той же метки


def _find_square_blobs(gray: np.ndarray, min_std: float = _STRICT_MIN_STD) -> list[dict]:
    img_area = gray.shape[0] * gray.shape[1]
    h_img, w_img = gray.shape
    block = 51 if min(gray.shape) > 1500 else 31
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 15
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if area < 0.0003 * img_area or area > 0.015 * img_area:
            continue
        aspect = w / h if h else 0
        if not (0.6 < aspect < 1.6):
            continue
        roi = binary[y:y + h, x:x + w]
        fill = cv2.countNonZero(roi) / area
        if fill < 0.35:
            continue
        # печатная метка — резкий чёрно-белый контраст (чернила на бумаге),
        # а не плавная фактура фона/стола — обычно контраст остаётся высоким,
        # но при неравномерном освещении угла листа порог смягчается вторым проходом
        gray_roi = gray[y:y + h, x:x + w]
        if gray_roi.std() < min_std:
            continue
        cx, cy = x + w / 2, y + h / 2
        # метки всегда у одного из 4 углов листа
        near_lr = cx < 0.32 * w_img or cx > 0.68 * w_img
        near_tb = cy < 0.32 * h_img or cy > 0.68 * h_img
        if not (near_lr and near_tb):
            continue
        candidates.append({"center": (cx, cy), "area": area, "bbox": (x, y, w, h)})
    return candidates


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    """Схлопывает кандидатов, чьи центры оказались ближе _DEDUPE_DIST_PX друг к другу —
    это внешний+внутренний контур одной и той же метки (блик/неоднородность внутри
    чёрного квадрата даёт на adaptiveThreshold два отдельных контура вместо одного).
    Оставляем более крупный (обычно это внешний, настоящий контур метки)."""
    kept: list[dict] = []
    for c in sorted(candidates, key=lambda c: -c["area"]):
        cx, cy = c["center"]
        if any(math.hypot(cx - k["center"][0], cy - k["center"][1]) < _DEDUPE_DIST_PX for k in kept):
            continue
        kept.append(c)
    return kept


def _order_corners(pts):
    pts = np.array(pts, dtype="float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()
    tl_i, br_i = np.argmin(s), np.argmax(s)
    tr_i, bl_i = np.argmin(diff), np.argmax(diff)
    if len({tl_i, br_i, tr_i, bl_i}) < 4:
        return None
    return pts[tl_i], pts[tr_i], pts[br_i], pts[bl_i]


def _quad_score(tl, tr, br, bl, areas):
    top, bottom = np.linalg.norm(tr - tl), np.linalg.norm(br - bl)
    left, right = np.linalg.norm(bl - tl), np.linalg.norm(br - tr)
    if min(top, bottom, left, right) < 1e-3:
        return 1e9
    width, height = (top + bottom) / 2, (left + right) / 2
    aspect_err = abs(width / height - TARGET_ASPECT) / TARGET_ASPECT
    side_pair_err = abs(top - bottom) / width + abs(left - right) / height

    def angle(a, b, c):
        v1, v2 = a - b, c - b
        cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6)
        return abs(np.degrees(np.arccos(np.clip(cos, -1, 1))) - 90)

    angle_err = (angle(bl, tl, tr) + angle(tl, tr, br) + angle(tr, br, bl) + angle(br, bl, tl)) / 4
    areas = np.array(areas, dtype="float64")
    area_cv = areas.std() / areas.mean() if areas.mean() > 0 else 1.0
    return aspect_err * 3 + side_pair_err * 2 + angle_err / 30 + area_cv * 1.5


def _best_quad(candidates, top_n=24):
    cands = sorted(candidates, key=lambda c: -c["area"])[:top_n]
    best, best_score = None, 1e18
    for combo in itertools.combinations(cands, 4):
        ordered = _order_corners([c["center"] for c in combo])
        if ordered is None:
            continue
        tl, tr, br, bl = ordered
        score = _quad_score(tl, tr, br, bl, [c["area"] for c in combo])
        if score < best_score:
            best_score, best = score, ordered
    return best, best_score


def detect_and_warp(img: np.ndarray) -> np.ndarray:
    """Находит 4 угловые метки и возвращает выпрямленное изображение половины
    листа в каноническом масштабе (PX_PER_MM px/мм). Бросает MarkersNotFound,
    если метки не удалось надёжно определить (нужно сообщить об этом пользователю,
    а не молча выдавать мусорные координаты)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    candidates = _dedupe_candidates(_find_square_blobs(gray))
    if len(candidates) < 4:
        # строгого порога контраста не хватило — пробуем ослабленный (см. _RELAXED_MIN_STD)
        candidates = _dedupe_candidates(_find_square_blobs(gray, min_std=_RELAXED_MIN_STD))
    if len(candidates) < 4:
        raise MarkersNotFound(f"Найдено {len(candidates)} меток из 4 — недостаточно")

    quad, score = _best_quad(candidates)
    if quad is None or score > 2.5:  # эмпирический порог — выше означает явно не прямоугольник
        raise MarkersNotFound(f"Не удалось выбрать 4 угла листа (score={score:.2f})")

    tl, tr, br, bl = quad
    src = np.array([tl, tr, br, bl], dtype="float32")
    half = MARKER_MM * PX_PER_MM / 2
    dst = np.array([
        [3 * PX_PER_MM + half, 3 * PX_PER_MM + half],
        [200 * PX_PER_MM + half, 3 * PX_PER_MM + half],
        [200 * PX_PER_MM + half, 138.5 * PX_PER_MM + half],
        [3 * PX_PER_MM + half, 138.5 * PX_PER_MM + half],
    ], dtype="float32")

    H = cv2.getPerspectiveTransform(src, dst)
    out_w, out_h = int(PAGE_W_MM * PX_PER_MM), int(HALF_H_MM * PX_PER_MM)
    return cv2.warpPerspective(img, H, (out_w, out_h))
