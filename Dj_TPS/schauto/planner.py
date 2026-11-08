"""Распределение заказов (частей заказов) по выездным фотографам. Чистая функция без Django и сети.

Единица назначения - часть заказа (`PlanPart`): интервалы заказа, разделённые перерывом меньше SPLIT_GAP_MINUTES, остаются вместе,
а при перерыве от часа части можно отдать разным фотографам. Заказ с одним интервалом - одна часть.

Жёсткие ограничения (нарушать нельзя, иначе заказ остаётся нераспределённым и в отчёте видна причина по каждому фотографу):
доступность в день (отпуск/отгул/больничный и окна времени), лимит заказов в день, отсутствие пересечений по времени и достаточный
промежуток между заказами в разных центрах: дорога по маршрутам (минимум по вариантам пары) + буфер.

Мягкие (штрафы, меньше - лучше): соответствие навыка сложности заказа (сложность центра + длительность + продление), знакомство
фотографа с центром, равномерность нагрузки за неделю (пн-вс) с учётом доступных дней и навыка, время в дороге, лишнее дробление заказа.
Нагрузка недели считается по ВСЕЙ неделе, а не по периоду расчёта: распределение обычно запускают на один день вперёд, и сколько
заказов у фотографа на неделе, расчёт сам знать не может. Поэтому заказы недели вне периода (уже назначенные в таблицах) приходят
извне (`week_load`), а доступные дни недели берутся из графика выходов за всю неделю.

Метод: сначала самые стеснённые части (меньше всего подходящих фотографов), каждая - к фотографу с минимальным приростом штрафа;
затем проход локальных улучшений (перенос и обмен частей) и попытки пристроить оставшиеся (в т.ч. вытеснением чужой части).
Всё детерминировано: одни и те же входные данные дают тот же план.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Callable, Iterable, Mapping

from .availability import ALL_DAY, Availability

EPS = 1e-9


@dataclass(frozen=True)
class PlannerConfig:
    buffer_min: int = 15              # запас между заказом и следующей поездкой/началом
    default_travel_min: int = 90      # когда для пары центров нет маршрута: консервативное значение, помечается в плане
    # сложность части заказа = сложность центра + надбавка за длительность и продление
    need_per_extra_hour: float = 1.0  # +баллов за каждый час сверх первого
    need_duration_cap: float = 2.0    # потолок надбавки за длительность
    need_extra: float = 0.5           # надбавка за продление
    # штрафы
    # Навык - приоритет: чем он выше, тем более сложные и многочисленные заказы. Поэтому избыток навыка почти не штрафуется
    # (лишь чуть бережёт сильных для тяжёлых заказов), а нехватка навыка штрафуется сильно
    w_skill_over: float = 0.3         # навык выше сложности, за балл
    w_skill_under: float = 4.5        # навык ниже сложности, за балл
    skill_load_power: float = 2.0     # доля нагрузки пропорциональна навыку в этой степени (выше навык - больше заказов)
    w_unfamiliar: float = 2.0         # в этом центре фотограф раньше не работал
    w_load: float = 100.0             # равномерность: (заказов за неделю / (типичная дневная нагрузка * доступные дни недели * вес навыка))^2
    load_orders_per_day: float = 2.0  # типичная дневная нагрузка для ёмкости недели; дневной лимит фотографа - только потолок
    w_travel: float = 0.05            # за минуту дороги между заказами
    w_split: float = 6.0              # за каждого дополнительного исполнителя одного заказа
    max_passes: int = 30              # потолок проходов локальных улучшений


@dataclass(frozen=True)
class PlanPart:
    key: str                  # "<id заказа>:<номер части>"
    order_id: int
    date: date
    start: int                # минуты от полуночи
    end: int                  # с учётом продления (оно относится к концу последней части)
    work_minutes: int
    venue_id: int
    venue_name: str
    venue_difficulty: int
    extra_minutes: int = 0
    part_no: int = 1
    parts_total: int = 1

    @property
    def title(self) -> str:
        return f'{self.venue_name} {_hm(self.start)}-{_hm(self.end)}'


@dataclass(frozen=True)
class PlanStaff:
    id: int
    name: str
    skill: int
    max_orders: int
    availability: Mapping[date, Availability] = field(default_factory=dict)  # нет даты - свободен весь день

    def avail(self, day: date) -> Availability:
        return self.availability.get(day, ALL_DAY)


@dataclass(frozen=True)
class Rejection:
    code: str   # blocked / unparsed / window / limit / overlap / gap
    text: str
    # только для gap (фотограф не успевает доехать): ключи двух соседних частей по времени, сколько минут нужно и сколько есть.
    # По ним проверку можно подтвердить вручную: одна пара - одно подтверждение, с какой бы из двух частей её ни открыли
    pair: tuple[str, str] | None = None
    need: int = 0
    gap: int = 0

    @property
    def shortfall(self) -> int:
        return max(0, self.need - self.gap)


@dataclass
class PlanEntry:
    part: PlanPart
    staff_id: int | None
    need: float
    cost: float = 0.0                                        # вклад части в штраф плана
    breakdown: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)         # почему именно этот исполнитель
    alternatives: list[str] = field(default_factory=list)    # кто был бы следующим и чем хуже
    rejected: list[str] = field(default_factory=list)        # кто не подходит и почему
    candidates: int = 0                                      # сколько фотографов подходило


@dataclass
class PlanResult:
    entries: list[PlanEntry]
    total_cost: float
    defaulted_routes: list[tuple[int, int]]   # пары центров без маршрута (принято значение по умолчанию)
    passes: int = 0

    @property
    def assigned(self) -> list[PlanEntry]:
        return [e for e in self.entries if e.staff_id is not None]

    @property
    def unassigned(self) -> list[PlanEntry]:
        return [e for e in self.entries if e.staff_id is None]


def _hm(minutes: int) -> str:
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def _order_key(part: PlanPart):
    return part.start, part.end, part.key


def part_need(part: PlanPart, cfg: PlannerConfig = PlannerConfig()) -> float:
    """Требуемый уровень навыка для части заказа (1-10)"""
    extra_hours = max(0, part.work_minutes - 60) / 60
    need = part.venue_difficulty + min(cfg.need_duration_cap, extra_hours * cfg.need_per_extra_hour)
    if part.extra_minutes:
        need += cfg.need_extra
    return min(10.0, max(1.0, need))


def sequence_problems(part: PlanPart, items: list[PlanPart], travel_minutes: Callable[[PlanPart, PlanPart], int],
                      buffer_min: int) -> list[Rejection]:
    """Все причины, по которым часть несовместима по времени с остальными заказами фотографа в этот день (items - без самой части).

    Пересечение проверяется со всеми заказами дня (ручные назначения могут налезать друг на друга), запас на дорогу
    (дорога + буфер) - с ближайшими: последним закончившимся и первым следующим. Части одного заказа запаса не требуют.
    Есть пересечение - возвращаются только пересечения; иначе - нехватка времени до предыдущего и до следующего заказа."""
    def needed(a: PlanPart, b: PlanPart) -> int:
        return 0 if a.order_id == b.order_id else travel_minutes(a, b) + buffer_min

    def too_close(first: PlanPart, second: PlanPart, gap: int, need: int, before: bool) -> Rejection:
        travel = travel_minutes(first, second)
        if before:
            text = f'не успевает после «{first.title}»: нужно {need} мин (дорога {travel} + запас {buffer_min}), есть {gap}'
        else:
            text = (f'не успеет к «{second.title}» после этого заказа: нужно {need} мин (дорога {travel} + запас '
                    f'{buffer_min}), есть {gap}')
        return Rejection('gap', text, pair=(first.key, second.key), need=need, gap=gap)

    overlaps = [Rejection('overlap', f'занят в это время: {x.title}') for x in items if x.start < part.end and part.start < x.end]
    if overlaps:
        return overlaps
    prev = nxt = None
    for x in items:
        if x.end <= part.start:
            if prev is None or x.end > prev.end:
                prev = x
        elif nxt is None or x.start < nxt.start:
            nxt = x
    problems = []
    if prev is not None and part.start - prev.end < needed(prev, part):
        problems.append(too_close(prev, part, part.start - prev.end, needed(prev, part), before=True))
    if nxt is not None and nxt.start - part.end < needed(part, nxt):
        problems.append(too_close(part, nxt, nxt.start - part.end, needed(part, nxt), before=False))
    return problems


def sequence_problem(part: PlanPart, items: list[PlanPart], travel_minutes: Callable[[PlanPart, PlanPart], int],
                     buffer_min: int) -> Rejection | None:
    """Первая причина из `sequence_problems` (для солвера достаточно одной) или None, если часть совместима"""
    problems = sequence_problems(part, items, travel_minutes, buffer_min)
    return problems[0] if problems else None


def find_problems(planned: Iterable[tuple[int, PlanPart]], fixed: Iterable[tuple[int, PlanPart]],
                  travel: Callable[[int, int], int | None] | None = None,
                  config: PlannerConfig = PlannerConfig()) -> dict[str, list[Rejection]]:
    """Проверка уже готового распределения: ключ части -> все причины (пересечение или фотограф не успевает доехать).
    Конфликты между собой у ручных назначений (fixed) не проверяются - это входные данные, не решение планировщика."""
    travel = travel or (lambda a, b: None)

    def minutes(a: PlanPart, b: PlanPart) -> int:
        if a.venue_id == b.venue_id:
            return 0
        m = travel(a.venue_id, b.venue_id)
        return config.default_travel_min if m is None else m

    days: dict[tuple[int, date], list[PlanPart]] = defaultdict(list)
    for sid, part in list(planned) + list(fixed):
        days[(sid, part.date)].append(part)
    planned_keys = {(sid, part.key) for sid, part in planned}
    problems: dict[str, list[Rejection]] = {}
    for (sid, _day), items in days.items():
        for part in items:
            if (sid, part.key) not in planned_keys:
                continue
            found = sequence_problems(part, [x for x in items if x is not part], minutes, config.buffer_min)
            if found:
                problems[part.key] = found
    return problems


def find_conflicts(planned: Iterable[tuple[int, PlanPart]], fixed: Iterable[tuple[int, PlanPart]],
                   travel: Callable[[int, int], int | None] | None = None,
                   config: PlannerConfig = PlannerConfig()) -> dict[str, str]:
    """То же, что `find_problems`, но ключ части -> текст первой причины"""
    return {key: found[0].text for key, found in find_problems(planned, fixed, travel, config).items()}


class Planner:
    def __init__(self, parts: Iterable[PlanPart], staff: Iterable[PlanStaff],
                 fixed: Iterable[tuple[int, PlanPart]] = (),
                 travel: Callable[[int, int], int | None] | None = None,
                 familiarity: Mapping[tuple[int, int], int] | None = None,
                 date_from: date | None = None, date_to: date | None = None,
                 config: PlannerConfig = PlannerConfig(),
                 week_load: Mapping[tuple[int, tuple[int, int]], int] | None = None):
        """parts - что распределяем; fixed - уже назначенное вручную (staff_id, часть): не меняется, но занимает время и лимит;
        travel(from_venue, to_venue) - минуты по лучшему варианту маршрута или None; familiarity[(staff_id, venue_id)] - сколько
        раз фотограф уже работал в центре; date_from/date_to - период плана (для оценки загрузки недели);
        week_load[(staff_id, (год, номер ISO-недели))] - сколько заказов у фотографа на этой неделе ВНЕ периода плана (уже назначены
        в таблицах на другие дни): к заказам внутри периода они добавляются, чтобы нагрузка недели была настоящей, а не обрезанной
        периодом."""
        self.cfg = config
        self.staff = {s.id: s for s in sorted(staff, key=lambda s: s.id)}
        self.parts = sorted(parts, key=lambda p: p.key)
        self.by_key = {p.key: p for p in self.parts}
        self.order_parts: dict[int, list[str]] = defaultdict(list)
        for p in self.parts:
            self.order_parts[p.order_id].append(p.key)
        self.familiarity = familiarity or {}
        self.week_load = week_load or {}
        self._travel_fn = travel or (lambda a, b: None)
        self._travel_cache: dict[tuple[int, int], int | None] = {}
        self.defaulted: set[tuple[int, int]] = set()

        self.items: dict[int, dict[date, list[PlanPart]]] = {sid: defaultdict(list) for sid in self.staff}  # фотограф -> день -> части по времени
        self.owner: dict[str, int | None] = {p.key: None for p in self.parts}
        self.fixed_keys: set[str] = set()
        all_days = [p.date for p in self.parts]
        for staff_id, part in fixed:
            if staff_id in self.staff:
                self._insert(staff_id, part)
                self.fixed_keys.add(part.key)
                all_days.append(part.date)
        self.date_from = date_from or (min(all_days) if all_days else date.today())
        self.date_to = date_to or (max(all_days) if all_days else self.date_from)
        # доступные дни считаем по целым неделям (пн-вс), затронутым периодом: расчёт на один день тоже должен знать,
        # сколько дней фотограф доступен на этой неделе (отпуск/отгул/больничный не считаются)
        self._week_days: dict[tuple[int, tuple[int, int]], int] = {}
        first = self.date_from - timedelta(days=self.date_from.weekday())
        last = self.date_to + timedelta(days=6 - self.date_to.weekday())
        self._weeks = {(first + timedelta(days=i)).isocalendar()[:2] for i in range((last - first).days + 1)}
        for sid, s in self.staff.items():
            day = first
            while day <= last:
                if s.avail(day).windows:
                    self._week_days[(sid, day.isocalendar()[:2])] = self._week_days.get((sid, day.isocalendar()[:2]), 0) + 1
                day += timedelta(days=1)
        # внешняя нагрузка нужна только для недель периода (остальные на выбор не влияют)
        self._outside_weeks: dict[int, set[tuple[int, int]]] = defaultdict(set)
        for (sid, week), n in self.week_load.items():
            if n and week in self._weeks and sid in self.staff:
                self._outside_weeks[sid].add(week)
        self.need = {p.key: part_need(p, config) for p in self.parts}
        powers = {sid: s.skill ** config.skill_load_power for sid, s in self.staff.items()}
        mean_power = sum(powers.values()) / len(powers) if powers else 1.0
        self._weight = {sid: power / mean_power for sid, power in powers.items()}  # средний вес 1: сильные берут больше

    # --- состояние ---------------------------------------------------------------------------------------------------

    def _insert(self, sid: int, part: PlanPart):
        lst = self.items[sid][part.date]
        lst.append(part)
        lst.sort(key=_order_key)

    def _remove(self, sid: int, part: PlanPart):
        self.items[sid][part.date].remove(part)

    def _place(self, part: PlanPart, sid: int | None):
        """Переносит часть к фотографу (None - снимает назначение)"""
        old = self.owner[part.key]
        if old is not None:
            self._remove(old, part)
        self.owner[part.key] = sid
        if sid is not None:
            self._insert(sid, part)

    # --- маршруты -----------------------------------------------------------------------------------------------------

    def _travel_minutes(self, a: PlanPart, b: PlanPart) -> int:
        if a.venue_id == b.venue_id:
            return 0
        key = (a.venue_id, b.venue_id)
        if key not in self._travel_cache:
            self._travel_cache[key] = self._travel_fn(*key)
        minutes = self._travel_cache[key]
        if minutes is None:
            self.defaulted.add(key)
            return self.cfg.default_travel_min
        return minutes

    # --- жёсткие ограничения ------------------------------------------------------------------------------------------

    def _reject(self, s: PlanStaff, part: PlanPart, items: list[PlanPart]) -> Rejection | None:
        """Почему часть нельзя отдать фотографу s (items - его части в этот день без `part`); None - можно"""
        a = s.avail(part.date)
        if a.blocked:
            return Rejection('blocked', a.blocked.lower())
        if not a.ok:
            return Rejection('unparsed', f'время доступности не разобрано: «{a.raw}»')
        if not a.covers(part.start, part.end):
            return Rejection('window', f'доступен {a.describe()}, а заказ {_hm(part.start)}-{_hm(part.end)}')
        orders = {i.order_id for i in items}
        if part.order_id not in orders and len(orders) + 1 > s.max_orders:
            return Rejection('limit', f'уже {len(orders)} из {s.max_orders} заказов в этот день')
        return sequence_problem(part, items, self._travel_minutes, self.cfg.buffer_min)

    def _can_take(self, s: PlanStaff, part: PlanPart) -> bool:
        return self._reject(s, part, self.items[s.id][part.date]) is None

    # --- штрафы -------------------------------------------------------------------------------------------------------

    def _skill_cost(self, s: PlanStaff, part: PlanPart) -> float:
        diff = s.skill - self.need[part.key]
        return diff * self.cfg.w_skill_over if diff >= 0 else -diff * self.cfg.w_skill_under

    def _unfamiliar_cost(self, s: PlanStaff, part: PlanPart) -> float:
        return 0.0 if self.familiarity.get((s.id, part.venue_id), 0) > 0 else self.cfg.w_unfamiliar

    def _travel_cost(self, sid: int) -> float:
        total = 0.0
        for lst in self.items[sid].values():
            for a, b in zip(lst, lst[1:]):
                if a.order_id != b.order_id:
                    total += self._travel_minutes(a, b)
        return total * self.cfg.w_travel

    def _week_orders(self, sid: int) -> dict[tuple[int, int], set[int]]:
        weeks: dict[tuple[int, int], set[int]] = defaultdict(set)
        for day, lst in self.items[sid].items():
            weeks[day.isocalendar()[:2]].update(p.order_id for p in lst)
        return weeks

    def _week_count(self, sid: int, week: tuple[int, int]) -> int:
        """Заказов у фотографа на неделе: внутри периода плана (расчёт и назначенное вручную) и вне периода (из таблиц)"""
        return len(self._week_orders(sid).get(week, ())) + (self.week_load.get((sid, week), 0) if week in self._weeks else 0)

    def _week_cap(self, s: PlanStaff, week: tuple[int, int]) -> float:
        """Ёмкость недели: типичная дневная нагрузка * доступные дни недели * вес по навыку. Дневной лимит фотографа сюда НЕ
        входит: это потолок (жёсткое ограничение), а не мера того, сколько человека стоит нагружать"""
        return max(1, self._week_days.get((s.id, week), 0)) * self.cfg.load_orders_per_day * self._weight[s.id]

    def _load_cost(self, sid: int) -> float:
        """Штраф нагрузки по неделям, где у фотографа есть заказы в плане или вне периода. Заказы вне периода входят в счёт недели,
        но сами не двигаются: от них зависит только то, насколько дорого добавить ему ещё один заказ (штраф растёт по квадрату,
        поэтому лишний заказ тому, у кого неделя уже загружена, обходится дороже - считается прирост, а не вся неделя заново)"""
        s = self.staff[sid]
        weeks = set(self._week_orders(sid)) | self._outside_weeks.get(sid, set())
        return sum(self.cfg.w_load * (self._week_count(sid, week) / self._week_cap(s, week)) ** 2 for week in weeks)

    def _planned(self, sid: int) -> list[PlanPart]:
        return [p for lst in self.items[sid].values() for p in lst if p.key not in self.fixed_keys]

    def _staff_breakdown(self, sid: int) -> dict[str, float]:
        s = self.staff[sid]
        planned = self._planned(sid)
        return {
            'skill': sum(self._skill_cost(s, p) for p in planned),
            'unfamiliar': sum(self._unfamiliar_cost(s, p) for p in planned),
            'travel': self._travel_cost(sid),
            'load': self._load_cost(sid),
        }

    def _staff_cost(self, sid: int) -> float:
        return sum(self._staff_breakdown(sid).values())

    def _split_cost(self, order_id: int) -> float:
        owners = {self.owner[k] for k in self.order_parts[order_id] if self.owner[k] is not None}
        return max(0, len(owners) - 1) * self.cfg.w_split

    def _local_cost(self, sids: Iterable[int], order_ids: Iterable[int]) -> float:
        return sum(self._staff_cost(s) for s in set(sids)) + sum(self._split_cost(o) for o in set(order_ids))

    def total_cost(self) -> float:
        return self._local_cost(self.staff, self.order_parts)

    # --- алгоритм -----------------------------------------------------------------------------------------------------

    def _candidates(self, part: PlanPart) -> list[PlanStaff]:
        return [s for s in self.staff.values() if self.owner[part.key] != s.id and self._can_take(s, part)]

    def _delta_move(self, part: PlanPart, new_sid: int | None) -> float:
        """Изменение штрафа при переносе части (проверку жёстких ограничений вызывающий делает сам); состояние не меняется"""
        old_sid = self.owner[part.key]
        sids = [x for x in (old_sid, new_sid) if x is not None]
        before = self._local_cost(sids, [part.order_id])
        self._place(part, new_sid)
        after = self._local_cost(sids, [part.order_id])
        self._place(part, old_sid)
        # округляем: общие слагаемые (нагрузка недели вне периода) при вычитании дают шум ~1e-14, а он не должен решать ничью
        return round(after - before, 9)

    def _greedy(self):
        def sort_key(p: PlanPart):
            return len(self._candidates(p)), -self.need[p.key], p.date, p.start, p.key

        for part in sorted(self.parts, key=sort_key):
            options = [(self._delta_move(part, s.id), -s.skill, s.id) for s in self._candidates(part)]
            if options:
                self._place(part, min(options)[2])

    def _try_relocate(self) -> bool:
        improved = False
        for part in self.parts:
            sid = self.owner[part.key]
            if sid is None:
                continue
            best = None
            for t in self._candidates(part):
                delta = self._delta_move(part, t.id)
                if delta < -EPS and (best is None or (delta, -t.skill, t.id) < best):
                    best = (delta, -t.skill, t.id)
            if best:
                self._place(part, best[2])
                improved = True
        return improved

    def _try_swap(self) -> bool:
        improved = False
        assigned = [p for p in self.parts if self.owner[p.key] is not None]
        for i, p in enumerate(assigned):
            for q in assigned[i + 1:]:
                sp, sq = self.owner[p.key], self.owner[q.key]
                if sp is None or sq is None or sp == sq or p.order_id == q.order_id:
                    continue
                if not self._swap_feasible(p, q, sp, sq):
                    continue
                before = self._local_cost([sp, sq], [p.order_id, q.order_id])
                self._place(p, sq), self._place(q, sp)
                after = self._local_cost([sp, sq], [p.order_id, q.order_id])
                if after < before - EPS:
                    improved = True
                else:
                    self._place(p, sp), self._place(q, sq)
        return improved

    def _swap_feasible(self, p: PlanPart, q: PlanPart, sp: int, sq: int) -> bool:
        """p уходит к sq, q - к sp: проверяем итоговое расписание каждого"""
        items_q = [i for i in self.items[sq][p.date] if i is not q]
        items_p = [i for i in self.items[sp][q.date] if i is not p]
        return self._reject(self.staff[sq], p, items_q) is None and self._reject(self.staff[sp], q, items_p) is None

    def _place_unassigned(self) -> bool:
        placed = False
        for part in self.parts:
            if self.owner[part.key] is not None:
                continue
            options = [(self._delta_move(part, s.id), -s.skill, s.id) for s in self._candidates(part)]
            if options:
                self._place(part, min(options)[2])
                placed = True
        return placed

    def _try_eject(self) -> bool:
        """Нераспределённая часть занимает место фотографа, а его часть переезжает к другому, если так получается пристроить обе"""
        placed = False
        for part in self.parts:
            if self.owner[part.key] is not None:
                continue
            done = False
            for s in self.staff.values():
                if done:
                    break
                for other in list(self.items[s.id][part.date]):
                    if other.key in self.fixed_keys or other.order_id == part.order_id:
                        continue
                    for t in self.staff.values():
                        if t.id == s.id or not self._can_take(t, other):
                            continue
                        self._place(other, t.id)
                        if self._can_take(s, part):
                            self._place(part, s.id)
                            placed = done = True
                            break
                        self._place(other, s.id)  # не помогло - возвращаем
                    if done:
                        break
        return placed

    def solve(self) -> PlanResult:
        self._greedy()
        passes = 0
        for passes in range(1, self.cfg.max_passes + 1):
            changed = self._try_relocate()
            changed = self._try_swap() or changed
            changed = self._place_unassigned() or changed
            changed = self._try_eject() or changed
            if not changed:
                break
        entries = [self._explain(p) for p in sorted(self.parts, key=lambda p: (p.date, p.start, p.key))]
        return PlanResult(entries, self.total_cost(), sorted(self.defaulted), passes)

    # --- объяснения ---------------------------------------------------------------------------------------------------

    def _rejections(self, part: PlanPart, skip: int | None) -> list[str]:
        out = []
        for s in self.staff.values():
            if s.id == skip:
                continue
            rej = self._reject(s, part, self.items[s.id][part.date])
            if rej:
                out.append(f'{s.name}: {rej.text}')
        return out

    def _explain(self, part: PlanPart) -> PlanEntry:
        need = self.need[part.key]
        sid = self.owner[part.key]
        entry = PlanEntry(part, sid, need)
        if sid is None:
            entry.rejected = self._rejections(part, None)
            if not self.staff:
                entry.reasons.append('нет выездных фотографов с заданными навыком и лимитом заказов')
            return entry

        s = self.staff[sid]
        diff = s.skill - need
        entry.breakdown = {'skill': self._skill_cost(s, part), 'unfamiliar': self._unfamiliar_cost(s, part)}
        parts_note = ''
        if part.parts_total > 1:
            others = sorted({self.staff[self.owner[k]].name for k in self.order_parts[part.order_id]
                             if k != part.key and self.owner[k] is not None})
            parts_note = (f'Часть {part.part_no} из {part.parts_total} заказа'
                          + (f' (остальное у: {", ".join(others)})' if others and others != [s.name] else ' (всё у одного фотографа)'))
        level = ('подходит по уровню' if abs(diff) <= 1 else
                 'навык выше сложности (запас)' if diff > 1 else 'навык ниже сложности')
        entry.reasons.append(f'Навык {s.skill}, сложность заказа {need:.1f} (центр {part.venue_difficulty}'
                             f'{", с учётом длительности" if need > part.venue_difficulty else ""}): {level}')
        seen = self.familiarity.get((s.id, part.venue_id), 0)
        entry.reasons.append(f'Уже работал в этом центре: {seen} зак.' if seen else 'В этом центре раньше не работал')
        if parts_note:
            entry.reasons.append(parts_note)
        a = s.avail(part.date)
        if not a.all_day:
            entry.reasons.append(f'Доступность на день: {a.describe()}')

        day_items = self.items[sid][part.date]
        idx = day_items.index(part)
        if idx == 0:
            entry.reasons.append('Первый заказ в этот день')
        neighbours = (('До этого', day_items[idx - 1] if idx else None, True),
                      ('Следом', day_items[idx + 1] if idx + 1 < len(day_items) else None, False))
        for label, other, before in neighbours:
            if other is None:
                continue
            first, second = (other, part) if before else (part, other)
            gap = second.start - first.end
            travel = self._travel_minutes(first, second)
            defaulted = first.venue_id != second.venue_id and (first.venue_id, second.venue_id) in self.defaulted
            fixed_mark = ' (назначен вручную)' if other.key in self.fixed_keys else ''
            if other.order_id == part.order_id:
                entry.reasons.append(f'{label} другая часть этого заказа ({other.title}), перерыв {gap} мин')
            else:
                route = f'маршрут не задан, принято {travel} мин' if defaulted else f'дорога {travel} мин'
                entry.reasons.append(f'{label}: {other.title}{fixed_mark}, {route}, '
                                     f'запас {gap - travel - self.cfg.buffer_min} мин сверх буфера')

        week = part.date.isocalendar()[:2]
        monday = part.date - timedelta(days=part.date.weekday())
        in_plan = len(self._week_orders(sid).get(week, ()))
        outside = self.week_load.get((sid, week), 0) if week in self._weeks else 0
        entry.reasons.append(
            f'Нагрузка за неделю {monday:%d.%m}-{monday + timedelta(days=6):%d.%m}: заказов {in_plan + outside} '
            f'(в периоде расчёта {in_plan}, вне него уже назначено в таблицах {outside}); расчётная ёмкость недели '
            f'≈ {self._week_cap(s, week):.1f}, дневной лимит {s.max_orders} - только жёсткий потолок')

        feasible = []
        for t in self.staff.values():
            if t.id == sid:
                continue
            if self._reject(t, part, self.items[t.id][part.date]) is None:
                feasible.append((self._delta_move(part, t.id), t))
        entry.candidates = len(feasible) + 1
        feasible.sort(key=lambda x: (round(x[0], 6), -x[1].skill, x[1].id))
        entry.alternatives = [f'{t.name}: штраф {"+" if d >= 0 else ""}{d:.1f}' for d, t in feasible[:2]]
        entry.rejected = self._rejections(part, sid)
        entry.cost = entry.breakdown['skill'] + entry.breakdown['unfamiliar']
        if feasible:
            entry.reasons.append(f'Подходило фотографов: {len(feasible) + 1}; лучшая замена - {feasible[0][1].name}')
        else:
            entry.reasons.append('Других подходящих фотографов нет')
        return entry


def plan(parts, staff, fixed=(), travel=None, familiarity=None, date_from=None, date_to=None,
         config: PlannerConfig = PlannerConfig(), week_load=None) -> PlanResult:
    return Planner(parts, staff, fixed, travel, familiarity, date_from, date_to, config, week_load).solve()


def config_to_dict(config: PlannerConfig) -> dict:
    return asdict(config)
