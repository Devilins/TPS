"""Импорт заказов из Google-таблиц в PhotoOrder (кнопка "Загрузить из таблиц").

Сначала сеть, потом БД: листы читаются через источник (`tabsource`: сервисный аккаунт - всего 2 запроса на таблицу, таблицы разных
брендов параллельно; запасной путь - публичная ссылка), затем всё разбирается и пишется в БД последовательно в одной транзакции.
Повторная загрузка идемпотентна: заказ опознаётся по отпечатку строки, исчезнувшие из таблицы заказы помечаются статусом
"Пропал из таблицы".
"""
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Q
from django.db.transaction import atomic
from django.utils import timezone

from tph_system.models import ImplEvents

from . import googleapi
from .gsheet import BRANDS, KIND_CENTER, KIND_TRIPS, MANAGER_NAMES, SheetError, get_sheet_id, list_tabs, read_tab_rows
from .mapping import PERSON_IGNORED, PERSON_MATCHED, PERSON_UNMATCHED, Resolver
from .models import PhotoOrder, Venue
from .parsers import PEOPLE_SEPARATOR, split_people
from .sheetrows import SheetLayoutError, parse_rows
from .tabsource import PublicSource, default_source

logger = logging.getLogger(__name__)

HISTORY_DAYS = 14   # сколько дней назад от сегодня загружаем по умолчанию
FUTURE_DAYS = 120   # и вперёд. Год в датах не указан, поэтому окно должно быть заметно меньше полугода

UPDATE_FIELDS = ['sheet_gid', 'sheet_row', 'venue', 'place_raw', 'date', 'time_start', 'time_end', 'extra_minutes',
                 'slots', 'raw_time', 'notes', 'photographer_raw', 'retoucher_raw', 'photographer', 'retoucher', 'no_retouch',
                 'status', 'last_seen_at']


@dataclass
class TabReport:
    brand: str
    tab: str
    created: int = 0
    updated: int = 0
    gone: int = 0
    bad_date: int = 0
    no_time: int = 0
    problems: list[str] = field(default_factory=list)
    error: str = ''


@dataclass
class ImportReport:
    date_from: date
    date_to: date
    tabs: list[TabReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # ошибки уровня таблицы (нет ID, нет доступа)
    notes: list[str] = field(default_factory=list)   # примечания (например, чтение по публичной ссылке вместо сервисного аккаунта)

    @property
    def created(self): return sum(t.created for t in self.tabs)

    @property
    def updated(self): return sum(t.updated for t in self.tabs)

    @property
    def gone(self): return sum(t.gone for t in self.tabs)

    @property
    def failed_tabs(self): return [t for t in self.tabs if t.error]

    def summary(self) -> str:
        text = (f'Загрузка заказов {self.date_from:%d.%m.%Y}-{self.date_to:%d.%m.%Y}: листов {len(self.tabs)}, '
                f'новых {self.created}, обновлено {self.updated}, пропало из таблицы {self.gone}')
        problems = self.errors + [f'{t.brand} «{t.tab}»: {t.error}' for t in self.failed_tabs]
        text += f'. Ошибки: {"; ".join(problems)}' if problems else ''
        return text + (f'. Примечание: {"; ".join(self.notes)}' if self.notes else '')


def compute_status(time_ok: bool, venue_id: int | None, photographer_raw: str) -> str:
    if not time_ok or venue_id is None:
        return PhotoOrder.STATUS_NEEDS_FIX
    return PhotoOrder.STATUS_ASSIGNED if photographer_raw else PhotoOrder.STATUS_OPEN


def resolve_people_and_place(resolver: Resolver, photographer: str, retoucher: str, place: str,
                             venue_id: int | None) -> dict:
    """Поля заказа, зависящие от справочников: кто назначен и где проходит заказ.

    В ячейке «Фотограф» один человек или несколько через « + » (заказ с перерывом снимают двое). Один исполнитель - в
    `photographer`; несколько - `photographer` пуст, а сопоставленные сотрудники возвращаются в `team_ids` (это не поле
    модели: их записывает `sync_team`). Игнорируемые имена (пометки вроде «штат») в `photographer_raw` не попадают."""
    keep = (PERSON_MATCHED, PERSON_UNMATCHED)
    kept = [(name, status, staff_id) for name, status, staff_id in
            ((name, *resolver.person(name)) for name in split_people(photographer)) if status in keep]
    team = list(dict.fromkeys(staff_id for _, status, staff_id in kept if status == PERSON_MATCHED))
    single = len(kept) == 1
    rt_status, rt_id = resolver.person(retoucher)
    no_retouch = resolver.is_no_retouch(retoucher)
    if no_retouch:
        rt_status, rt_id = PERSON_IGNORED, None
    fields = {
        'photographer_raw': PEOPLE_SEPARATOR.join(name for name, _, _ in kept)[:120],
        'photographer_id': team[0] if single and team else None,
        'team_ids': [] if single else team,
        'retoucher_raw': retoucher if rt_status in keep else '',
        'retoucher_id': rt_id,
        'no_retouch': no_retouch,
    }
    if venue_id is None and place:
        venue_id = resolver.place(place)
        fields['place_raw'] = '' if venue_id else place[:120]  # адрес храним, только пока центр не определён
    else:
        fields['place_raw'] = ''
    fields['venue_id'] = venue_id
    return fields


def sync_team(wanted: dict[int, list[int]]):
    """Приводит `PhotoOrder.photographers` к нужному виду: {id заказа: [id сотрудников]}. Лишних убирает, недостающих добавляет;
    запросов - один на чтение и по одному на вставку/удаление, а не по запросу на заказ"""
    if not wanted:
        return
    through = PhotoOrder.photographers.through
    current: dict[int, set[int]] = defaultdict(set)
    for order_id, staff_id in through.objects.filter(photoorder_id__in=list(wanted)).values_list('photoorder_id', 'staff_id'):
        current[order_id].add(staff_id)
    add = []
    for order_id, ids in wanted.items():
        want = set(ids)
        add.extend(through(photoorder_id=order_id, staff_id=staff_id) for staff_id in sorted(want - current[order_id]))
        stale = current[order_id] - want
        if stale:
            through.objects.filter(photoorder_id=order_id, staff_id__in=stale).delete()
    through.objects.bulk_create(add)


def apply_mappings() -> int:
    """Пересчитать заказы с неопознанными именами/адресами после появления новых сопоставлений"""
    resolver = Resolver()
    changed = []
    unresolved = ((Q(photographer__isnull=True) & ~Q(photographer_raw='')) |
                  (Q(retoucher__isnull=True) & ~Q(retoucher_raw='')) |
                  (Q(venue__isnull=True) & ~Q(place_raw='')))
    watched = ('photographer_id', 'retoucher_id', 'venue_id', 'photographer_raw', 'retoucher_raw', 'place_raw',
               'no_retouch', 'status')
    teams: dict[int, list[int]] = {}
    for order in (PhotoOrder.objects.exclude(status=PhotoOrder.STATUS_GONE).filter(unresolved)
                  .prefetch_related('photographers')):
        before = tuple(getattr(order, name) for name in watched)
        team_before = {s.pk for s in order.photographers.all()}
        fields = resolve_people_and_place(resolver, order.photographer_raw, order.retoucher_raw, order.place_raw,
                                          order.venue_id)
        team = fields.pop('team_ids')
        if order.no_retouch and not order.retoucher_raw:
            fields['no_retouch'] = True  # "исходники" в ячейке уже распознаны при загрузке, сырого значения не осталось
        for name, value in fields.items():
            setattr(order, name, value)
        order.status = compute_status(order.time_start is not None, order.venue_id, order.photographer_raw)
        if team_before != set(team):
            teams[order.pk] = team
        if tuple(getattr(order, name) for name in watched) != before or team_before != set(team):
            changed.append(order)
    if changed:
        PhotoOrder.objects.bulk_update(
            changed, ['venue', 'place_raw', 'photographer_raw', 'retoucher_raw', 'photographer', 'retoucher',
                      'no_retouch', 'status'])
        sync_team(teams)
    return len(changed)


def _per_brand(source, fn, brands) -> dict:
    """fn(бренд) для каждого бренда: сеть ждём параллельно, если источник это допускает"""
    if source.parallel_brands:
        return googleapi.run_per_brand(fn, {brand: brand for brand in brands})
    return {brand: fn(brand) for brand in brands}


def run_import(brands=BRANDS, date_from: date | None = None, date_to: date | None = None, *, today: date | None = None,
               lister=None, fetcher=None, source=None) -> ImportReport:
    """lister/fetcher - подмена публичного чтения (тесты), source - готовый источник; иначе сервисный аккаунт Google,
    а если он не настроен - публичная ссылка (с примечанием в отчёте)"""
    today = today or timezone.localdate()
    date_from = date_from or today - timedelta(days=HISTORY_DAYS)
    date_to = date_to or today + timedelta(days=FUTURE_DAYS)
    report = ImportReport(date_from=date_from, date_to=date_to)
    if source is None:
        if lister or fetcher:
            source = PublicSource(lister or list_tabs, fetcher or read_tab_rows)
        else:
            source, note = default_source()
            if note:
                report.notes.append(note)
    started = time.monotonic()

    # 1. Списки листов (сеть; БД здесь не трогаем)
    def list_brand(brand):
        try:
            get_sheet_id(brand)
            return source.tabs(brand), ''
        except SheetError as e:
            return None, str(e)

    listed = _per_brand(source, list_brand, brands)

    # 2. Что читать: листы центров с привязанным Venue и лист выездов (у Laserland)
    jobs: dict[str, list] = defaultdict(list)  # бренд -> [(лист, Venue|None)]
    for brand in brands:
        tabs, error = listed[brand]
        if error:
            report.errors.append(f'[{brand}] {error}')
            continue
        by_name = {t.name.casefold(): t for t in tabs}
        for venue in Venue.objects.filter(brand=brand, is_active=True).exclude(sheet_tab_name=''):
            tab = by_name.get(venue.sheet_tab_name.casefold())
            if tab is None:
                report.tabs.append(TabReport(brand, venue.sheet_tab_name, error='лист не найден в таблице'))
            elif tab.kind != KIND_CENTER:
                report.tabs.append(TabReport(brand, tab.name, error='лист не является листом центра'))
            else:
                jobs[brand].append((tab, venue))
        jobs[brand].extend((t, None) for t in tabs if t.kind == KIND_TRIPS)

    # 3. Читаем значения листов (сеть)
    def read_brand(brand):
        try:
            return source.read(brand, [tab for tab, _ in jobs[brand]]), ''
        except SheetError as e:
            return None, str(e)

    fetched = _per_brand(source, read_brand, [brand for brand in brands if jobs[brand]])
    logger.info('Загрузка заказов: чтение %s, листов %s, %.1f с', source.name, sum(len(j) for j in jobs.values()), time.monotonic() - started)

    # 4. Разбираем и пишем
    resolver = Resolver()
    now = timezone.now()
    with atomic():
        for brand, (data, error) in fetched.items():
            if error:
                report.errors.append(f'[{brand}] {error}')
                continue
            for tab, venue in jobs[brand]:
                rows, tab_error = data[tab.gid]
                _import_tab(report, brand, tab, venue, rows, tab_error, resolver, today, date_from, date_to, now)

    ImplEvents.objects.create(
        event_type='Schauto_Import', event_message=report.summary(), solved='Нет' if (report.errors or report.failed_tabs) else 'Да',
        status='Системная ошибка' if (report.errors or report.failed_tabs) else 'Успешно')
    return report


def _import_tab(report, brand, tab, venue, rows, error, resolver, today, date_from, date_to, now):
    """Разбирает прочитанный лист и записывает его заказы; сбой листа попадает в отчёт, остальные листы продолжаются"""
    tab_report = TabReport(brand, tab.name, error=error)
    report.tabs.append(tab_report)
    if error:
        return
    try:
        parsed = parse_rows(tab.kind, rows, today, date_from, date_to, MANAGER_NAMES.get(brand, ''))
    except SheetLayoutError as e:
        tab_report.error = f'нестандартная разметка листа: {e}'
        return
    tab_report.bad_date = parsed.stats['bad_date']
    tab_report.no_time = parsed.stats['no_time']
    tab_report.problems = parsed.problems
    _store(brand, tab, venue, parsed, resolver, tab_report, date_from, date_to, now)


def _store(brand, tab, venue, parsed, resolver, tab_report, date_from, date_to, now):
    existing = {o.fingerprint: o for o in PhotoOrder.objects.filter(brand=brand, tab_name=tab.name)}
    to_create, to_update, seen = [], [], set()
    teams: dict[str, list[int]] = {}         # отпечаток -> сотрудники заказа с несколькими фотографами

    for raw in parsed.orders:
        seen.add(raw.fingerprint)
        extra = raw.time.extra or raw.extra_from_comment
        notes = list(raw.time.notes)
        if raw.extra_from_comment:
            notes.append(f'продление {raw.extra_from_comment} мин взято из комментария')
        if raw.date_note:
            notes.append(f'пометка в дате: {raw.date_note}')
        fields = resolve_people_and_place(resolver, raw.photographer, raw.retoucher, raw.place,
                                          venue.id if venue else None)
        teams[raw.fingerprint] = fields.pop('team_ids')
        values = {
            'sheet_gid': tab.gid, 'sheet_row': raw.row, 'date': raw.date,
            'time_start': raw.time.start, 'time_end': raw.time.end, 'extra_minutes': extra,
            'slots': [[a.strftime('%H:%M'), b.strftime('%H:%M')] for a, b in raw.time.slots],
            'raw_time': raw.raw_time, 'notes': '; '.join(notes)[:200], 'last_seen_at': now,
            'status': compute_status(raw.time.ok, fields['venue_id'], fields['photographer_raw']),
            **fields,
        }
        order = existing.get(raw.fingerprint)
        if order is None:
            to_create.append(PhotoOrder(brand=brand, tab_name=tab.name, fingerprint=raw.fingerprint, **values))
        else:
            for name, value in values.items():
                setattr(order, name, value)
            to_update.append(order)

    for fp, order in existing.items():
        if fp not in seen and order.status != PhotoOrder.STATUS_GONE and date_from <= order.date <= date_to:
            order.status = PhotoOrder.STATUS_GONE
            to_update.append(order)
            tab_report.gone += 1

    PhotoOrder.objects.bulk_create(to_create)
    PhotoOrder.objects.bulk_update(to_update, UPDATE_FIELDS)
    if any(o.pk is None for o in to_create):          # СУБД не вернула ключи вставленных строк
        ids = dict(PhotoOrder.objects.filter(brand=brand, tab_name=tab.name, fingerprint__in=[o.fingerprint for o in to_create])
                   .values_list('fingerprint', 'pk'))
        for o in to_create:
            o.pk = ids[o.fingerprint]
    # состав команды: у обновлённых заказов он мог измениться, у новых нужен только непустой
    sync_team({o.pk: teams[o.fingerprint] for o in to_update if o.fingerprint in teams}
              | {o.pk: teams[o.fingerprint] for o in to_create if teams[o.fingerprint]})
    tab_report.created = len(to_create)
    tab_report.updated = len(to_update) - tab_report.gone
