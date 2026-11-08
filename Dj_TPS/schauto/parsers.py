"""Разбор значений ячеек таблиц заказов: дата, время, продление, имена, адреса.

Чистые функции без Django и сети. Таблицы заполняют вручную, поэтому форматы разнородные -
всё нераспознанное возвращается как "не ок" с понятным замечанием и уходит в ручной разбор, а не угадывается.
"""
import hashlib
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date, time, timedelta

# --- дата ---------------------------------------------------------------------------------------------------------
# "02.10", "2.10", "02.1", "02.10.", "02.10.26", "02.10.2026", допускаются разделители . / -.
# После даты может стоять пометка менеджера ("23.10 МЕГА") - она не часть даты
_DATE_RE = re.compile(r'^\s*(\d{1,2})\s*[./\-]\s*(\d{1,2})(?:\s*[./\-]\s*(\d{4}|\d{2}))?\s*[./]?(?P<rest>.*)$', re.DOTALL)
# Строки-разделители внутри листа: "ЯНВАРЬ 2026" (у свежих месяцев года может не быть: "ОКТЯБРЬ")
_MONTH_STEMS = ('январ', 'феврал', 'март', 'апрел', 'ма', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр')
_MONTH_ROW_RE = re.compile(
    r'^\s*(?P<month>январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*\s*(?P<year>\d{4})?\s*г?\.?\s*$',
    re.IGNORECASE)


@dataclass(frozen=True)
class DateParts:
    day: int
    month: int
    year: int | None  # None - в ячейке года нет
    note: str         # пометка после даты ("МЕГА"), если есть


def split_date(text: str) -> DateParts | None:
    """День, месяц, (год) и пометка из ячейки даты; None, если это не дата. Корректность даты (31.02) не проверяется."""
    m = _DATE_RE.match(text or '')
    if not m:
        return None
    rest = m.group('rest')
    if rest[:1].isdigit() or rest[:1] == ':':
        return None  # цифры/двоеточие сразу после даты ("12.103", "12.10:30") - мусор или время, а не дата
    year = m.group(3)
    if year:
        year = int(year) + (2000 if len(year) == 2 else 0)
    return DateParts(int(m.group(1)), int(m.group(2)), year or None, rest.strip(' .,;:-/')[:30])


def parse_month_header(text: str) -> tuple[int | None, int] | None:
    """Строка-разделитель месяца: (год или None, месяц) либо None, если это не разделитель"""
    m = _MONTH_ROW_RE.match(text or '')
    if not m:
        return None
    stem = m.group('month').casefold()
    month = next(i for i, stem_ in enumerate(_MONTH_STEMS, start=1) if stem.startswith(stem_))
    return (int(m.group('year')) if m.group('year') else None), month


def is_month_header(text: str) -> bool:
    return parse_month_header(text) is not None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


class YearResolver:
    """Подбирает год датам без года, идя по строкам листа сверху вниз.

    В листах месяцы идут блоками от новых к старым (сверху будущие и текущие заказы), поэтому год выбирается ближайшим
    к опорной дате - медиане нескольких последних строк: единичные "залётные" строки опору не сбивают.
    Опора сбрасывается разделителем с годом ("ЯНВАРЬ 2025") и датой с явным годом. Для первой строки листа берётся
    самая поздняя дата, которая не дальше чем на ANCHOR_AHEAD_DAYS от сегодня в будущем.
    """
    ANCHOR_AHEAD_DAYS = 100
    RECENT = 5

    def __init__(self, today: date):
        self.today = today
        self.recent: deque[date] = deque(maxlen=self.RECENT)

    def reset(self, year: int, month: int):
        self.recent.clear()
        self.recent.append(date(year, month, 15))

    def resolve(self, day: int, month: int, year: int | None = None) -> date | None:
        if year:
            result = _safe_date(year, month, day)
        elif not self.recent:
            limit = self.today + timedelta(days=self.ANCHOR_AHEAD_DAYS)
            candidates = sorted(d for d in (_safe_date(y, month, day) for y in range(self.today.year - 2, self.today.year + 2)) if d)
            result = max((d for d in candidates if d <= limit), default=candidates[0] if candidates else None)
        else:
            ref = sorted(self.recent)[len(self.recent) // 2]
            candidates = [d for d in (_safe_date(y, month, day) for y in (ref.year - 1, ref.year, ref.year + 1)) if d]
            result = min(candidates, key=lambda d: abs((d - ref).days), default=None)
        if result:
            self.recent.append(result)
        return result


# --- время --------------------------------------------------------------------------------------------------------
# "17:30-18:30", "20.00-21.00", "14-00-15-00", "17/30-18.30", "19:30 - 20:30"
# + варианты "14:50--15:50", "15:50:00-16:50", "13;45-14:45", "15 00-16:00"
_RANGE_RE = re.compile(r'(\d{1,2})\s*[:.\-/;,]?\s*(\d{2})(?::00)?\s*[-–—]+\s*(\d{1,2})\s*[:.\-/;,]?\s*(\d{2})(?::00)?')
# Только длительность без времени начала: "1 час", "2,5 часа", "30 минут"
_DURATION_ONLY_RE = re.compile(r'\d+(?:[.,]\d+)?\s*(?:час|мин)|^\s*час', re.IGNORECASE)

# Продление: "+ доп час", "доп 30 мин", "+30 мин", "+ 1 час", "доп пол часа", "+1,5 часа"
_PLUS = r'(?:\+|доп\w*\.?)\s*'
_EXTRA_PARTS = (
    (re.compile(_PLUS + r'(\d+)\s*мин\w*', re.IGNORECASE), lambda m: int(m.group(1))),
    (re.compile(_PLUS + r'(\d+(?:[.,]\d+)?)\s*час\w*', re.IGNORECASE), lambda m: round(float(m.group(1).replace(',', '.')) * 60)),
    (re.compile(_PLUS + r'(?:пол\s*часа|полчаса|1/2\s*часа)', re.IGNORECASE), lambda m: 30),
    (re.compile(_PLUS + r'час\b', re.IGNORECASE), lambda m: 60),
)
MAX_EXTRA_MINUTES = 240


# Перерыв между интервалами заказа от этого значения (мин) позволяет отдать части заказа разным фотографам
# или вставить в перерыв другой заказ; короче - фотограф остаётся на заказе весь день
SPLIT_GAP_MINUTES = 60


@dataclass
class ParsedTime:
    start: time | None = None  # начало первого интервала
    end: time | None = None    # конец последнего интервала без учёта продления
    extra: int = 0             # минуты продления ("+ доп час"); относится к концу последнего интервала
    ok: bool = False
    notes: list[str] = field(default_factory=list)
    slots: list[tuple[time, time]] = field(default_factory=list)  # интервалы по порядку, без пересечений


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def slot_gaps(slots: list[tuple[time, time]]) -> list[int]:
    """Перерывы между соседними интервалами, минуты"""
    return [_minutes(nxt[0]) - _minutes(prev[1]) for prev, nxt in zip(slots, slots[1:])]


def split_parts(slots: list[tuple[time, time]], min_gap: int = SPLIT_GAP_MINUTES) -> list[list[tuple[time, time]]]:
    """Части заказа, которые можно отдавать разным фотографам: интервалы, разделённые перерывом меньше `min_gap`, остаются вместе"""
    parts: list[list[tuple[time, time]]] = []
    for slot in slots:
        if parts and _minutes(slot[0]) - _minutes(parts[-1][-1][1]) < min_gap:
            parts[-1].append(slot)
        else:
            parts.append([slot])
    return parts


def parse_extra_minutes(text: str) -> int:
    """Суммарное продление в минутах, указанное в тексте ("доп час", "+30 мин"); 0, если не найдено."""
    total, text = 0, text or ''
    for pattern, minutes in _EXTRA_PARTS:
        for m in pattern.finditer(text):
            total += minutes(m)
        text = pattern.sub(' ', text)  # уже учтённое не считаем второй раз ("доп 30 мин" ловится и как "+ N час...")
    return min(total, MAX_EXTRA_MINUTES)


def parse_time(text: str) -> ParsedTime:
    """Интервал(ы) и продление из ячейки "Время". Несколько интервалов сохраняются по отдельности (`slots`): перерыв
    между ними может быть свободен для фотографа или другого заказа, см. split_parts."""
    result = ParsedTime()
    text = (text or '').strip()
    ranges = []
    for m in _RANGE_RE.finditer(text):
        h1, m1, h2, m2 = (int(g) for g in m.groups())
        if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
            result.notes.append(f'нереальное время «{m.group(0)}»')
            return result
        start, end = time(h1, m1), time(h2, m2)
        if end <= start:
            result.notes.append(f'конец не позже начала в «{m.group(0)}»')
            return result
        ranges.append((start, end))
    if not ranges:
        result.notes.append('указана только длительность, время начала неизвестно' if _DURATION_ONLY_RE.search(text)
                            else 'время не распознано')
        return result

    ranges.sort()
    slots = [ranges[0]]
    for start, end in ranges[1:]:
        if start <= slots[-1][1]:   # пересекающиеся/впритык интервалы - один
            slots[-1] = (slots[-1][0], max(slots[-1][1], end))
            result.notes.append('пересекающиеся интервалы объединены')
        else:
            slots.append((start, end))
    result.slots = slots
    result.start, result.end = slots[0][0], slots[-1][1]
    result.ok = True
    if len(slots) > 1:
        gaps = slot_gaps(slots)
        note = f'интервалов {len(slots)}, перерывы {", ".join(str(g) for g in gaps)} мин'
        if any(g >= SPLIT_GAP_MINUTES for g in gaps):
            note += ' - части можно отдать разным фотографам'
        result.notes.append(note)
    result.extra = parse_extra_minutes(_RANGE_RE.sub(' ', text))
    if result.extra:
        result.notes.append(f'продление {result.extra} мин')
    return result


# --- имена и адреса -----------------------------------------------------------------------------------------------

def clean_person(raw: str) -> str:
    """Имя из ячейки "Фотограф"/"Ретушер" без телефона и мусора: "Катерина 89688649620" -> "Катерина"."""
    text = re.sub(r'[^\w\s.\-]', ' ', raw or '')    # скобки, плюсы, запятые и т.п.
    text = re.sub(r'[\d_]+', ' ', text)               # телефоны и любые цифры
    return ' '.join(text.split()).strip(' .-')


PEOPLE_SEPARATOR = ' + '                               # так несколько фотографов записываются в ячейку и в базу
_PEOPLE_SPLIT_RE = re.compile(r'[+,;&]|\sи\s')          # «Роман + Лиза», «Дина, Юра», «Тигран и Лиза» (строчная «и»: «Даша И» - фамилия)


def split_people(raw: str) -> list[str]:
    """Имена из ячейки «Фотограф»: "Роман + Лиза Гужвенко" -> ['Роман', 'Лиза Гужвенко']. Когда заказ с перерывом снимают двое,
    их записывают через «+». Плюс в конце ("Екатерина Львова+ - -") - пометка в таблице, а не второй человек: пустые хвосты
    отбрасываются, имя остаётся одно. Повторы убираются. Ссылки и «/» не разделители (адрес соцсети не разбивается на «имена»)."""
    names: list[str] = []
    seen: set[str] = set()
    for part in _PEOPLE_SPLIT_RE.split(raw or ''):
        name = clean_person(part)
        key = norm_text(name)
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def clean_people(raw: str) -> str:
    """Очищенная ячейка «Фотограф»: одно имя или несколько через « + »"""
    return PEOPLE_SEPARATOR.join(split_people(raw))


def same_people(a: str, b: str) -> bool:
    """Одни и те же люди в двух записях (порядок и регистр не важны)"""
    return {norm_text(n) for n in split_people(a)} == {norm_text(n) for n in split_people(b)}


def strip_manager(raw: str, manager: str) -> str:
    """Убирает из ячейки "Фотограф" имя и телефон руководителя ("Катерина 89688649620"). В таблице Laserland это значение по умолчанию,
    а имя фотографа дописывается после него. Цифры телефона в таблице бывают с опечатками, поэтому подходит любой номер из 7+ цифр."""
    if not manager:
        return raw or ''
    return re.sub(rf'{re.escape(manager)}[^\W\d_]*[\s,:;\-]*\+?[\d\s\-()]{{7,}}', ' ', raw or '', flags=re.IGNORECASE)


def norm_text(raw: str) -> str:
    """Сопоставимый вид строки: регистр, ё/е, пробелы."""
    return ' '.join((raw or '').casefold().replace('ё', 'е').split())


def norm_person(raw: str) -> str:
    return norm_text(clean_person(raw))


def norm_place(raw: str) -> str:
    """Сопоставимый вид адреса: без пунктуации и префикса "Адрес:"."""
    text = re.sub(r'[^\w\s]', ' ', norm_text(raw))
    text = re.sub(r'^\s*адрес\b', ' ', text)
    return ' '.join(text.split())


NO_RETOUCH_VALUES = frozenset({'исходники', 'исходник'})  # JJ: клиент купил исходники, ретушь не нужна


def row_fingerprint(*parts: str, occurrence: int = 0) -> str:
    """Отпечаток строки заказа для повторного поиска (в таблицах нет ID заказа).

    Не включает время и исполнителя: перенос времени и назначение исполнителя не должны превращать заказ в "новый".
    """
    raw = '|'.join(norm_text(p) for p in parts) + f'#{occurrence}'
    return hashlib.sha256(('schauto-v1|' + raw).encode('utf-8')).hexdigest()[:32]
