"""Выгрузка и загрузка маршрутов в CSV (таблицу удобно заполнять в Excel).

Формат: `Откуда;Куда;Минут;Вариант` (разделитель - точка с запятой, кодировка utf-8 с BOM).
Выгрузка содержит и все ещё не заполненные пары центров с пустым временем - файл служит шаблоном.
"""
import csv
import io
from itertools import permutations

from django.db.transaction import atomic

from .models import Route, Venue

HEADER = ['Откуда', 'Куда', 'Минут', 'Вариант']
MAX_ERRORS_SHOWN = 20


class RoutesImportError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(errors[:MAX_ERRORS_SHOWN]))


def export_routes_csv() -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(HEADER)
    existing = set()
    for r in Route.objects.select_related('from_venue', 'to_venue'):
        writer.writerow([r.from_venue.name, r.to_venue.name, r.duration_min, r.description])
        existing.add((r.from_venue_id, r.to_venue_id))
    for a, b in permutations(Venue.objects.filter(is_active=True), 2):
        if (a.id, b.id) not in existing:
            writer.writerow([a.name, b.name, '', ''])
    return out.getvalue()


def _decode(raw: bytes) -> str:
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1251')  # Excel в русской локали сохраняет CSV в ANSI


def import_routes_csv(raw: bytes, mirror: bool) -> dict:
    """Загружает маршруты. Либо всё, либо ничего: при любой ошибке в файле бросает RoutesImportError."""
    text = _decode(raw)
    delimiter = ';' if text.split('\n', 1)[0].count(';') >= text.split('\n', 1)[0].count(',') else ','

    venues = {}
    for v in Venue.objects.all():
        venues[v.name.strip().lower()] = v
        if v.sheet_tab_name:
            venues.setdefault(v.sheet_tab_name.strip().lower(), v)

    errors, rows, skipped = [], {}, 0
    for line_no, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1):
        row = [c.strip() for c in row]
        if not any(row):
            continue
        if line_no == 1 and row[0].lower() == HEADER[0].lower():
            continue
        if len(row) < 3:
            errors.append(f'Строка {line_no}: ожидалось минимум 3 столбца (Откуда;Куда;Минут)')
            continue
        src, dst = venues.get(row[0].lower()), venues.get(row[1].lower())
        if src is None or dst is None:
            errors.append(f'Строка {line_no}: неизвестный центр «{row[0] if src is None else row[1]}»')
            continue
        if src == dst:
            errors.append(f'Строка {line_no}: центры отправления и назначения совпадают')
            continue
        if row[2] == '':
            skipped += 1  # пара из шаблона, время не заполнено
            continue
        try:
            minutes = int(row[2])
            if not 0 <= minutes <= 600:
                raise ValueError
        except ValueError:
            errors.append(f'Строка {line_no}: «{row[2]}» - время должно быть целым числом минут от 0 до 600')
            continue
        description = row[3] if len(row) > 3 else ''
        rows[(src.id, dst.id, description)] = (src, dst, minutes)  # повтор строки - побеждает последняя

    if errors:
        raise RoutesImportError(errors)

    created = updated = mirrored = 0
    with atomic():
        for (_, _, description), (src, dst, minutes) in rows.items():
            _, was_created = Route.objects.update_or_create(
                from_venue=src, to_venue=dst, description=description, defaults={'duration_min': minutes})
            if was_created:
                created += 1
            else:
                updated += 1
        if mirror:
            for (src_id, dst_id, description), (src, dst, minutes) in rows.items():
                if (dst_id, src_id, description) in rows:
                    continue
                _, was_created = Route.objects.get_or_create(
                    from_venue=dst, to_venue=src, description=description, defaults={'duration_min': minutes})
                mirrored += was_created
    return {'created': created, 'updated': updated, 'mirrored': mirrored, 'skipped': skipped}
