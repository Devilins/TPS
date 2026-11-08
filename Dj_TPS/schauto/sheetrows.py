"""Разбор строк одного листа таблицы заказов в "сырые" заказы. Чистые функции: без БД и сети.

Листы разных центров устроены по-разному, поэтому столбцы ищутся по названиям заголовков, а не по номерам.
Персональные данные клиентов (имя заказчика, телефон, ссылки) наружу не отдаются: заказчик/именинник и № банкета
используются только для отпечатка строки.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from .gsheet import KIND_TRIPS
from .parsers import (ParsedTime, YearResolver, clean_people, clean_person, norm_text, parse_extra_minutes, parse_month_header,
                      parse_time, row_fingerprint, split_date, strip_manager)

HEADER_SCAN_ROWS = 5
MAX_PROBLEM_SAMPLES = 8


class SheetLayoutError(Exception):
    pass


@dataclass
class RawOrder:
    row: int                       # номер строки в листе (с 1)
    date: date
    raw_time: str
    time: ParsedTime
    extra_from_comment: int
    photographer: str              # очищенное имя из ячейки (без телефона), '' если пусто; несколько человек - через « + »
    retoucher: str
    place: str                     # только для листа выездов: адрес из ячейки
    date_note: str = ''            # пометка менеджера после даты ("23.10 МЕГА") - возможно, заказ другого центра
    base_key: tuple = ()           # части отпечатка без номера повтора
    fingerprint: str = ''


@dataclass
class ParseResult:
    orders: list[RawOrder] = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {'rows': 0, 'in_window': 0, 'bad_date': 0, 'no_time': 0})
    problems: list[str] = field(default_factory=list)


def _header(cell: str) -> str:
    return ' '.join((cell or '').replace('\n', ' ').split()).casefold()


def find_columns(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Строка заголовков (индекс) и словарь поле -> индекс столбца. Берётся первое вхождение названия."""
    for h_idx, cells in enumerate(rows[:HEADER_SCAN_ROWS]):
        headers = [_header(c) for c in cells]
        if 'время' not in headers:
            continue
        cols: dict[str, int] = {}

        def first(name, startswith=False):
            for i, h in enumerate(headers):
                if h == name or (startswith and h.startswith(name)):
                    return i
            return None

        cols['time'] = headers.index('время')
        # столбец даты бывает без заголовка/с битым заголовком - тогда это столбец слева от "Время"
        date_col = first('дата')
        if date_col is None and cols['time'] > 0:
            date_col = cols['time'] - 1
        if date_col is None:
            raise SheetLayoutError('не найден столбец с датой')
        cols['date'] = date_col
        for key, name, sw in (('banquet', '№ банкета', True), ('customer', 'заказчик', False),
                              ('birthday', 'именинник', False), ('photographer', 'фотограф', True),
                              ('retoucher', 'ретушер', True), ('comment', 'комментар', True), ('place', 'адрес', False)):
            idx = first(name, sw)
            if idx is not None:
                cols[key] = idx
        if 'photographer' not in cols:
            raise SheetLayoutError('не найден столбец «Фотограф»')
        return h_idx, cols
    raise SheetLayoutError('не найдена строка заголовков (столбец «Время»)')


def parse_rows(kind: str, rows: list[list[str]], today: date, date_from: date, date_to: date,
               manager: str = '') -> ParseResult:
    """Заказы листа за окно [date_from, date_to]. Строки вне окна и пустые пропускаются.

    manager - имя руководителя, которое стоит в ячейке "Фотограф" по умолчанию (LL), см. parsers.strip_manager."""
    result = ParseResult()
    if not rows:
        return result
    h_idx, cols = find_columns(rows)

    def cell(cells, key):
        i = cols.get(key)
        return cells[i].strip() if i is not None and i < len(cells) else ''

    # Проход сверху вниз: год в ячейках не указан, определяется по порядку строк (см. YearResolver)
    resolver = YearResolver(today)
    occurrences: dict[tuple, int] = {}
    for idx in range(h_idx + 1, len(rows)):
        cells, row_no = rows[idx], idx + 1
        date_text, time_text = cell(cells, 'date'), cell(cells, 'time')
        if not date_text and not time_text:
            continue
        header = parse_month_header(date_text)
        if header:  # разделитель месяца; с годом - надёжная опора для следующих строк
            if header[0]:
                resolver.reset(*header)
            continue
        result.stats['rows'] += 1
        parts = split_date(date_text)
        d = resolver.resolve(parts.day, parts.month, parts.year) if parts else None
        if d is None:
            if date_text:
                result.stats['bad_date'] += 1
                if len(result.problems) < MAX_PROBLEM_SAMPLES:
                    result.problems.append(f'строка {row_no}: дата «{date_text[:20]}» не распознана')
            continue
        if not date_from <= d <= date_to:
            continue
        result.stats['in_window'] += 1
        if not time_text:
            result.stats['no_time'] += 1
            continue

        parsed_time = parse_time(time_text)
        comment_extra = 0
        if parsed_time.ok and not parsed_time.extra:
            comment_extra = parse_extra_minutes(cell(cells, 'comment'))

        order = RawOrder(
            row=row_no, date=d, raw_time=time_text[:60], time=parsed_time, extra_from_comment=comment_extra,
            photographer=clean_people(strip_manager(cell(cells, 'photographer'), manager))[:120],
            retoucher=clean_person(cell(cells, 'retoucher'))[:60],
            place=cell(cells, 'place') if kind == KIND_TRIPS else '',
            date_note=parts.note,
        )
        # В отпечаток входят дата, № банкета и заказчик/именинник (как есть) и номер повтора одинаковых строк
        # день.месяц без года: год подбирается по порядку строк и может пересчитаться - отпечаток от этого не должен меняться
        order.base_key = (f'{d.day}.{d.month}', cell(cells, 'banquet'), cell(cells, 'customer'), cell(cells, 'birthday'),
                          order.place)
        # Повторы считаем по нормализованному ключу - иначе строки, различающиеся только регистром/пробелами,
        # получили бы одинаковый отпечаток
        norm_key = tuple(norm_text(part) for part in order.base_key)
        n = occurrences.get(norm_key, 0)
        occurrences[norm_key] = n + 1
        order.fingerprint = row_fingerprint(*order.base_key, occurrence=n)
        result.orders.append(order)
    return result


# Признаки адреса: улица, шоссе, проспект, дом, км, торговый центр, метро. Нужно минимум два разных признака
_ADDRESS_MARKERS = re.compile(r'\b(?:ул\.|улица|ш\.|шоссе|пр\.|пр-т|просп\w*|бул\.|бульвар|д\.|стр\.|км|километр|тц|трц|трк|м\.|мкад)(?=\W|$)',
                              re.IGNORECASE)


def find_address(rows: list[list[str]]) -> str:
    """Адрес центра из строки заголовков листа: в части листов он записан в служебной ячейке справа от известных столбцов
    ("м.Ленинский проспект, ул.Вавилова, д.3, тц Гагаринский, 3 этаж"). Пустая строка, если подходящей ячейки нет."""
    try:
        h_idx, cols = find_columns(rows)
    except SheetLayoutError:
        return ''
    known = set(cols.values())
    best, best_score = '', 1
    for i, cell in enumerate(rows[h_idx]):
        text = ' '.join(cell.split())
        if i in known or not 15 <= len(text) <= 250 or re.match(r'^\d\)', text) or 'добрый день' in text.casefold():
            continue
        score = len({m.group(0).casefold() for m in _ADDRESS_MARKERS.finditer(text)})
        if score > best_score or (score == best_score and score > 1 and len(text) > len(best)):
            best, best_score = text, score
    return best.strip(' .')[:200]
