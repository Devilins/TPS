"""Доступность сотрудника в день: разбор свободного текста из `WorkVacSchedule.time_availiable`.

Чистые функции без Django. День закрывают только отпуск, отгул и больничный в графике выходов и отпусков; пустой статус,
«Работает» и отсутствие записи значат «ставить можно». Время внутри дня вводят вручную ("с 15:00", "До 14:30 и с 18:30", "Занят 17:00-19:00", "весь день"),
поэтому нераспознанное не угадывается: результат `ok=False`, окон нет, и планировщик такого сотрудника в этот день не назначает
(ошибка видна в отчёте плана). Время в окнах - минуты от полуночи.
"""
import re
from dataclasses import dataclass

DAY = 24 * 60

# Время: "15", "15:30", "15.30" (часы без минут допустимы: "с 13", "до 17")
_T = r'(\d{1,2})(?:[:.](\d{2}))?'
_RANGE_RE = re.compile(rf'(?<![\d:.]){_T}(?!\d)\s*(?:[-–—]|до|по)\s*(?<![\d:.]){_T}(?!\d)')
_SINGLE_RE = re.compile(rf'(?:(?P<kw>до|после|с|от)\s*)?(?<![\d:.]){_T}(?!\d)')
_ALL_DAY_RE = re.compile(r'весь\s*день|целый\s*день|полный\s*день|свободен|любое\s*время|с\s*утра')
_LATIN_TO_CYR = str.maketrans({'c': 'с', 'a': 'а', 'o': 'о', 'e': 'е', 'p': 'р', 'x': 'х'})


@dataclass(frozen=True)
class Availability:
    windows: tuple[tuple[int, int], ...]  # интервалы, в которые сотрудник свободен
    raw: str = ''                         # исходный текст (для объяснений в плане)
    ok: bool = True                       # False - текст не разобран, окон нет
    blocked: str = ''                     # причина недоступности на весь день ("Отпуск")
    note: str = ''                        # как понят неоднозначный текст

    def covers(self, start: int, end: int) -> bool:
        return any(w0 <= start and end <= w1 for w0, w1 in self.windows)

    @property
    def all_day(self) -> bool:
        return self.windows == ((0, DAY),)

    def describe(self) -> str:
        if self.blocked:
            return self.blocked
        if not self.ok:
            return f'не разобрано: «{self.raw}»'
        if self.all_day:
            return 'весь день'
        return ', '.join(f'{_hm(a)}-{_hm(b)}' for a, b in self.windows)


ALL_DAY = Availability(((0, DAY),))


def _hm(minutes: int) -> str:
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def _to_minutes(hour: str, minute: str | None) -> int | None:
    h, m = int(hour), int(minute or 0)
    if h > 24 or m > 59 or (h == 24 and m):
        return None
    return h * 60 + m


def _merge(windows: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[list[int]] = []
    for start, end in sorted(w for w in windows if w[0] < w[1]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple((a, b) for a, b in merged)


def _normalize(text: str) -> str:
    text = text.casefold().replace('ё', 'е').translate(_LATIN_TO_CYR)
    text = re.sub(r'\([^)]*\)', ' ', text)                  # "С 18:00 (17:45)" - уточнение в скобках не считаем
    text = re.sub(r'(?<!\d)(\d{1,2})/(00|15|30|45)(?!\d)', r'\1:\2', text)  # "c 15/00" - это 15:00
    # "С 12:30/13:00" - две версии времени: консервативно берём более позднюю
    text = re.sub(rf'{_T}\s*/\s*{_T}', lambda m: f'{m.group(3)}:{m.group(4) or "00"}', text)
    return text


def parse_availability(text: str | None) -> Availability:
    """Окна свободного времени из текста. Пусто или "весь день" - свободен весь день."""
    raw = (text or '').strip()
    if not raw:
        return ALL_DAY
    s = _normalize(raw)
    if _ALL_DAY_RE.search(s):
        return Availability(((0, DAY),), raw, note='«с утра» понято как весь день' if 'утра' in s else '')

    def unparsed(why: str) -> Availability:
        return Availability((), raw, ok=False, note=why)

    if 'занят' in s:
        # "Занят 17:00-19:00", "с 15.00 до 16.00 занят": свободен всё остальное время
        times = [(m.group(1), m.group(2)) for m in re.finditer(rf'(?<![\d:.]){_T}(?!\d)', s)]
        minutes = [_to_minutes(h, mi) for h, mi in times]
        if len(minutes) != 2 or None in minutes or minutes[0] >= minutes[1]:
            return unparsed('не удалось понять, когда занят')
        return Availability(_merge([(0, minutes[0]), (minutes[1], DAY)]), raw, note=f'занят {_hm(minutes[0])}-{_hm(minutes[1])}')

    windows: list[tuple[int, int]] = []
    note = ''
    rest = s
    for m in _RANGE_RE.finditer(s):
        a, b = _to_minutes(m.group(1), m.group(2)), _to_minutes(m.group(3), m.group(4))
        if a is None or b is None or a >= b:
            return unparsed('нереальное время')
        windows.append((a, b))
    rest = _RANGE_RE.sub(' ', s)
    for m in _SINGLE_RE.finditer(rest):
        t = _to_minutes(m.group(2), m.group(3))
        if t is None:
            return unparsed('нереальное время')
        if m.group('kw') == 'до':
            windows.append((0, t))
        else:
            windows.append((t, DAY))
            if m.group('kw') is None:
                note = 'время без «с» понято как «с этого времени»'
    if not windows:
        return unparsed('время не найдено')
    merged = _merge(windows)
    if not merged:
        return unparsed('окно нулевой длины')
    return Availability(merged, raw, note=note)


BLOCKING_STATUSES = frozenset({'Отпуск', 'Отгул', 'Больничный'})


def day_availability(status: str | None, text: str | None) -> Availability:
    """Доступность за день по записи графика выходов и отпусков. День закрывают только отпуск, отгул и больничный;
    при пустом статусе, «Работает» и при отсутствии записи ставить можно (время - по тексту, если он есть)."""
    if status in BLOCKING_STATUSES:
        return Availability((), (text or '').strip(), blocked=status)
    return parse_availability(text)
