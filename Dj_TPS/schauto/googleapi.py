"""Обмен с Google Sheets API под сервисным аккаунтом: единственное место, где schauto ходит в сеть с учёткой.

Им пользуются запись исполнителей (`sheetwrite`) и загрузка заказов (`tabsource`). Правила, ради которых всё устроено так
(лимит Google - 60 чтений в минуту на пользователя, сервер слабый - 1 ядро / 1 ГБ):
- обращаемся только к HTTP-клиенту `gspread` (`gspread.service_account(...).http_client`), а не к его объектам листов:
  `get_worksheet_by_id` при каждом вызове заново скачивает метаданные всей таблицы;
- на таблицу - несколько запросов вне зависимости от числа листов: все листы одним `values:batchGet` (адреса диапазонов группируются
  так, чтобы адрес запроса не вышел за предел), метаданные - отдельным запросом и только если они нужны;
- клиент Google живёт в процессе по одному на бренд (`shared_client`): токен действует час, соединение остаётся открытым, поэтому
  повторное нажатие не тратит время на вход и TLS-рукопожатие. Обращения к клиенту идут под блокировкой (сеанс не делим между
  потоками), а после любой ошибки клиент выбрасывается (`forget_client`) - следующая попытка начнётся с чистого сеанса;
- таймаут сети задан (иначе зависший ответ Google держал бы поток веб-сервера, пока не оборвёт nginx).
Сеть и клиент можно подменить в тестах: `client` - объект с методом `book(sheet_id)`.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from django.conf import settings

from .gsheet import SheetError

MAX_QUERY_CHARS = 6000        # длина адресов диапазонов в одном запросе чтения (у Google предел адреса около 8 КБ)
VERIFY_COLUMNS = 30           # сколько первых ячеек строки сверяем перед записью
HTTP_TIMEOUT = (10, 40)       # (соединение, ожидание ответа) в секундах


def col_letters(index: int) -> str:
    """Индекс столбца с нуля -> буквы A1-нотации (0 -> A, 26 -> AA)"""
    n, letters = index + 1, ''
    while n:
        n, rest = divmod(n - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def quote_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


class GoogleBook:
    """Одна Google-таблица. Все обращения к сети - здесь, по одному запросу на действие"""

    def __init__(self, http, sheet_id: str, lock=None):
        self.http = http
        self.sheet_id = sheet_id
        self.lock = lock or threading.RLock()

    def sheets(self) -> list[tuple[int, str, bool]]:
        """Листы в порядке вкладок: (номер листа - gid, название, скрыт ли); запрашиваются только эти поля"""
        with self.lock:
            meta = self.http.fetch_sheet_metadata(self.sheet_id, params={'fields': 'sheets.properties(sheetId,title,hidden)'})
        return [(s['properties']['sheetId'], s['properties']['title'], bool(s['properties'].get('hidden')))
                for s in meta.get('sheets', [])]

    def titles(self) -> dict[int, str]:
        """Номер листа (gid) -> название"""
        return {gid: title for gid, title, _hidden in self.sheets()}

    @staticmethod
    def _chunks(ranges: list[str]):
        # диапазоны группами так, чтобы адрес запроса не вышел за предел: обычно все - одним запросом
        chunk: list[str] = []
        size = 0
        for rng in ranges:
            n = len(quote(rng, safe='')) + len('&ranges=')
            if chunk and size + n > MAX_QUERY_CHARS:
                yield chunk
                chunk, size = [], 0
            chunk.append(rng)
            size += n
        if chunk:
            yield chunk

    def _batch_get(self, ranges: list[str]) -> list[dict]:
        out: list[dict] = []
        for chunk in self._chunks(ranges):
            with self.lock:
                value_ranges = self.http.values_batch_get(self.sheet_id, chunk).get('valueRanges', [])
            if len(value_ranges) != len(chunk):
                raise SheetError('Google вернул неполный ответ при чтении таблицы')
            out.extend(value_ranges)
        return out

    def read_tabs(self, titles: list[str]) -> dict[str, list[list[str]]]:
        """Все значения листов (как показаны в таблице); пустые хвосты строк и пустые последние строки Google не присылает.
        Номер строки в листе = индекс + 1 (пустые строки в середине приходят как [])."""
        result = {}
        for title, value_range in zip(titles, self._batch_get([quote_title(t) for t in titles])):
            start = value_range.get('range', '').rpartition('!')[2].partition(':')[0]
            if start not in ('', 'A1'):
                raise SheetError(f'лист «{title}»: Google вернул данные не с первой ячейки')
            result[title] = value_range.get('values', [])
        return result

    def read_rows(self, rows: list[tuple[str, int]]) -> dict[tuple[str, int], list[str]]:
        """Первые VERIFY_COLUMNS ячеек указанных строк (лист, номер строки с 1)"""
        last = col_letters(VERIFY_COLUMNS - 1)
        ranges = [f'{quote_title(title)}!A{row}:{last}{row}' for title, row in rows]
        return {spec: (value_range.get('values') or [[]])[0] for spec, value_range in zip(rows, self._batch_get(ranges))}

    def write(self, cells: list[tuple[str, int, int, str]]):
        """Записывает ячейки (лист, строка с 1, столбец с 0, значение) одним запросом, значения как есть"""
        data = [{'range': f'{quote_title(title)}!{col_letters(col)}{row}', 'values': [[value]]} for title, row, col, value in cells]
        with self.lock:
            self.http.values_batch_update(self.sheet_id, body={'valueInputOption': 'RAW', 'data': data})


class GoogleClient:
    def __init__(self, http):
        self.http = http
        self.lock = threading.RLock()       # один сеанс - один поток за раз

    def book(self, sheet_id: str) -> GoogleBook:
        return GoogleBook(self.http, sheet_id, self.lock)


def check_configured() -> str:
    """Путь к ключу сервисного аккаунта; SheetError, если доступ не настроен (без входа в Google)"""
    path = settings.SCHAUTO_GOOGLE_CREDENTIALS_FILE
    if not path:
        raise SheetError('Не настроен доступ к Google: не задана переменная SCHAUTO_GOOGLE_CREDENTIALS_FILE')
    if not Path(path).is_file():
        raise SheetError('Не настроен доступ к Google: файл ключа сервисного аккаунта не найден')
    return path


_CLIENTS: dict[str, GoogleClient] = {}
_CLIENTS_LOCK = threading.Lock()


def shared_client(brand: str) -> GoogleClient:
    """Клиент Google для таблицы бренда: создаётся один раз на процесс и переиспользуется"""
    with _CLIENTS_LOCK:
        if brand not in _CLIENTS:
            _CLIENTS[brand] = get_client()
        return _CLIENTS[brand]


def forget_client(brand: str):
    """Выбросить клиента (после ошибки): следующее обращение откроет новый сеанс"""
    with _CLIENTS_LOCK:
        _CLIENTS.pop(brand, None)


def get_client() -> GoogleClient:
    """Новый клиент сервисного аккаунта; SheetError, если доступ не настроен"""
    path = check_configured()
    try:
        import gspread
        http = gspread.service_account(filename=path).http_client
        http.set_timeout(HTTP_TIMEOUT)
        return GoogleClient(http)
    except Exception as e:  # битый ключ и т.п.
        raise SheetError(f'Не удалось войти в Google под сервисным аккаунтом: {e.__class__.__name__}') from e


def error_text(e: Exception) -> str:
    """Понятное сообщение о сбое Google; лимит запросов (429) - отдельно: он проходит сам, повторить безопасно"""
    if isinstance(e, SheetError):
        return str(e)
    if getattr(e, 'code', None) == 429:
        return 'превышен лимит запросов Google (60 чтений в минуту): подождите минуту и повторите - уже записанное повторно не пишется'
    return f'{e.__class__.__name__}: {str(e)[:120]}'


def is_missing_range(e: Exception) -> bool:
    """Google отказывается читать лист с таким названием (переименован или удалён): ошибка 400 "Unable to parse range" """
    return getattr(e, 'code', None) == 400 and 'Unable to parse range' in str(e)


def run_per_brand(fn, plans: dict) -> dict:
    """Таблицы разных брендов обрабатываем параллельно: это ожидание сети, а не работа процессора"""
    if len(plans) <= 1:
        return {brand: fn(arg) for brand, arg in plans.items()}
    with ThreadPoolExecutor(max_workers=len(plans)) as pool:
        futures = {brand: pool.submit(fn, arg) for brand, arg in plans.items()}
        return {brand: future.result() for brand, future in futures.items()}
