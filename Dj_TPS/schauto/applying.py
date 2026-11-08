"""Правка, проверка и применение распределения.

Правка: руководитель меняет исполнителей в черновике (`save_edits`).
Проверка (`validate_plan`, только база, без сети): у каждой части есть фотограф; заказ в таблице не изменился с момента расчёта;
в графике выходов у фотографа в этот день нет отпуска, отгула или больничного и время подходит; фотограф успевает между заказами
(дорога + буфер, без пересечений); дневной лимит заказов не превышен.
Проблемы двух видов. БЛОКИРУЮЩИЕ (исправляются сменой исполнителя, подтвердить нельзя): нет фотографа, заказ изменился или занят,
фотограф не работает, отпуск/отгул/больничный, время в графике не разобрано, пересечение заказов, дневной лимит. ПОДТВЕРЖДАЕМЫЕ
вручную (`Problem`): фотографу не хватает времени на дорогу и запас между заказами и заказ выходит за время из графика - обычно
на 5-10 минут, и человек знает, что он успеет. Подтверждение (`save_confirmations`) хранится в `PlanRun.confirmed` по подписи
проблемы (фотограф, части, цифры): если ситуация изменилась, подтверждение не действует и проблема возвращается. Применить можно,
когда блокирующих нет и все подтверждаемые подтверждены; подтверждённое попадает в сообщения, журнал и историю применений.
Применение (`apply_plan`): проверка -> предпроверка таблицы без записи -> запись фотографов в Google-таблицы ->
запись в график работы (`Schedule`, только для центров с фототочкой в ERP). В таблице Joki Joya фотограф, который обрабатывает фото
сам (`Staff.retouches_own`), вписывается и в «Ретушер» (пустую ячейку; чужого ретушёра и «исходники» не трогаем). В график попадают только заказы, которые удалось вписать
в таблицу, чтобы график и таблица не расходились. Повторное применение пропускает уже сделанное.
Удаление (`delete_plan`): только черновик, по которому ничего не вписано в таблицы; таблиц, графика и заказов оно не касается.
Откат (`rollback_plan`): возвращает ячейки в таблицах, удаляет созданные смены и снова открывает заказы - но только то, что безопасно:
изменённую после записи ячейку, смену с продажами/расчётом ЗП или изменённую вручную не трогает и сообщает причину.
"""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field, fields as dc_fields
from datetime import timedelta

from django.db.models import Q
from django.db.transaction import atomic
from django.utils import timezone

from tph_system.models import ImplEvents, Salary, Sales, Schedule, Staff, WorkVacSchedule

from . import sheetwrite
from .availability import day_availability
from .gsheet import SheetError
from .importer import sync_team
from .models import Assignment, PhotoOrder, PlanRun
from .parsers import PEOPLE_SEPARATOR
from .planner import PlannerConfig, find_problems
from .planning import fixed_parts, order_parts, route_minutes
from .sheetwrite import REVERT_OK_STATUSES, RevertItem, SheetItem

SCHEDULE_POSITION = 'Выездной фотограф'


def allowed_staff():
    """Кого можно ставить на заказы вручную: работающие выездные (навык и лимит для ручного выбора не нужны)"""
    return Staff.objects.filter(staff_type='Выездной', dism_status='Работает').order_by('name', 'f_name')


def _hm(minutes: int) -> str:
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def _config(run: PlanRun) -> PlannerConfig:
    known = {f.name for f in dc_fields(PlannerConfig)}
    return PlannerConfig(**{k: v for k, v in (run.config or {}).items() if k in known})


# --- правка ---------------------------------------------------------------------------------------------------------

@atomic
def save_edits(run: PlanRun, changes: dict[int, int | None]) -> int:
    """Меняет исполнителей у частей: {id назначения: id сотрудника или None}. Возвращает число изменённых.
    Уже вписанные в таблицу части не меняются; допустимы только работающие выездные."""
    if not run.editable:
        raise ValueError('Расчёт нельзя править: он уже применён или применяется')
    allowed = {s.pk: s for s in allowed_staff()}
    changes_text = []
    changed = []
    for a in run.assignments.filter(pk__in=changes).select_related('order__venue', 'staff'):
        new = changes[a.pk]
        if a.is_done or (new is not None and new not in allowed) or new == a.staff_id:
            continue
        changes_text.append(f'{a.date:%d.%m} {a.time_display} {a.order.venue}: {a.staff or "не назначен"} -> '
                            f'{allowed[new] if new else "не назначен"}')
        a.staff_id = new
        changed.append(a)
    if changed:
        Assignment.objects.bulk_update(changed, ['staff'])
        ImplEvents.objects.create(
            event_type='Schauto_Plan_Edit', status='Успешно', solved='Да',
            event_message=f'Правка распределения №{run.pk}: изменено исполнителей {len(changed)}. {"; ".join(changes_text[:15])}'[:900])
    return len(changed)


# --- проверка -------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Problem:
    """Проблема, которую руководитель может подтвердить вручную («фотограф успеет»)"""
    sig: str            # подпись: подтверждение действует, только пока она не изменилась
    text: str
    kind: str           # gap - не хватает времени на дорогу и запас; window - заказ вне времени из графика выходов
    shortfall: int      # на сколько минут не хватает


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)                  # общие блокирующие
    row_errors: dict[int, list[str]] = field(default_factory=dict)   # id назначения -> блокирующие
    row_soft: dict[int, list[Problem]] = field(default_factory=dict)       # id назначения -> можно подтвердить, не подтверждено
    row_confirmed: dict[int, list[Problem]] = field(default_factory=dict)  # id назначения -> подтверждено вручную
    warnings: list[str] = field(default_factory=list)
    row_warnings: dict[int, list[str]] = field(default_factory=dict)
    checked: int = 0                                                 # сколько частей проверено

    @staticmethod
    def _distinct(rows: dict[int, list[Problem]]) -> dict[str, Problem]:
        # одну проблему (пара заказов) видно в двух строках - считаем и подтверждаем её один раз
        return {p.sig: p for problems in rows.values() for p in problems}

    @property
    def ok(self) -> bool:
        return not self.errors and not self.row_errors and not self.row_soft

    @property
    def blocking_count(self) -> int:
        return len(self.errors) + sum(len(v) for v in self.row_errors.values())

    @property
    def unconfirmed(self) -> dict[str, Problem]:
        return self._distinct(self.row_soft)

    @property
    def confirmed(self) -> dict[str, Problem]:
        return self._distinct(self.row_confirmed)

    @property
    def error_count(self) -> int:
        """Сколько проблем мешает применению: блокирующие и ещё не подтверждённые"""
        return self.blocking_count + len(self.unconfirmed)

    def row_error(self, a: Assignment, text: str):
        self.row_errors.setdefault(a.pk, []).append(text)

    def row_soft_problem(self, a: Assignment, problem: Problem, confirmed: dict):
        bucket = self.row_confirmed if problem.sig in confirmed else self.row_soft
        bucket.setdefault(a.pk, []).append(problem)

    def row_warning(self, a: Assignment, text: str):
        self.row_warnings.setdefault(a.pk, []).append(text)


def _window_shortfall(avail, start: int, end: int) -> int:
    """На сколько минут заказ выходит за ближайшее время из графика выходов"""
    if not avail.windows:
        return end - start
    return min(max(0, w0 - start) + max(0, end - w1) for w0, w1 in avail.windows)


def validate_plan(run: PlanRun) -> Validation:
    """Проверка по текущему состоянию базы (не по снимку на момент расчёта): график и заказы могли измениться"""
    result = Validation()
    confirmed = run.confirmed or {}
    assignments = list(run.assignments.select_related('order__venue__store', 'staff', 'auto_staff'))
    pending = [a for a in assignments if not a.is_done]
    result.checked = len(pending)
    if not pending:
        result.errors.append('Нечего применять: все части уже вписаны в таблицу')
        return result

    cfg = _config(run)
    staff_ids = {a.staff_id for a in pending if a.staff_id}
    records = {(r.staff_id, r.date): r for r in WorkVacSchedule.objects.filter(
        staff_id__in=staff_ids, date__gte=run.date_from, date__lte=run.date_to)}
    valid_staff = {s.pk for s in allowed_staff().filter(pk__in=staff_ids)}

    planned = []        # (staff_id, часть) по текущим данным заказов
    by_key: dict[str, Assignment] = {}
    for a in pending:
        if a.staff_id is None:
            result.row_error(a, 'не назначен фотограф')
            continue
        order = a.order
        if order.status != PhotoOrder.STATUS_OPEN:
            result.row_error(a, f'заказ уже не ждёт исполнителя (статус «{order.get_status_display()}»): пересчитайте распределение')
            continue
        parts = order_parts(order)
        part = parts[a.part_no - 1] if 0 < a.part_no <= len(parts) else None
        if part is None or (part.start, part.end, part.date) != (a.start_min, a.end_min, a.date):
            result.row_error(a, 'время или дата заказа в таблице изменились после расчёта: пересчитайте распределение')
            continue
        if a.staff_id not in valid_staff:
            result.row_error(a, f'{a.staff}: не работает или не выездной фотограф')
            continue
        record = records.get((a.staff_id, a.date))
        avail = day_availability(record.staff_wrk_status if record else None, record.time_availiable if record else None)
        if avail.blocked:
            result.row_error(a, f'{a.staff} не работает в этот день: в графике выходов на {a.date:%d.%m} стоит «{avail.blocked}»')
        elif not avail.ok:
            result.row_error(a, f'{a.staff}: время в графике выходов не разобрано («{avail.raw}»)')
        elif not avail.covers(part.start, part.end):
            shortfall = _window_shortfall(avail, part.start, part.end)
            raw_hash = hashlib.md5((avail.raw or '').encode()).hexdigest()[:8]
            result.row_soft_problem(a, Problem(
                sig=f'window|{a.staff_id}|{a.date.isoformat()}|{part.start}-{part.end}|{raw_hash}', kind='window', shortfall=shortfall,
                text=f'{a.staff}: по графику доступен {avail.describe()}, а заказ {a.time_display} (выходит за это время на {shortfall} мин)'),
                confirmed)
        planned.append((a.staff_id, part))
        by_key[part.key] = a

    # успевает ли фотограф: сравниваем с остальными заказами дня (в т.ч. назначенными вручную и уже вписанными)
    fixed, _ = fixed_parts(run.date_from, run.date_to, list(staff_ids))
    routes = route_minutes()
    for key, rejections in find_problems(planned, fixed, lambda x, y: routes.get((x, y)), cfg).items():
        a = by_key[key]
        for r in rejections:
            if r.code == 'gap':      # не хватает минут на дорогу и запас: решает человек, он знает, успеет ли фотограф
                result.row_soft_problem(a, Problem(
                    sig=f'gap|{a.staff_id}|{r.pair[0]}|{r.pair[1]}|{r.need}|{r.gap}', kind='gap', shortfall=r.shortfall,
                    text=f'{a.staff}: {r.text} - не хватает {r.shortfall} мин'), confirmed)
            else:                    # пересечение заказов подтвердить нельзя: в двух местах сразу быть невозможно
                result.row_error(a, f'{a.staff}: {r.text}')

    # лимит заказов в день (с учётом назначенных вручную) - блокирующая проверка
    per_day: dict[tuple[int, object], set[int]] = defaultdict(set)
    for sid, part in planned + list(fixed):
        per_day[(sid, part.date)].add(part.order_id)
    limits = {s.pk: s.max_orders_per_day for s in Staff.objects.filter(pk__in=staff_ids)}
    for a in pending:
        if a.staff_id and limits.get(a.staff_id) and len(per_day[(a.staff_id, a.date)]) > limits[a.staff_id]:
            result.row_error(a, f'{a.staff}: на {a.date:%d.%m} {len(per_day[(a.staff_id, a.date)])} заказов при лимите {limits[a.staff_id]} в день')

    # заказ, разделённый между фотографами: в таблице одна ячейка
    owners: dict[int, set[int]] = defaultdict(set)
    for a in assignments:
        if a.staff_id:
            owners[a.order_id].add(a.staff_id)
    for a in pending:
        if len(owners[a.order_id]) > 1:
            names = ', '.join(sorted({str(x.staff) for x in assignments if x.order_id == a.order_id and x.staff}))
            result.row_warning(a, f'заказ разделён между фотографами ({names}): в ячейку «Фотограф» будут вписаны оба имени')
    return result


# --- подтверждение проблем вручную ----------------------------------------------------------------------------------------

@dataclass
class ConfirmResult:
    confirmed: int = 0       # подтверждено сейчас
    revoked: int = 0         # подтверждение снято


@atomic
def save_confirmations(run: PlanRun, user, *, shown=(), ticked=(), upto: int | None = None) -> ConfirmResult:
    """Сохраняет подтверждения проблем из формы. shown - подписи проблем, которые были на экране; ticked - те из них, что
    отмечены («Успеет, подтверждаю»): показанная, но не отмеченная проблема теряет подтверждение. upto - подтвердить сразу все
    подтверждаемые проблемы, где не хватает не больше этого числа минут. Принимаются только подписи, которые сейчас действительно
    являются подтверждаемыми проблемами этого расчёта (блокирующие подтвердить нельзя, чужие и устаревшие подписи игнорируются)."""
    if not run.editable:
        raise ValueError('Расчёт нельзя править: он уже применён или применяется')
    check = validate_plan(run)
    current = {**check.unconfirmed, **check.confirmed}
    stored = dict(run.confirmed or {})
    shown, ticked = set(shown), set(ticked)
    revoked = [sig for sig in shown if sig in current and sig in stored and sig not in ticked]
    wanted = {sig for sig in ticked if sig in current}
    if upto is not None:
        wanted |= {sig for sig, problem in current.items() if problem.shortfall <= upto}
    added = [sig for sig in sorted(wanted) if sig not in stored]
    if not added and not revoked:
        return ConfirmResult()
    now = timezone.localtime().strftime('%d.%m.%Y %H:%M')
    who = str(user) if getattr(user, 'pk', None) else ''
    for sig in added:
        stored[sig] = {'text': current[sig].text, 'by': who, 'at': now}
    for sig in revoked:
        stored.pop(sig, None)
    PlanRun.objects.filter(pk=run.pk).update(confirmed=stored)
    run.confirmed = stored
    parts = []
    if added:
        parts.append(f'подтверждено вручную проблем: {len(added)} ({"; ".join(current[s].text for s in added[:8])})')
    if revoked:
        parts.append(f'снято подтверждений: {len(revoked)}')
    ImplEvents.objects.create(
        event_type='Schauto_Plan_Confirm', status='Успешно', solved='Да',
        event_message=f'Распределение №{run.pk}, {who}: {"; ".join(parts)}'[:900])
    return ConfirmResult(len(added), len(revoked))


def _overrides(run: PlanRun, check: Validation) -> list[dict]:
    """Подтверждённые вручную проблемы, с которыми применяется расчёт: кто и когда подтвердил"""
    stored = run.confirmed or {}
    return [{'text': problem.text, 'by': stored[sig].get('by', ''), 'at': stored[sig].get('at', '')}
            for sig, problem in sorted(check.confirmed.items())]


# --- применение -----------------------------------------------------------------------------------------------------

@dataclass
class ApplyResult:
    ok: bool
    stage: str                       # validation / sheets_access / sheets_check / done / partial / locked
    message: str
    validation: Validation | None = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)


def _order_value(assignments: list[Assignment]) -> str:
    """Что вписать в ячейку «Фотограф»: имена исполнителей заказа в порядке частей («Имя + Имя», как пишут в таблице)"""
    names: list[str] = []
    for a in sorted(assignments, key=lambda x: x.part_no):
        name = str(a.staff)
        if name not in names:
            names.append(name)
    return PEOPLE_SEPARATOR.join(names)


def _retoucher_value(group: list[Assignment]) -> str:
    """Кого вписать в «Ретушер» (только таблица Joki Joya): исполнителей заказа, которые обрабатывают фото сами"""
    if group[0].order.brand != 'JJ':
        return ''
    names: list[str] = []
    for a in sorted(group, key=lambda x: x.part_no):
        if a.staff and a.staff.retouches_own and str(a.staff) not in names:
            names.append(str(a.staff))
    return PEOPLE_SEPARATOR.join(names)


def _sheet_items(pending: list[Assignment]) -> tuple[list[SheetItem], dict[int, list[Assignment]]]:
    by_order: dict[int, list[Assignment]] = defaultdict(list)
    for a in pending:
        by_order[a.order_id].append(a)
    items = [SheetItem(order=group[0].order, value=_order_value(group), retoucher_value=_retoucher_value(group))
             for group in by_order.values()]
    return items, by_order


def _bulk_save(orders_fields: list[tuple[PhotoOrder, list[str]]]):
    """Сохраняет заказы пакетно: один запрос на набор полей вместо `save()` на каждый заказ"""
    by_fields: dict[tuple, list[PhotoOrder]] = defaultdict(list)
    for order, fields in orders_fields:
        by_fields[tuple(fields)].append(order)
    for fields, orders in by_fields.items():
        PhotoOrder.objects.bulk_update(orders, list(fields))


def _log(status: str, solved: str, text: str):
    ImplEvents.objects.create(event_type='Schauto_Plan_Apply', status=status, solved=solved, event_message=text[:900])


def apply_plan(run: PlanRun, user, *, client=None, only_check: bool = False) -> ApplyResult:
    """Проверяет и (если only_check=False) применяет распределение. Подробности - в докстринге модуля."""
    if not run.editable:
        return ApplyResult(False, 'locked', 'Расчёт уже применён или применяется прямо сейчас')

    check = validate_plan(run)
    if not check.ok:
        parts = []
        if check.blocking_count:
            parts.append(f'блокирующих проблем {check.blocking_count} (смените исполнителей)')
        if check.unconfirmed:
            parts.append(f'ждут вашего подтверждения {len(check.unconfirmed)} (отметьте «Успеет, подтверждаю» или смените исполнителя)')
        msg = f'Проверка не пройдена: {"; ".join(parts)}.'
        if not only_check:
            _log('Бизнес ошибка', 'Да', f'Применение распределения №{run.pk} отклонено проверкой: блокирующих {check.blocking_count}, '
                                        f'без подтверждения {len(check.unconfirmed)}')
        return ApplyResult(False, 'validation', msg, validation=check, errors=check.errors)
    overrides = _overrides(run, check)
    override_notes = [f'Подтверждено вручную ({o["by"] or "кем-то"}, {o["at"]}): {o["text"]}' for o in overrides]

    pending = [a for a in run.assignments.select_related('order__venue__store', 'staff') if not a.is_done]
    items, by_order = _sheet_items(pending)

    # предпроверка таблицы без записи: строка найдена, время то же, ячейка пуста. Прочитанное потом используется для записи
    try:
        prepared = sheetwrite.prepare(items, client=client)
    except SheetError as e:
        return ApplyResult(False, 'sheets_access', str(e), validation=check, errors=[str(e)])
    preflight = prepared.results
    bad = {order_id: r for order_id, r in preflight.items() if not r.ok}
    if bad:
        for order_id, r in bad.items():
            for a in by_order[order_id]:
                check.row_error(a, f'Google-таблица: {r.detail}')
        msg = f'Запись в таблицу невозможна: проблем {len(bad)}. В таблицах ничего не изменено.'
        if not only_check:
            _log('Бизнес ошибка', 'Да', f'Применение распределения №{run.pk} остановлено предпроверкой таблиц: {len(bad)} заказов')
        return ApplyResult(False, 'sheets_check', msg, validation=check)

    if only_check:
        notes = override_notes + [w for ws in check.row_warnings.values() for w in ws]
        for order_id, group in by_order.items():
            ret = preflight[order_id]
            if ret.ret_status == sheetwrite.RET_OTHER:
                notes.append(f'{group[0].order}: {ret.ret_detail} - оставлен, сам фотограф не вписывается')
            elif group[0].order.brand == 'JJ' and not _retoucher_value(group):
                notes.append(f'{group[0].order}: фотограф сам не обрабатывает фото - ретушёр не будет указан (нужен отдельный)')
        text = f'Все проверки успешны: можно применять ({len(items)} заказов, {len(pending)} частей)'
        text += f'; с подтверждёнными вручную проблемами: {len(overrides)}.' if overrides else '.'
        return ApplyResult(True, 'checked', text, validation=check, notes=notes,
                           counts={'orders': len(items), 'parts': len(pending), 'confirmed': len(overrides)})

    # защита от двойного нажатия
    if PlanRun.objects.filter(pk=run.pk, status__in=(PlanRun.STATUS_DRAFT, PlanRun.STATUS_PARTIAL)).update(
            status=PlanRun.STATUS_APPLYING) != 1:
        return ApplyResult(False, 'locked', 'Расчёт уже применяется: подождите и обновите страницу')

    notes = override_notes + [w for ws in check.row_warnings.values() for w in ws]
    try:
        sheet_results = sheetwrite.commit(prepared)
        counts = _record_and_write_schedule(run, pending, by_order, sheet_results, user, notes)
    except Exception as e:  # непредвиденный сбой: не оставляем расчёт «применяется»
        _finish(run, user, error=repr(e))
        _log('Системная ошибка', 'Нет', f'Применение распределения №{run.pk} прервано сбоем: {e!r}')
        return ApplyResult(False, 'partial', 'Применение прервано сбоем: часть данных могла быть записана. '
                           'Подробности в журнале ошибок; повторное применение пропустит уже сделанное.', validation=check)

    status = _finish(run, user, counts=counts, overrides=overrides)
    if status == PlanRun.STATUS_APPLIED:
        text = (f'Все проверки успешны, фотографы проставлены в график работы и в Google-таблицы: заказов в таблицах {counts["sheet"]}, '
                f'смен в графике {counts["schedule"]}'
                + (f' (центров без фототочки в ERP, где график не нужен: {counts["no_store"]})' if counts['no_store'] else '')
                + (f'; в «Ретушер» вписан сам фотограф: {counts["retoucher"]}' if counts['retoucher'] else '')
                + (f'; применено с подтверждёнными вручную проблемами: {len(overrides)}' if overrides else '') + '.')
        _log('Успешно', 'Да', f'Распределение №{run.pk} применено. {text}'
             + (' Подтверждено вручную: ' + '; '.join(f'{o["text"]} ({o["by"]})' for o in overrides[:10]) if overrides else ''))
        return ApplyResult(True, 'done', text, validation=check, notes=notes, counts=counts)
    errors = counts['errors']
    text = (f'Применено частично: в таблицы вписано заказов {counts["sheet"]}, в график {counts["schedule"]} смен; '
            f'не удалось: {len(errors)}. Исправьте причины и нажмите «Применить» ещё раз - сделанное повторно не пишется.')
    _log('Системная ошибка', 'Нет', f'Распределение №{run.pk} применено частично. {text} ' + '; '.join(errors[:5]))
    return ApplyResult(False, 'partial', text, validation=check, errors=errors, notes=notes, counts=counts)


@atomic
def _record_and_write_schedule(run, pending, by_order, sheet_results, user, notes) -> dict:
    """Фиксирует итоги записи в таблицы, обновляет заказы и пишет график для вписанных заказов"""
    counts = {'sheet': 0, 'schedule': 0, 'no_store': 0, 'retoucher': 0, 'errors': []}
    ok_orders = set()
    to_save: list[tuple[PhotoOrder, list[str]]] = []
    teams: dict[int, list[int]] = {}      # заказ, который снимают несколько фотографов -> все они
    for order_id, group in by_order.items():
        result = sheet_results.get(order_id) or sheetwrite.SheetResult(sheetwrite.ERROR, 'нет результата записи')
        for a in group:
            a.sheet_status, a.sheet_detail = result.status, result.detail[:200]
            if result.status == sheetwrite.WRITTEN:
                a.sheet_before, a.sheet_after = result.before, result.after   # по ним откат вернёт ячейку точно
        if result.ok:
            ok_orders.add(order_id)
            counts['sheet'] += result.status == sheetwrite.WRITTEN
            order = group[0].order
            order.status = PhotoOrder.STATUS_ASSIGNED
            order.photographer_raw = _order_value(group)
            members = list(dict.fromkeys(a.staff_id for a in sorted(group, key=lambda x: x.part_no)))
            order.photographer_id = members[0] if len(members) == 1 else None
            teams[order.pk] = members if len(members) > 1 else []
            fields = ['status', 'photographer_raw', 'photographer']
            if order.brand == 'JJ':                       # столбец «Ретушер» есть только в таблице Joki Joya
                ret_value = _retoucher_value(group)
                if not ret_value:
                    for a in group:
                        a.ret_status = 'not_own'
                    notes.append(f'{order}: фотограф сам не обрабатывает фото - ретушёр не указан (нужен отдельный)')
                elif result.status == sheetwrite.WRITTEN:
                    for a in group:
                        a.ret_status = result.ret_status
                        if result.ret_status == sheetwrite.WRITTEN:
                            a.ret_before, a.ret_after = result.ret_before, result.ret_after
                    if result.ret_status == sheetwrite.WRITTEN:
                        counts['retoucher'] += 1
                        order.retoucher_raw = ret_value
                        order.retoucher_id = group[0].staff_id if len({a.staff_id for a in group}) == 1 else None
                        fields += ['retoucher_raw', 'retoucher']
                    elif result.ret_status == sheetwrite.RET_OTHER:
                        notes.append(f'{order}: {result.ret_detail} - оставлен, сам фотограф не вписывается')
            to_save.append((order, fields))
        else:
            counts['errors'].append(f'{group[0].order}: {result.detail}')

    _bulk_save(to_save)
    sync_team(teams)

    # график: смена на точке центра, у времени работы - начало первого заказа фотографа в этот день на этой точке
    first_start: dict[tuple, int] = {}
    for a in run.assignments.select_related('order__venue__store').filter(staff__isnull=False):
        store = a.order.venue.store
        if store is not None:
            key = (a.staff_id, a.date, store.pk)
            first_start[key] = min(first_start.get(key, a.start_min), a.start_min)
    needed = {(a.staff_id, a.date, a.order.venue.store_id) for a in pending if a.order_id in ok_orders and a.order.venue.store_id}
    existing: dict[tuple, Schedule] = {}
    if needed:           # смены, которые уже есть, - одним запросом, а не по запросу на каждую
        for row in Schedule.objects.filter(staff_id__in={k[0] for k in needed}, date__in={k[1] for k in needed},
                                           store_id__in={k[2] for k in needed}):
            existing[(row.staff_id, row.date, row.store_id)] = row
    cache: dict[tuple, tuple] = {}
    for a in pending:
        if a.order_id not in ok_orders:
            continue
        store = a.order.venue.store
        if store is None:
            a.schedule_status = 'no_store'
            counts['no_store'] += 1
            continue
        key = (a.staff_id, a.date, store.pk)
        if key not in cache:
            row, created = existing.get(key), False
            if row is None:         # get_or_create: если смену успели создать параллельно, берём её, а не падаем на уникальности
                row, created = Schedule.objects.get_or_create(
                    staff_id=a.staff_id, date=a.date, store=store,
                    defaults={'position': SCHEDULE_POSITION, 'work_time': _hm(first_start[key])})
            cache[key] = (row, created)
            counts['schedule'] += created
            if not created and row.position != SCHEDULE_POSITION:
                notes.append(f'{a.staff} {a.date:%d.%m}: в графике на точке «{store.name}» уже есть смена с ролью «{row.position}» - оставлена как есть')
        row, created = cache[key]
        a.schedule, a.schedule_status = row, 'created' if created else 'exists'
    Assignment.objects.bulk_update(pending, ['sheet_status', 'sheet_detail', 'sheet_before', 'sheet_after', 'ret_status', 'ret_before',
                                             'ret_after', 'schedule', 'schedule_status'])
    return counts


def _current_log(run: PlanRun) -> list:
    """История применений из базы, а не из объекта в памяти: он мог устареть"""
    return list(PlanRun.objects.filter(pk=run.pk).values_list('apply_log', flat=True).first() or [])


def _finish(run: PlanRun, user, counts: dict | None = None, error: str = '', overrides: list | None = None) -> str:
    """Итоговый статус расчёта: применён, если все части вписаны в таблицу и обработаны в графике"""
    assignments = list(run.assignments.all())
    done = all(a.is_done and a.schedule_status for a in assignments if a.staff_id) and all(a.staff_id for a in assignments)
    status = PlanRun.STATUS_APPLIED if done and not error else (
        PlanRun.STATUS_PARTIAL if any(a.is_done for a in assignments) else PlanRun.STATUS_DRAFT)
    entry = {'action': 'apply', 'at': timezone.now().isoformat(timespec='seconds'), 'by': str(user) if getattr(user, 'pk', None) else '',
             'status': status, 'error': error[:200]}
    if counts:
        entry.update({'sheet': counts['sheet'], 'schedule': counts['schedule'], 'no_store': counts['no_store'],
                      'retoucher': counts['retoucher'], 'errors': counts['errors'][:10]})
    if overrides:
        entry['confirmed'] = overrides[:30]       # что и кто подтвердил вручную при этом применении
    PlanRun.objects.filter(pk=run.pk).update(
        status=status, applied_at=timezone.now(), applied_by=user if getattr(user, 'pk', None) else None,
        apply_log=[*_current_log(run), entry])
    run.status = status
    return status


# --- удаление черновика ---------------------------------------------------------------------------------------------------

class PlanNotDeletable(Exception):
    """Расчёт нельзя удалить; текст - причина для пользователя"""


@atomic
def delete_plan(run: PlanRun, user) -> str:
    """Удаляет черновик расчёта вместе с назначениями и объяснениями. Возвращает сообщение для пользователя.
    Google-таблицы, график работы и заказы не затрагиваются: черновик в них ничего не менял. Применённый расчёт удалить нельзя -
    сначала откат (иначе потеряется след того, что вписано в таблицы)."""
    fresh = PlanRun.objects.select_for_update().get(pk=run.pk)
    if fresh.status in (PlanRun.STATUS_APPLYING, PlanRun.STATUS_ROLLING_BACK):
        raise PlanNotDeletable('Расчёт сейчас применяется или откатывается - подождите минуту и обновите страницу')
    if fresh.status != PlanRun.STATUS_DRAFT or not fresh.deletable:
        raise PlanNotDeletable('Удалить можно только черновик. В таблицы уже вписаны исполнители: сначала нажмите «Откатить применение»')
    count = fresh.assignments.count()
    title = f'{fresh.date_from:%d.%m.%Y}-{fresh.date_to:%d.%m.%Y}'
    pk = fresh.pk
    fresh.delete()
    text = f'Распределение №{pk} за {title} удалено вместе с назначениями ({count})'
    ImplEvents.objects.create(event_type='Schauto_Plan_Delete', status='Успешно', solved='Да',
                              event_message=f'{text}. Кто: {user if getattr(user, "pk", None) else "—"}')
    return text


# --- откат ----------------------------------------------------------------------------------------------------------

@dataclass
class _ShiftChecks:
    """Данные для решения, можно ли удалить смены при откате: собираются несколькими запросами сразу на все смены"""
    first_start: dict       # (сотрудник, дата, точка) -> начало первого заказа расчёта
    by_schedule: dict       # id смены -> назначения этого расчёта
    used_elsewhere: set     # id смен, на которые ссылаются другие расчёты
    sales: set              # (точка, дата, сотрудник), у которых есть продажи (как админ или фотограф)
    salary: set             # (точка, дата, сотрудник) с рассчитанной зарплатой


def _shift_checks(run: PlanRun, assignments: list[Assignment], rows: list[Schedule]) -> _ShiftChecks:
    first_start: dict[tuple, int] = {}
    by_schedule: dict[int, list[Assignment]] = defaultdict(list)
    for a in assignments:
        if a.staff_id and a.order.venue.store_id:
            key = (a.staff_id, a.date, a.order.venue.store_id)
            first_start[key] = min(first_start.get(key, a.start_min), a.start_min)
        if a.schedule_id:
            by_schedule[a.schedule_id].append(a)
    stores, dates, staff = {r.store_id for r in rows}, {r.date for r in rows}, {r.staff_id for r in rows}
    sales: set[tuple] = set()
    for store_id, day, admin_id, photographer_id in Sales.objects.filter(store_id__in=stores, date__in=dates).filter(
            Q(staff_id__in=staff) | Q(photographer_id__in=staff)).values_list('store_id', 'date', 'staff_id', 'photographer_id'):
        sales.update({(store_id, day, admin_id), (store_id, day, photographer_id)})
    salary = set(Salary.objects.filter(store_id__in=stores, date__in=dates, staff_id__in=staff).values_list('store_id', 'date', 'staff_id'))
    used_elsewhere = set(Assignment.objects.filter(schedule_id__in=[r.pk for r in rows]).exclude(plan=run)
                         .values_list('schedule_id', flat=True))
    return _ShiftChecks(first_start, by_schedule, used_elsewhere, sales, salary)


def _schedule_block_reason(row: Schedule, checks: _ShiftChecks, reverted_ids: set[int]) -> str:
    """Почему смену, созданную применением, нельзя удалить (пустая строка - можно)"""
    if row.position != SCHEDULE_POSITION:
        return f'роль в смене изменена на «{row.position}»'
    expected = checks.first_start.get((row.staff_id, row.date, row.store_id))
    if expected is None or row.work_time != _hm(expected):
        return f'время работы изменено на {row.work_time}'
    if any(a.pk not in reverted_ids for a in checks.by_schedule.get(row.pk, [])):
        return 'часть заказов этой смены не удалось откатить в таблицах'
    if row.pk in checks.used_elsewhere:
        return 'смена используется другим расчётом'
    if (row.store_id, row.date, row.staff_id) in checks.sales:
        return 'на этой смене уже есть продажи'
    if (row.store_id, row.date, row.staff_id) in checks.salary:
        return 'по этой смене уже рассчитана зарплата'
    return ''


def rollback_plan(run: PlanRun, user, *, client=None) -> ApplyResult:
    """Откатывает применение: убирает вписанных фотографов из таблиц, удаляет созданные смены, возвращает заказы в «ждёт исполнителя».
    Делается только безопасное по каждому заказу; остальное остаётся как есть с указанием причины (статус расчёта - «частично»).
    Если откатано всё, расчёт снова становится черновиком, и его можно поправить и применить заново."""
    if not run.rollbackable:
        return ApplyResult(False, 'locked', 'Откатывать нечего: расчёт не применён или уже откачен')
    if PlanRun.objects.filter(pk=run.pk, status__in=(PlanRun.STATUS_APPLIED, PlanRun.STATUS_PARTIAL)).update(
            status=PlanRun.STATUS_ROLLING_BACK) != 1:
        return ApplyResult(False, 'locked', 'Расчёт сейчас применяется или откатывается: подождите и обновите страницу')
    previous = run.status

    def restore_status():
        PlanRun.objects.filter(pk=run.pk).update(status=previous)
        run.status = previous

    try:
        assignments = list(run.assignments.select_related('order__venue__store', 'staff', 'schedule'))
        written: dict[int, list[Assignment]] = defaultdict(list)
        for a in assignments:
            if a.sheet_status == 'written':
                written[a.order_id].append(a)
        items = [RevertItem(order=group[0].order, value=_order_value(group), before=group[0].sheet_before, after=group[0].sheet_after,
                            ret_before=group[0].ret_before, ret_after=group[0].ret_after if group[0].ret_status == 'written' else '')
                 for group in written.values()]
        try:
            results = sheetwrite.revert(items, write=True, client=client) if items else {}
        except SheetError as e:
            restore_status()
            return ApplyResult(False, 'sheets_access', str(e), errors=[str(e)])
        counts = _record_rollback(run, assignments, written, results)
    except Exception as e:
        restore_status()
        _log('Системная ошибка', 'Нет', f'Откат распределения №{run.pk} прерван сбоем: {e!r}')
        return ApplyResult(False, 'partial', 'Откат прерван сбоем: часть данных могла быть изменена. Подробности в журнале ошибок; '
                           'откат можно повторить - уже откатанное пропускается.')

    left = run.assignments.filter(sheet_status__in=('written', 'already')).exists()
    status = PlanRun.STATUS_PARTIAL if left else PlanRun.STATUS_DRAFT
    entry = {'action': 'rollback', 'at': timezone.now().isoformat(timespec='seconds'),
             'by': str(user) if getattr(user, 'pk', None) else '', 'status': status, 'error': '',
             'sheet': counts['cells'], 'retoucher': counts['retoucher'], 'schedule': counts['shifts'], 'errors': counts['errors'][:10],
             'kept': counts['kept'][:10]}
    update = {'status': status, 'apply_log': [*_current_log(run), entry]}
    if not left:
        update.update(applied_at=None, applied_by=None)
    PlanRun.objects.filter(pk=run.pk).update(**update)
    run.status = status

    if not counts['errors']:
        text = (f'Откат выполнен: из таблиц убрано заказов {counts["cells"]}'
                + (f' (в том числе из «Ретушер»: {counts["retoucher"]})' if counts['retoucher'] else '')
                + f', удалено смен в графике {counts["shifts"]}. '
                'Расчёт снова черновик: можно поправить исполнителей и применить заново.')
        _log('Успешно', 'Да', f'Распределение №{run.pk} откачено. {text}')
        return ApplyResult(True, 'rolled_back', text, notes=counts['kept'], counts=counts)
    text = (f'Откат выполнен частично: убрано заказов {counts["cells"]}, удалено смен {counts["shifts"]}, '
            f'не удалось откатить: {len(counts["errors"])}. Остальное остаётся как есть - исправьте причины и нажмите «Откатить» ещё раз.')
    _log('Бизнес ошибка', 'Нет', f'Откат распределения №{run.pk} частичный. {text} ' + '; '.join(counts['errors'][:5]))
    return ApplyResult(False, 'rollback_partial', text, errors=counts['errors'], notes=counts['kept'], counts=counts)


@atomic
def _record_rollback(run: PlanRun, assignments: list[Assignment], written: dict[int, list[Assignment]], results: dict) -> dict:
    counts = {'cells': 0, 'retoucher': 0, 'shifts': 0, 'errors': [], 'kept': []}
    reverted: list[Assignment] = []
    to_save: list[tuple[PhotoOrder, list[str]]] = []
    for a in assignments:
        if not a.is_done:
            continue
        if a.sheet_status == 'written':
            result = results.get(a.order_id)
            if result is None or result.status not in REVERT_OK_STATUSES:
                detail = result.detail if result else 'нет результата отката'
                a.sheet_detail = f'откат: {detail}'[:200]
                counts['errors'].append(f'{a.order}: {detail}')
                continue
            if result.status == sheetwrite.NOT_FOUND:
                counts['kept'].append(f'{a.order}: {result.detail}')
        reverted.append(a)          # 'already': имя в таблице стояло не от нас - в таблице ничего не трогаем

    reverted_ids = {a.pk for a in reverted}
    teams: dict[int, list[int]] = {}
    # заказы: возвращаем в «ждёт исполнителя», только если они в том виде, в каком их оставило применение
    for order_id, group in written.items():
        if group[0].pk not in reverted_ids:
            continue
        result = results[order_id]
        counts['cells'] += result.status == sheetwrite.REVERTED
        order = group[0].order
        fields = []
        if order.status == PhotoOrder.STATUS_ASSIGNED and order.photographer_raw == _order_value(group):
            order.status, order.photographer_id, order.photographer_raw = PhotoOrder.STATUS_OPEN, None, ''
            fields += ['status', 'photographer', 'photographer_raw']
            teams[order.pk] = []
        if group[0].ret_status == 'written':       # ячейку «Ретушер» откатываем отдельно: её изменение не мешает откату заказа
            counts['retoucher'] += result.ret_status == sheetwrite.REVERTED
            if result.ret_status in (sheetwrite.REVERTED, sheetwrite.CLEAN):
                if order.retoucher_raw == group[0].ret_after:
                    order.retoucher_id, order.retoucher_raw = None, ''
                    fields += ['retoucher', 'retoucher_raw']
            elif result.ret_status:
                counts['kept'].append(f'{order}: {result.ret_detail}')
        if fields:
            to_save.append((order, fields))

    _bulk_save(to_save)
    sync_team(teams)

    # смены, созданные применением: удаляем только безопасные
    rows = {a.schedule_id: a.schedule for a in reverted if a.schedule_status == 'created' and a.schedule_id}
    removable = []
    checks = _shift_checks(run, assignments, list(rows.values())) if rows else None
    for row in rows.values():
        reason = _schedule_block_reason(row, checks, reverted_ids)
        if reason:
            counts['kept'].append(f'Смена {row.staff} {row.date:%d.%m.%Y} на точке «{row.store.name}» оставлена: {reason}')
        else:
            removable.append(row.pk)

    for a in reverted:
        a.sheet_status = a.sheet_detail = a.sheet_before = a.sheet_after = a.ret_status = a.ret_before = a.ret_after = ''
        a.schedule, a.schedule_status = None, ''
    changed = [a for a in assignments if a.pk in reverted_ids or a.sheet_detail.startswith('откат:')]
    Assignment.objects.bulk_update(changed, ['sheet_status', 'sheet_detail', 'sheet_before', 'sheet_after', 'ret_status', 'ret_before',
                                             'ret_after', 'schedule', 'schedule_status'])
    counts['shifts'] = Schedule.objects.filter(pk__in=removable).delete()[0]
    return counts
