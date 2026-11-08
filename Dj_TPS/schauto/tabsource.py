"""Откуда берутся листы Google-таблиц заказов: загрузка заказов и заведение центров читают их через один из двух источников.

- `ApiSource` - сервисный аккаунт Google (основной путь). Список листов - одним запросом метаданных, значения ВСЕХ нужных листов -
  одним `values:batchGet`; бренды читаются параллельно. Итого 2 запроса на таблицу, число листов на них не влияет
  (было ~27 запросов публичным CSV, 12-13 с; стало 4 запроса, ~3 с). Таблицы должны быть доступны сервисному аккаунту -
  он уже нужен для записи исполнителей, поэтому публичный доступ по ссылке для чтения больше не обязателен.
- `PublicSource` - запасной путь, пока сервисный аккаунт не настроен: страница `htmlview` и CSV-экспорт каждого листа отдельным
  запросом (6 потоков). Работает, пока таблица открыта по ссылке.
Значения у источников одинаковые: на копиях таблиц (30 листов, ~64 тыс. ячеек) строки совпали ячейка в ячейку, а разбор дал тот же
результат. Номер строки в листе = индекс + 1 в обоих.
Интерфейс источника: `tabs(brand, sheet_id=None)` -> [Tab] и `read(brand, tabs, sheet_id=None)` -> {gid: (строки, ошибка)}.
Ошибка уровня всей таблицы - `SheetError`; ошибка отдельного листа возвращается в паре (источники, читающие листы по одному).
Источники принимают подмены в тестах: клиент Google (`factory`) и функции чтения (`lister`/`fetcher`).
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from . import googleapi
from .gsheet import SheetError, Tab, classify_tab, get_sheet_id, list_tabs, read_tab_rows

logger = logging.getLogger(__name__)

FETCH_WORKERS = 6    # публичное чтение: одновременных загрузок листов

TabData = tuple[list[list[str]] | None, str]    # (строки листа, текст ошибки)


class ApiSource:
    """Чтение через Google Sheets API под сервисным аккаунтом"""
    name = 'сервисный аккаунт Google'
    parallel_brands = True      # у каждого бренда свой клиент и своя блокировка: таблицы можно читать одновременно

    def __init__(self, factory=None):
        self.factory = factory or googleapi.shared_client

    def _book(self, brand: str, sheet_id: str | None):
        return self.factory(brand).book(get_sheet_id(brand, sheet_id))

    def _failed(self, brand: str, e: Exception) -> SheetError:
        """Сбой клиента Google -> SheetError с понятным текстом, а клиент выбрасываем: следующая попытка начнёт чистый сеанс"""
        logger.warning('Не удалось прочитать таблицу %s: %s', brand, e)
        googleapi.forget_client(brand)
        if googleapi.is_missing_range(e):
            return SheetError('лист переименовали или удалили во время загрузки: повторите загрузку')
        return SheetError(googleapi.error_text(e))

    def tabs(self, brand: str, sheet_id: str | None = None) -> list[Tab]:
        try:
            sheets = self._book(brand, sheet_id).sheets()
        except SheetError:
            raise
        except Exception as e:
            raise self._failed(brand, e) from e
        tabs = []
        for gid, name, hidden in sheets:
            if hidden:      # скрытые листы публичная страница не показывает - ведём себя так же
                continue
            kind, center = classify_tab(brand, name)
            tabs.append(Tab(name=name, gid=gid, kind=kind, center=center))
        if not tabs:
            raise SheetError('В таблице не найдено ни одного листа: проверьте ID таблицы и доступ к ней сервисного аккаунта')
        return tabs

    def read(self, brand: str, tabs: list[Tab], sheet_id: str | None = None) -> dict[int, TabData]:
        if not tabs:
            return {}
        try:
            values = self._book(brand, sheet_id).read_tabs([tab.name for tab in tabs])
        except SheetError:
            raise
        except Exception as e:
            raise self._failed(brand, e) from e
        return {tab.gid: (values[tab.name], '') for tab in tabs}


class PublicSource:
    """Чтение по публичной ссылке (без учётной записи): запасной путь"""
    name = 'публичная ссылка'
    parallel_brands = False     # листы одного бренда и так читаются в FETCH_WORKERS потоках; не множим соединения к Google

    def __init__(self, lister=list_tabs, fetcher=read_tab_rows, workers: int = FETCH_WORKERS):
        self.lister = lister
        self.fetcher = fetcher
        self.workers = workers

    def tabs(self, brand: str, sheet_id: str | None = None) -> list[Tab]:
        return self.lister(brand) if sheet_id is None else self.lister(brand, sheet_id)

    def read(self, brand: str, tabs: list[Tab], sheet_id: str | None = None) -> dict[int, TabData]:
        sheet_id = get_sheet_id(brand, sheet_id)

        def fetch(tab: Tab) -> TabData:
            try:
                return self.fetcher(sheet_id, tab.gid), ''
            except Exception as e:  # один плохой лист не должен ронять всю загрузку
                return None, str(e) or e.__class__.__name__

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return {tab.gid: data for tab, data in zip(tabs, pool.map(fetch, tabs))}


def default_source() -> tuple[ApiSource | PublicSource, str]:
    """Источник по умолчанию и примечание для отчёта: сервисный аккаунт, а если доступ к Google не настроен - публичная ссылка"""
    try:
        googleapi.check_configured()
    except SheetError as e:
        return PublicSource(), f'чтение идёт по публичной ссылке, это медленнее ({e})'
    return ApiSource(), ''
