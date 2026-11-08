"""Связка планировщика с БД: собирает входные данные из заказов, графика сотрудников и маршрутов, сохраняет расчёт (PlanRun).

Сам алгоритм - в planner.py (чистая функция). В Schedule и в Google-таблицу этот модуль НЕ пишет: это этапы 4 и 5.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from django.db.models import Count, Min, Q
from django.db.transaction import atomic

from tph_system.models import ImplEvents, Schedule, Staff, WorkVacSchedule

from .availability import day_availability
from .models import Assignment, PhotoOrder, PlanRun, Route, Venue
from .planner import PlanPart, PlannerConfig, PlanStaff, config_to_dict, plan

MAX_SPAN_DAYS = 62            # дольше планировать за один расчёт не даём: вся неделя-две заказов и так видна
SCHEDULE_HISTORY_DAYS = 365   # смены на фототочке за этот срок считаются знакомством с центром


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _hm(minutes: int) -> str:
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def order_parts(order: PhotoOrder) -> list[PlanPart]:
    """Части заказа для планировщика. Продление относится к концу последней части"""
    parts = order.parts
    out = []
    for no, slots in enumerate(parts, start=1):
        extra = order.extra_minutes if no == len(parts) else 0
        work = sum(_minutes(b) - _minutes(a) for a, b in slots) + extra
        out.append(PlanPart(
            key=f'{order.pk}:{no}', order_id=order.pk, date=order.date, start=_minutes(slots[0][0]),
            end=_minutes(slots[-1][1]) + extra, work_minutes=work, venue_id=order.venue_id, venue_name=order.venue.name,
            venue_difficulty=order.venue.difficulty, extra_minutes=extra, part_no=no, parts_total=len(parts)))
    return out


@dataclass
class PlanningData:
    date_from: date
    date_to: date
    parts: list[PlanPart] = field(default_factory=list)
    staff: list[PlanStaff] = field(default_factory=list)
    fixed: list[tuple[int, PlanPart]] = field(default_factory=list)
    familiarity: dict[tuple[int, int], int] = field(default_factory=dict)
    week_load: dict[tuple[int, tuple[int, int]], int] = field(default_factory=dict)   # заказы недели вне периода (из таблиц)
    routes: dict[tuple[int, int], int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    orders_planned: int = 0
    venue_names: dict[int, str] = field(default_factory=dict)

    def travel(self, a: int, b: int) -> int | None:
        return self.routes.get((a, b))


def route_minutes() -> dict[tuple[int, int], int]:
    """Время в пути между центрами: минимум по вариантам маршрута для каждой направленной пары"""
    return {(row['from_venue_id'], row['to_venue_id']): row['m']
            for row in Route.objects.values('from_venue_id', 'to_venue_id').annotate(m=Min('duration_min'))}


def fixed_parts(date_from: date, date_to: date, staff_ids: list[int]) -> tuple[list[tuple[int, PlanPart]], int]:
    """Заказы периода, у которых исполнитель уже указан в таблице: (staff_id, часть) для нужных сотрудников и число заказов
    с исполнителем, которого не удалось определить (занятость неизвестна).

    Один исполнитель (`photographer`) занимает все части заказа. Заказ, который снимают несколько фотографов («Роман + Лиза»),
    хранит их в `photographers`: в ячейке не сказано, кто какую часть снимает, поэтому каждый занят во всех частях, кроме тех
    случаев, когда расчёт сам разделил заказ (применённые назначения точно говорят, чья какая часть). Нужно, чтобы участника
    заказа не поставили на другой заказ в то же время; в перерыве между частями он остаётся свободным."""
    out: list[tuple[int, PlanPart]] = []
    base = PhotoOrder.objects.filter(date__range=(date_from, date_to), status=PhotoOrder.STATUS_ASSIGNED).select_related('venue')
    for order in base.filter(photographer_id__in=staff_ids):
        out.extend((order.photographer_id, part) for part in order_parts(order))
    nameless = {o.pk: o for o in base.filter(photographer__isnull=True).prefetch_related('photographers')}
    applied: dict[int, dict[int, int]] = defaultdict(dict)        # заказ -> номер части -> сотрудник по применённым расчётам
    latest: dict[tuple[int, int], Assignment] = {}
    for a in (Assignment.objects.filter(order_id__in=nameless, staff__isnull=False, sheet_status__in=('written', 'already'))
              .select_related('plan').order_by('plan__created_at', 'pk')):
        latest[(a.order_id, a.part_no)] = a      # последний применённый расчёт перекрывает прежние
    for (order_id, part_no), a in latest.items():
        applied[order_id][part_no] = a.staff_id
    known: set[int] = set()
    for order_id, order in nameless.items():
        parts = order_parts(order)
        members = {s.pk for s in order.photographers.all()}
        if members:                      # кто снимает - по ячейке; чья часть - по расчёту, если он есть
            known.add(order_id)
            for staff_id in members & set(staff_ids):
                own = [parts[n - 1] for n, sid in applied[order_id].items() if sid == staff_id and 0 < n <= len(parts)]
                out.extend((staff_id, part) for part in (own or parts))
        elif order_id in applied:        # имён в ячейке не разобрано, но расчёт этого заказа применялся
            known.add(order_id)
            out.extend((sid, parts[n - 1]) for n, sid in applied[order_id].items() if sid in staff_ids and 0 < n <= len(parts))
    return out, len(set(nameless) - known)


def week_bounds(date_from: date, date_to: date) -> tuple[date, date]:
    """Понедельник первой и воскресенье последней недели (пн-вс), которых касается период"""
    return date_from - timedelta(days=date_from.weekday()), date_to + timedelta(days=6 - date_to.weekday())


def week_load(date_from: date, date_to: date, staff_ids: list[int]) -> dict[tuple[int, tuple[int, int]], int]:
    """Нагрузка недель, которых касается период, из заказов в таблицах («Заказы»): {(сотрудник, (год, ISO-неделя)): число заказов}
    на дни этих недель ВНЕ периода. Распределение обычно запускают на один день вперёд, и по нему одному нагрузку недели не узнать:
    значит, берём то, что уже назначено на остальные дни недели - и раньше (уже снято или снимается), и позже. Заказы внутри
    периода сюда не входят (их планировщик видит сам, и они не должны считаться дважды). Считаются заказы со статусом «Назначен»:
    один исполнитель в `photographer`, несколько - в `photographers` (каждому засчитывается заказ целиком)."""
    start, end = week_bounds(date_from, date_to)
    outside = Q(date__lt=date_from) | Q(date__gt=date_to)
    counts: Counter = Counter()
    base = PhotoOrder.objects.filter(date__range=(start, end), status=PhotoOrder.STATUS_ASSIGNED).filter(outside)
    for staff_id, day in base.filter(photographer_id__in=staff_ids).values_list('photographer_id', 'date'):
        counts[(staff_id, day.isocalendar()[:2])] += 1
    members = PhotoOrder.photographers.through.objects.filter(
        staff_id__in=staff_ids, photoorder__date__range=(start, end), photoorder__status=PhotoOrder.STATUS_ASSIGNED
    ).filter(Q(photoorder__date__lt=date_from) | Q(photoorder__date__gt=date_to))
    for staff_id, day in members.values_list('staff_id', 'photoorder__date'):
        counts[(staff_id, day.isocalendar()[:2])] += 1
    return dict(counts)


def collect(date_from: date, date_to: date) -> PlanningData:
    data = PlanningData(date_from, date_to)

    # заказы
    base = PhotoOrder.objects.filter(date__range=(date_from, date_to)).select_related('venue')
    open_orders = list(base.filter(status=PhotoOrder.STATUS_OPEN))
    planned = [o for o in open_orders if o.venue.is_active]
    if len(planned) < len(open_orders):
        data.warnings.append(f'Заказов в центрах, не участвующих в планировании: {len(open_orders) - len(planned)} - они пропущены')
    needs_fix = base.filter(status=PhotoOrder.STATUS_NEEDS_FIX).count()
    if needs_fix:
        data.warnings.append(f'Заказов, требующих ручной правки: {needs_fix} - они в расчёт не входят')
    for order in planned:
        parts = order_parts(order)
        if not parts:
            data.warnings.append(f'Заказ {order} без распознанного времени пропущен')
            continue
        data.parts.extend(parts)
        data.orders_planned += 1
    plan_dates = {p.date for p in data.parts}

    # сотрудники
    outbound = list(Staff.objects.filter(staff_type='Выездной', dism_status='Работает').order_by('id'))
    eligible = []
    for s in outbound:
        if s.skill_score is None or s.max_orders_per_day is None:
            data.warnings.append(f'{s}: не заданы навык или лимит заказов - в расчёте не участвует')
        else:
            eligible.append(s)
    # график выходов и отпусков: отпуск, отгул и больничный закрывают день; пустой статус, «Работает» и отсутствие записи - ставить можно
    # график берём за целые недели: по нему считаются доступные дни недели (ёмкость нагрузки), даже если период - один день
    week_start, week_end = week_bounds(date_from, date_to)
    availability: dict[int, dict[date, object]] = defaultdict(dict)
    for rec in WorkVacSchedule.objects.filter(staff__in=eligible, date__range=(week_start, week_end)).select_related('staff'):
        avail = day_availability(rec.staff_wrk_status, rec.time_availiable)
        availability[rec.staff_id][rec.date] = avail
        if not avail.ok and rec.date in plan_dates:
            data.warnings.append(f'{rec.staff} {rec.date:%d.%m}: время доступности «{avail.raw}» не разобрано - в этот день не назначается')
    data.staff = [PlanStaff(id=s.id, name=str(s), skill=s.skill_score, max_orders=s.max_orders_per_day,
                            availability=availability.get(s.id, {})) for s in eligible]
    staff_ids = [s.id for s in eligible]

    # назначенное вручную в таблицах: занимает время и лимит, но не меняется
    data.fixed, unknown = fixed_parts(date_from, date_to, staff_ids)
    if unknown:
        data.warnings.append(f'У {unknown} заказов в таблице указан исполнитель, не сопоставленный с сотрудником (экран «Сопоставления») - '
                             f'его занятость не учтена')

    # знакомство с центром: прежние заказы в таблицах и смены на фототочке центра
    familiarity: Counter = Counter()
    for row in (PhotoOrder.objects.filter(status=PhotoOrder.STATUS_ASSIGNED, photographer_id__in=staff_ids, date__lt=date_from)
                .values('photographer_id', 'venue_id').annotate(n=Count('id'))):
        familiarity[(row['photographer_id'], row['venue_id'])] += row['n']
    for row in (PhotoOrder.photographers.through.objects
                .filter(staff_id__in=staff_ids, photoorder__status=PhotoOrder.STATUS_ASSIGNED, photoorder__date__lt=date_from)
                .values('staff_id', 'photoorder__venue_id').annotate(n=Count('id'))):      # заказы, которые снимали вдвоём
        familiarity[(row['staff_id'], row['photoorder__venue_id'])] += row['n']
    venues_by_store = defaultdict(list)
    for venue_id, store_id in Venue.objects.filter(store__isnull=False).values_list('id', 'store_id'):
        venues_by_store[store_id].append(venue_id)
    since = date_from - timedelta(days=SCHEDULE_HISTORY_DAYS)
    for row in (Schedule.objects.filter(staff_id__in=staff_ids, store_id__in=venues_by_store, date__gte=since, date__lt=date_from)
                .values('staff_id', 'store_id').annotate(n=Count('id'))):
        for venue_id in venues_by_store[row['store_id']]:
            familiarity[(row['staff_id'], venue_id)] += row['n']
    data.familiarity = dict(familiarity)
    data.week_load = week_load(date_from, date_to, staff_ids)

    # маршруты: минимум по вариантам пары
    data.routes = route_minutes()
    data.venue_names = dict(Venue.objects.values_list('id', 'name'))
    return data


def _fixed_display(data: PlanningData) -> list[dict]:
    names = {s.id: s.name for s in data.staff}
    rows = [{'staff': names[sid], 'staff_id': sid, 'date': p.date.isoformat(), 'start': _hm(p.start), 'end': _hm(p.end),
             'venue': p.venue_name, 'order_id': p.order_id, 'part': f'{p.part_no}/{p.parts_total}'} for sid, p in data.fixed]
    return sorted(rows, key=lambda r: (r['date'], r['start'], r['staff_id']))


@atomic
def run_plan(user, date_from: date, date_to: date, config: PlannerConfig = PlannerConfig()) -> PlanRun:
    """Рассчитывает распределение за период и сохраняет черновик. В Schedule и таблицы ничего не пишет."""
    data = collect(date_from, date_to)
    result = plan(data.parts, data.staff, data.fixed, data.travel, data.familiarity, date_from, date_to, config,
                  week_load=data.week_load)
    for a, b in result.defaulted_routes:
        data.warnings.append(f'Нет маршрута «{data.venue_names.get(a, a)}» -> «{data.venue_names.get(b, b)}»: '
                             f'принято {config.default_travel_min} мин')

    assigned = result.assigned
    unassigned = result.unassigned
    summary = {
        'orders': data.orders_planned, 'parts': len(result.entries), 'assigned': len(assigned), 'unassigned': len(unassigned),
        'orders_unassigned': len({e.part.order_id for e in unassigned}), 'fixed_orders': len({p.order_id for _, p in data.fixed}),
        'staff': len(data.staff), 'total_cost': round(result.total_cost, 1), 'passes': result.passes,
    }
    run = PlanRun.objects.create(date_from=date_from, date_to=date_to, created_by=user if getattr(user, 'pk', None) else None,
                                 config=config_to_dict(config), summary=summary, warnings=data.warnings, fixed=_fixed_display(data))
    Assignment.objects.bulk_create([
        Assignment(plan=run, order_id=e.part.order_id, part_no=e.part.part_no, parts_total=e.part.parts_total, date=e.part.date,
                   start_min=e.part.start, end_min=e.part.end, staff_id=e.staff_id, auto_staff_id=e.staff_id, need=round(e.need, 2),
                   cost=round(e.cost, 2),
                   candidates=e.candidates, reasons=e.reasons, alternatives=e.alternatives, rejected=e.rejected)
        for e in result.entries])
    ImplEvents.objects.create(
        event_type='Schauto_Plan', status='Успешно', solved='Да',
        event_message=(f'Расчёт распределения выездных {date_from:%d.%m.%Y}-{date_to:%d.%m.%Y}: частей заказов {summary["parts"]}, '
                       f'распределено {summary["assigned"]}, не распределено {summary["unassigned"]}, '
                       f'фотографов {summary["staff"]}, предупреждений {len(data.warnings)}'))
    return run
