"""Работа с Google-таблицами заказов.

Таблиц две - по одной на бренд (Laserland и Joki Joya), у каждой свои правила листов (см. classify_tab).
Здесь - правила листов (`classify_tab`), ID таблиц и ЗАПАСНОЕ публичное чтение (`list_tabs`, `read_tab_rows`: таблицы открыты по
ссылке, листы отдаются публичным экспортом). Основной путь чтения и запись - через сервисный аккаунт: `googleapi`, `tabsource`
(см. schauto/CLAUDE.md).
"""
import csv
import io
import json
import re
from dataclasses import dataclass

import httpx
from django.conf import settings

HTTP_TIMEOUT = 30

BRANDS = ('LL', 'JJ')

# Виды листов
KIND_CENTER = 'center'    # лист центра с фототочкой - заказы этого центра
KIND_TRIPS = 'trips'      # LL: лист "ВЫЕЗДЫ" - заказы на адреса центров без фототочки LL
KIND_VIDEO = 'video'      # LL: лист "ВИДЕО ВСЕ ЦЕНТРЫ" - заказные видеосъёмки, центр определяется по № банкета
KIND_IGNORED = 'ignored'  # не используем

# В ячейке "Фотограф" таблицы Laserland по умолчанию стоит руководитель с телефоном ("Катерина 89688649620"), а имя фотографа
# дописывается после; сам по себе он исполнителем не считается
MANAGER_NAMES = {'LL': 'Катерина'}

# В htmlview вкладки перечислены как items.push({name: "...", pageUrl: "...", gid: "123", ...})
_TAB_RE = re.compile(r'\{name:\s*"((?:[^"\\]|\\.)*)"[^}]*?gid:\s*"?(\d+)')
# Лист центра в таблице Joki Joya: "<Центр> JJ" (листы "... LL" в ней - остатки Laserland, игнорируются)
_JJ_CENTER_RE = re.compile(r'^(?P<base>.+?)\s+JJ$', re.IGNORECASE)
# Листы таблицы Laserland, которые не являются листами центров
_LL_SPECIAL = {
    'шоу все центры': KIND_IGNORED,
    'выезды': KIND_TRIPS,
    'видео все центры': KIND_VIDEO,
}


class SheetError(Exception):
    pass


@dataclass(frozen=True)
class Tab:
    name: str
    gid: int
    kind: str
    center: str = ''  # для KIND_CENTER: название центра без бренда ("Гагаринский")


def classify_tab(brand: str, name: str) -> tuple[str, str]:
    """Вид листа и название центра (только для листа центра) по правилам таблицы бренда."""
    name = name.strip()
    if brand == 'JJ':
        m = _JJ_CENTER_RE.match(name)
        return (KIND_CENTER, m.group('base').strip()) if m else (KIND_IGNORED, '')
    if brand == 'LL':
        special = _LL_SPECIAL.get(name.casefold())
        return (special, '') if special else (KIND_CENTER, name)
    raise ValueError(f'Неизвестный бренд: {brand}')


def center_name(base: str, brand: str) -> str:
    """Название центра в schauto: "ГАГАРИНСКИЙ" + LL -> "Гагаринский LL" (бренд в названии - центры разных брендов
    с одинаковым названием не должны совпасть)."""
    base = base.strip()
    if base.isupper():
        base = base.capitalize()
    return f'{base} {brand}'


def get_sheet_id(brand: str, sheet_id: str | None = None) -> str:
    sheet_id = sheet_id or settings.SCHAUTO_SHEET_IDS.get(brand, '')
    if not sheet_id:
        raise SheetError(f"Не задан ID таблицы {brand} (переменная окружения SCHAUTO_SHEET_ID_{brand})")
    return sheet_id


def _get(url: str) -> httpx.Response:
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise SheetError(f"Не удалось получить данные из Google-таблицы: {e}") from e
    return resp


def list_tabs(brand: str, sheet_id: str | None = None) -> list[Tab]:
    """Листы таблицы бренда с определённым видом"""
    sheet_id = get_sheet_id(brand, sheet_id)
    html = _get(f"https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview").text
    tabs = []
    for raw_name, gid in _TAB_RE.findall(html):
        try:
            name = json.loads(f'"{raw_name}"')
        except ValueError:
            name = raw_name
        kind, center = classify_tab(brand, name)
        tabs.append(Tab(name=name, gid=int(gid), kind=kind, center=center))
    if not tabs:
        raise SheetError("В таблице не найдено ни одного листа: проверьте ID и доступ по ссылке")
    return tabs


def read_tab_rows(sheet_id: str, gid: int) -> list[list[str]]:
    """Все строки листа как списки строк (как показаны в таблице). Номер строки в листе = индекс + 1."""
    text = _get(f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}").content.decode('utf-8')
    return list(csv.reader(io.StringIO(text)))
