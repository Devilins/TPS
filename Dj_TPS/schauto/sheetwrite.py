"""Запись исполнителей в столбцы «Фотограф» и «Ретушер» Google-таблиц заказов (сервисный аккаунт Google).

Правила записи (ошибка здесь - чужие данные в живой таблице, поэтому осторожно):
- строка заказа ищется заново по отпечатку (в таблицах нет ID, а строки могут сдвигаться), а не по сохранённому номеру;
- пишем только если дата и время строки совпадают с заказом и ячейка «Фотограф» пуста (в Laserland в ней по умолчанию стоит
  руководитель с телефоном - имя дописывается после него, как делают сотрудники); исполнитель, которого вписали после загрузки,
  не перезаписывается (конфликт);
- повторная запись того же имени безопасна (`already`);
- перед записью целевые строки перечитываются: если строка изменилась с момента проверки - в неё не пишем (`changed`).
Ретушёр (таблица Joki Joya): если фотограф сам обрабатывает фото, его имя вписывается и в «Ретушер» - той же записью. Ячейку
«Ретушер» трогаем только пустую: уже указанный ретушёр и «исходники» (ретушь не нужна) остаются как есть, это не ошибка.
Откат (`revert`): ячейка очищается только если в ней ровно то, что записали мы; изменённую после записи не трогаем (конфликт).

Как это быстро и экономно (лимит Google - 60 чтений в минуту на пользователя, а сервер слабый): на одну таблицу приходится
всего 3 запроса - чтение ВСЕХ нужных листов одним `values:batchGet`, перечитывание целевых строк одним `batchGet` и запись всех
ячеек одним `values:batchUpdate`; таблицы разных брендов обрабатываются параллельно. Листы читаются по названию, сохранённому при
загрузке заказов: метаданные (номер листа -> название) запрашиваются только если лист переименовали или удалили. Верность строки
гарантирует не название листа, а отпечаток строки и сверка строки перед записью.
Проверка (`prepare`) и запись (`commit`) делят одно чтение. Вся работа с сетью - в `googleapi` (`GoogleBook`, общий клиент на
процесс, блокировки, таймауты); здесь остальное - чистые функции над прочитанными значениями.
Сеть и клиент можно подменить в тестах: `client` - объект с методом `book(sheet_id)`.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from . import googleapi
from .googleapi import VERIFY_COLUMNS, GoogleBook
from .gsheet import MANAGER_NAMES, classify_tab, get_sheet_id
from .models import PhotoOrder
from .parsers import NO_RETOUCH_VALUES, norm_person, norm_text, same_people
from .sheetrows import SheetLayoutError, find_columns, parse_rows

logger = logging.getLogger(__name__)

READY = 'ready'          # можно записать (режим проверки)
WRITTEN = 'written'      # записано
ALREADY = 'already'      # это имя уже стоит в ячейке
CONFLICT = 'conflict'    # в ячейке уже другой исполнитель
NOT_FOUND = 'not_found'  # строки заказа в таблице нет
CHANGED = 'changed'      # дата или время строки не совпадают с заказом (или строку изменили, пока шла проверка)
ERROR = 'error'          # сбой чтения/записи

REVERTED = 'reverted'    # откат: ячейка возвращена к прежнему виду
CLEAN = 'clean'          # откат: ячейка уже в прежнем виде, делать нечего

# Статусы ячейки «Ретушер» (поле SheetResult.ret_status); пустой статус - ретушёра не вписывали
RET_OTHER = 'other'          # ретушёр уже указан (или в ячейке что-то есть) - оставлен как есть
RET_ORIGINALS = 'originals'  # в ячейке «исходники»: ретушь не нужна
RET_NO_COLUMN = 'no_column'  # в листе нет столбца «Ретушер»

OK_STATUSES = frozenset({READY, WRITTEN, ALREADY})
REVERT_OK_STATUSES = frozenset({READY, REVERTED, CLEAN, NOT_FOUND})   # NOT_FOUND: строки нет - в таблице нашего имени тоже нет


@dataclass
class SheetItem:
    order: PhotoOrder
    value: str                  # что вписать: "Иван Петров" (если у заказа несколько исполнителей - через " / ")
    retoucher_value: str = ''   # что вписать в «Ретушер» (JJ, фотограф обрабатывает сам); пусто - ретушёра не вписываем


@dataclass
class RevertItem:
    order: PhotoOrder
    value: str          # имя (имена), которые вписывали
    before: str = ''    # что было в ячейке до записи
    after: str = ''     # что стало после записи целиком; пусто - запись сделана старой версией, определяем по имени
    ret_before: str = ''    # «Ретушер»: что было до записи
    ret_after: str = ''     # «Ретушер»: что стало после записи; пусто - ретушёра не вписывали


@dataclass
class SheetResult:
    status: str
    detail: str = ''
    before: str = ''    # для записи: что было в ячейке
    after: str = ''     # для записи: что стало в ячейке
    ret_status: str = ''    # ячейка «Ретушер»: ready/written/already/other/originals/no_column (запись), reverted/clean/conflict (откат)
    ret_detail: str = ''
    ret_before: str = ''
    ret_after: str = ''

    @property
    def ok(self) -> bool:
        return self.status in OK_STATUSES


# --- что делать с каждой строкой: чистые функции над прочитанными значениями ------------------------------------------

@dataclass
class _Cell:
    order_pk: int
    row: int
    col: int
    value: str


@dataclass
class _TabPlan:
    title: str
    rows: list[list[str]]
    results: dict[int, SheetResult] = field(default_factory=dict)   # статусы проверки по заказам
    cells: list[_Cell] = field(default_factory=list)                # что записать
    finals: dict[int, SheetResult] = field(default_factory=dict)    # статус заказа после успешной записи


def _same(a: str, b: str) -> bool:
    return ' '.join((a or '').split()) == ' '.join((b or '').split())


def _same_time(raw, order: PhotoOrder) -> bool:
    return raw.time.ok and raw.time.start == order.time_start and raw.time.end == order.time_end


def _cell_at(rows: list[list[str]], row: int, col: int) -> str:
    cells = rows[row - 1] if row - 1 < len(rows) else []
    return cells[col] if col < len(cells) else ''


def _parse_tab(brand: str, tab_name: str, rows: list[list[str]], group: list, today: date):
    """Столбцы листа и разобранные строки в окне дат заказов группы"""
    kind, _ = classify_tab(brand, tab_name)
    dates = [it.order.date for it in group]
    _, cols = find_columns(rows)
    parsed = parse_rows(kind, rows, today, min(dates), max(dates), MANAGER_NAMES.get(brand, ''))
    return cols, {o.fingerprint: o for o in parsed.orders}


def _plan_retoucher(item: SheetItem, raw, rows: list[list[str]], cols: dict) -> tuple[str, str, str | None, str]:
    """Что делать с ячейкой «Ретушер»: (статус, пояснение, новое значение или None - не писать, текущее значение)"""
    if not item.retoucher_value:
        return '', '', None, ''
    col = cols.get('retoucher')
    if col is None:
        return RET_NO_COLUMN, 'в таблице нет столбца «Ретушер»', None, ''
    current = _cell_at(rows, raw.row, col)
    if not current.strip():
        return READY, '', item.retoucher_value, current
    if raw.retoucher and norm_person(raw.retoucher) == norm_person(item.retoucher_value):
        return ALREADY, 'это имя уже стоит в «Ретушер»', None, current
    if norm_text(raw.retoucher) in NO_RETOUCH_VALUES:
        return RET_ORIGINALS, 'в «Ретушер» стоит «исходники»: ретушь не нужна', None, current
    return RET_OTHER, f'в «Ретушер» уже указано: «{current.strip()}»', None, current


def _plan_write_tab(brand: str, tab_name: str, title: str, rows: list[list[str]], group: list[SheetItem], today: date) -> _TabPlan:
    plan = _TabPlan(title, rows)
    try:
        cols, by_fingerprint = _parse_tab(brand, tab_name, rows, group, today)
    except SheetLayoutError as e:
        plan.results = {it.order.pk: SheetResult(ERROR, f'нестандартная разметка листа: {e}') for it in group}
        return plan
    col = cols['photographer']
    for item in group:
        order, raw = item.order, by_fingerprint.get(item.order.fingerprint)
        if raw is None:
            plan.results[order.pk] = SheetResult(NOT_FOUND, 'строка заказа не найдена в таблице: заказ изменили или удалили, загрузите заказы заново')
        elif raw.date != order.date or not _same_time(raw, order):
            plan.results[order.pk] = SheetResult(CHANGED, 'дата или время заказа в таблице изменились после загрузки, загрузите заказы заново')
        elif raw.photographer:
            if same_people(raw.photographer, item.value):
                plan.results[order.pk] = SheetResult(ALREADY, 'это имя уже стоит в таблице')
            else:
                plan.results[order.pk] = SheetResult(CONFLICT, f'в таблице уже указан исполнитель: «{raw.photographer}»')
        else:
            current = _cell_at(rows, raw.row, col)
            new_value = f'{current.strip()} {item.value}'.strip()   # Laserland: руководитель с телефоном остаётся, имя - после него
            ret_status, ret_detail, ret_new, ret_current = _plan_retoucher(item, raw, rows, cols)
            plan.cells.append(_Cell(order.pk, raw.row, col, new_value))
            if ret_new is not None:
                plan.cells.append(_Cell(order.pk, raw.row, cols['retoucher'], ret_new))
            plan.results[order.pk] = SheetResult(READY, before=current, after=new_value, ret_status=ret_status, ret_detail=ret_detail,
                                                 ret_before=ret_current, ret_after=ret_new or '')
            plan.finals[order.pk] = SheetResult(
                WRITTEN, before=current, after=new_value, ret_detail=ret_detail, ret_before=ret_current, ret_after=ret_new or '',
                ret_status=WRITTEN if ret_new is not None else ret_status)
    return plan


def _plan_ret_revert(item: RevertItem, raw, rows: list[list[str]], cols: dict) -> tuple[str, str, str | None]:
    """Откат «Ретушер»: (статус, пояснение, значение для возврата или None - не писать). Расхождение не ошибка:
    ячейку, которую изменили после записи, оставляем, откат заказа от этого не зависит."""
    if not item.ret_after:
        return '', '', None
    col = cols.get('retoucher')
    if col is None:
        return NOT_FOUND, 'в таблице нет столбца «Ретушер»', None
    current = _cell_at(rows, raw.row, col)
    if _same(current, item.ret_after):
        return READY, '', item.ret_before
    if _same(current, item.ret_before):
        return CLEAN, '', None
    return CONFLICT, f'«Ретушер» изменили после записи (сейчас «{current.strip()}»): оставлена как есть', None


def _plan_revert_tab(brand: str, tab_name: str, title: str, rows: list[list[str]], group: list[RevertItem], today: date) -> _TabPlan:
    plan = _TabPlan(title, rows)
    try:
        cols, by_fingerprint = _parse_tab(brand, tab_name, rows, group, today)
    except SheetLayoutError as e:
        plan.results = {it.order.pk: SheetResult(ERROR, f'нестандартная разметка листа: {e}') for it in group}
        return plan
    col = cols['photographer']
    for item in group:
        order, raw = item.order, by_fingerprint.get(item.order.fingerprint)
        if raw is None:
            plan.results[order.pk] = SheetResult(NOT_FOUND, 'строка заказа не найдена в таблице (удалена или изменена): возвращать нечего, '
                                                            'проверьте таблицу вручную')
            continue
        ret_status, ret_detail, ret_restore = _plan_ret_revert(item, raw, rows, cols)
        current = _cell_at(rows, raw.row, col)
        value = None            # что вернуть в «Фотограф»; None - не писать
        if item.after and _same(current, item.after):
            value = item.before
        elif not item.after and item.value and current.strip().endswith(item.value):
            value = current.strip()[:-len(item.value)].rstrip()      # запись старой версии: убираем имя с конца
        elif _same(current, item.before):
            plan.results[order.pk] = SheetResult(CLEAN, 'в ячейке уже прежнее значение', ret_status=ret_status, ret_detail=ret_detail)
        else:
            # «Фотограф» изменили после записи: заказ остаётся назначенным, «Ретушер» тоже не трогаем
            plan.results[order.pk] = SheetResult(CONFLICT, f'в ячейке сейчас «{current.strip()}», а мы вписывали «{item.after or item.value}»: '
                                                           f'её изменили после записи, не трогаем')
            continue
        if value is not None:
            plan.results[order.pk] = SheetResult(READY, ret_status=ret_status, ret_detail=ret_detail)
            plan.cells.append(_Cell(order.pk, raw.row, col, value))
        if ret_restore is not None:        # «Ретушер» откатываем и тогда, когда «Фотограф» уже чист
            plan.cells.append(_Cell(order.pk, raw.row, cols['retoucher'], ret_restore))
        if plan.cells and plan.cells[-1].order_pk == order.pk:
            done = plan.results[order.pk]
            plan.finals[order.pk] = SheetResult(
                REVERTED if value is not None else done.status, done.detail,
                ret_status=REVERTED if ret_restore is not None else done.ret_status, ret_detail=done.ret_detail)
    return plan


# --- чтение и запись: по одной таблице (бренду) -------------------------------------------------------------------------

@dataclass
class _BrandPlan:
    brand: str
    book: GoogleBook | None = None
    tabs: list[_TabPlan] = field(default_factory=list)
    results: dict[int, SheetResult] = field(default_factory=dict)


def _prepare_brand(brand: str, groups: dict, planner, factory) -> _BrandPlan:
    """groups: {(название листа при загрузке, gid): [элементы]}; planner - _plan_write_tab или _plan_revert_tab"""
    plan = _BrandPlan(brand)
    everyone = [it for group in groups.values() for it in group]
    try:
        plan.book = factory(brand).book(get_sheet_id(brand))
        wanted: dict[tuple, str] = {key: key[0] for key in groups}      # читаем по названию, сохранённому при загрузке
        try:
            values = plan.book.read_tabs(sorted(set(wanted.values())))
        except Exception as e:
            if not googleapi.is_missing_range(e):
                raise
            # какой-то лист переименовали или удалили: названия берём по номеру листа (единственный случай, когда нужны метаданные)
            titles = plan.book.titles()
            wanted = {}
            for key, group in groups.items():
                tab_name, gid = key
                if gid is None:
                    plan.results.update({it.order.pk: SheetResult(ERROR, 'у заказа не сохранён номер листа: загрузите заказы заново') for it in group})
                elif gid not in titles:
                    plan.results.update({it.order.pk: SheetResult(ERROR, f'лист «{tab_name}» не найден в таблице (удалён?)') for it in group})
                else:
                    wanted[key] = titles[gid]
            values = plan.book.read_tabs(sorted(set(wanted.values()))) if wanted else {}
        today = timezone.localdate()
        for (tab_name, gid), title in wanted.items():
            tab = planner(brand, tab_name, title, values[title], groups[(tab_name, gid)], today)
            plan.tabs.append(tab)
            plan.results.update(tab.results)
    except Exception as e:
        logger.exception('Не удалось прочитать таблицу %s', brand)
        googleapi.forget_client(brand)
        plan.tabs = []
        plan.results = {it.order.pk: SheetResult(ERROR, f'таблица {brand}: {googleapi.error_text(e)}') for it in everyone}
    return plan


def _row_key(cells: list[str]) -> tuple:
    """Значения строки для сверки: первые VERIFY_COLUMNS ячеек без пустого хвоста"""
    cells = list(cells[:VERIFY_COLUMNS])
    while cells and not cells[-1]:
        cells.pop()
    return tuple(cells)


def _commit_brand(plan: _BrandPlan) -> dict[int, SheetResult]:
    """Перечитывает целевые строки и, если они не изменились с проверки, записывает все ячейки одним запросом"""
    results = dict(plan.results)
    targets = [(tab, cell) for tab in plan.tabs for cell in tab.cells]
    if not targets:
        return results
    pks = {cell.order_pk for _, cell in targets}
    try:
        fresh = plan.book.read_rows(sorted({(tab.title, cell.row) for tab, cell in targets}))
        stale = {(tab.title, cell.row) for tab, cell in targets
                 if _row_key(fresh.get((tab.title, cell.row), [])) != _row_key(tab.rows[cell.row - 1] if cell.row - 1 < len(tab.rows) else [])}
        for tab, cell in targets:
            if (tab.title, cell.row) in stale:
                results[cell.order_pk] = SheetResult(CHANGED, 'строка в таблице изменилась, пока шла проверка: повторите применение')
        writable = [(tab, cell) for tab, cell in targets if (tab.title, cell.row) not in stale]
        if writable:
            plan.book.write([(tab.title, cell.row, cell.col, cell.value) for tab, cell in writable])
    except Exception as e:
        logger.exception('Запись в таблицу %s не удалась', plan.brand)
        googleapi.forget_client(plan.brand)
        for pk in pks:
            results[pk] = SheetResult(ERROR, f'ошибка записи в таблицу: {googleapi.error_text(e)}'[:200])
        return results
    for tab in plan.tabs:
        for pk, final in tab.finals.items():
            if results.get(pk) is not None and results[pk].status != CHANGED:
                results[pk] = final
    return results


@dataclass
class Prepared:
    """Результат проверки: что нашли в таблицах; `commit` записывает именно это, без повторного чтения всех листов"""
    results: dict[int, SheetResult]
    brands: dict[str, _BrandPlan] = field(default_factory=dict)


def _factory(client):
    """Откуда брать клиента для бренда: переданного (тесты) или общего на процесс"""
    if client is not None:
        return lambda brand: client
    googleapi.check_configured()    # доступ не настроен - SheetError до любой работы
    return googleapi.shared_client


def _prepare(items: list, planner, client) -> Prepared:
    factory = _factory(client)
    by_brand: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for item in items:
        by_brand[item.order.brand][(item.order.tab_name, item.order.sheet_gid)].append(item)
    plans = googleapi.run_per_brand(lambda brand: _prepare_brand(brand, by_brand[brand], planner, factory), {b: b for b in sorted(by_brand)})
    results: dict[int, SheetResult] = {}
    for plan in plans.values():
        results.update(plan.results)
    return Prepared(results, plans)


def prepare(items: list[SheetItem], *, client=None) -> Prepared:
    """Проверка записи: читает таблицы (по одному запросу на таблицу) и находит строки; ничего не меняет.
    SheetError - если доступ к Google не настроен; сбои по таблице попадают в результаты как `error`."""
    return _prepare(items, _plan_write_tab, client)


def prepare_revert(items: list[RevertItem], *, client=None) -> Prepared:
    return _prepare(items, _plan_revert_tab, client)


def commit(prepared: Prepared) -> dict[int, SheetResult]:
    """Записывает то, что нашла проверка. Ключ результата - id заказа."""
    committed = googleapi.run_per_brand(_commit_brand, prepared.brands)
    results: dict[int, SheetResult] = {}
    for brand_results in committed.values():
        results.update(brand_results)
    return results


def process(items: list[SheetItem], *, write: bool, client=None, today: date | None = None) -> dict[int, SheetResult]:
    """Проверяет (write=False) или записывает (write=True) исполнителей. `today` оставлен для совместимости вызовов."""
    prepared = prepare(items, client=client)
    return commit(prepared) if write else prepared.results


def revert(items: list[RevertItem], *, write: bool, client=None, today: date | None = None) -> dict[int, SheetResult]:
    """Возвращает ячейки к состоянию до записи (write=False - только проверка). Ключ результата - id заказа."""
    prepared = prepare_revert(items, client=client)
    return commit(prepared) if write else prepared.results
