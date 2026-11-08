import re
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings

from tph_system.models import Staff

from . import googleapi
from .googleapi import GoogleClient
from .gsheet import SheetError
from .importer import run_import
from .models import PhotoOrder, Venue
from .sheetwrite import (ALREADY, CHANGED, CLEAN, CONFLICT, ERROR, NOT_FOUND, READY, RET_NO_COLUMN, RET_ORIGINALS, RET_OTHER,
                         REVERT_OK_STATUSES, REVERTED, WRITTEN, RevertItem, SheetItem, commit, prepare, process, revert)
from .test_import import SHEETS, TODAY, FakeSheets
from .test_parsers import JJ_HEADER, LL_HEADER

MANAGER = 'Катерина 89688649620'
LL_ROWS = [
    LL_HEADER,
    ['22.10', '10:00-11:00', 'Г2001', 'Заказчик 1', '', '', '', '', '', MANAGER],   # свободен: в ячейке только руководитель
    ['22.10', '15:00-16:00', 'Г2002', 'Заказчик 2', '', '', '', '', '', ''],          # свободен: ячейка пуста
    ['23.10', '12:00-13:00', 'Г2003', 'Заказчик 3', '', '', '', '', '', MANAGER + ' Даша Чужая'],  # кого-то уже вписали
]
JJ_ROWS = [
    JJ_HEADER,
    ['22.10', '12:00-13:00', '', 'Заказчик 4', 'Именинник', '', '', '', ''],
]


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


RANGE_RE = re.compile(r"^'((?:[^']|'')*)'(?:!([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?)?$")


class FakeWorksheet:
    """Лист в памяти (название - как у настоящего листа): значения отдаются так же, как их отдаёт Google"""

    def __init__(self, rows, title=''):
        width = max(len(r) for r in rows)
        self.rows = [list(r) + [''] * (width - len(r)) for r in rows]
        self.title = title
        self.updates = []             # A1-адреса записанных ячеек
        self.fail_on_write = False
        self.hidden = False           # скрытый лист

    def values(self):
        """Без пустых хвостов строк и пустых последних строк: Google их не присылает"""
        out = [list(r) for r in self.rows]
        for row in out:
            while row and not row[-1]:
                row.pop()
        while out and not out[-1]:
            out.pop()
        return out


class FakeApiError(Exception):
    """Ошибка API Google как её отдаёт gspread: у неё есть код"""

    def __init__(self, code, message):
        super().__init__(f'APIError: [{code}]: {message}')
        self.code = code


class FakeHttp:
    """Подмена HTTP-клиента gspread: те три метода, которые вызывает GoogleBook; таблицы - в памяти"""

    def __init__(self, books):
        self.books = books            # id таблицы -> {gid: FakeWorksheet}
        self.requests = []            # (вид запроса, id таблицы): по ним тесты считают обращения к Google

    def _sheet(self, sheet_id, title):
        for ws in self.books[sheet_id].values():
            if ws.title == title:
                return ws
        raise FakeApiError(400, f"Unable to parse range: '{title}'")

    def fetch_sheet_metadata(self, sheet_id, params=None):
        self.requests.append(('meta', sheet_id))
        assert params and 'fields' in params                   # запрашиваем только нужные поля, не всю таблицу
        return {'sheets': [{'properties': {'sheetId': gid, 'title': ws.title, **({'hidden': True} if ws.hidden else {})}}
                           for gid, ws in self.books[sheet_id].items()]}

    def values_batch_get(self, sheet_id, ranges, params=None):
        self.requests.append(('read', sheet_id))
        out = []
        for rng in ranges:
            m = RANGE_RE.match(rng)
            ws = self._sheet(sheet_id, m.group(1).replace("''", "'"))
            if m.group(2) is None:                              # весь лист
                out.append({'range': f"{rng}!A1:Z{len(ws.rows)}", 'values': ws.values()})
                continue
            c1, r1, c2, r2 = col_index(m.group(2)), int(m.group(3)), col_index(m.group(4)), int(m.group(5))
            rows = [ws.rows[r - 1][c1:c2 + 1] if r - 1 < len(ws.rows) else [] for r in range(r1, r2 + 1)]
            for row in rows:
                while row and not row[-1]:
                    row.pop()
            entry = {'range': f"{rng}!{m.group(2)}{r1}:{m.group(4)}{r2}"}
            if any(rows):
                entry['values'] = rows
            out.append(entry)
        return {'valueRanges': out}

    def values_batch_update(self, sheet_id, body=None):
        self.requests.append(('write', sheet_id))
        assert body['valueInputOption'] == 'RAW'              # значения пишутся как есть, без разбора Google
        targets = []
        for item in body['data']:
            m = RANGE_RE.match(item['range'])
            targets.append((self._sheet(sheet_id, m.group(1).replace("''", "'")), int(m.group(3)) - 1, col_index(m.group(2)),
                            m.group(2) + m.group(3), item['values'][0][0]))
        if any(ws.fail_on_write for ws, *_ in targets):
            raise RuntimeError('Google API недоступен')       # запись пакетная: либо вся, либо ничего
        for ws, row, col, a1, value in targets:
            ws.rows[row][col] = value
            ws.updates.append(a1)
        return {'totalUpdatedCells': len(targets)}


class FakeClient(GoogleClient):
    def __init__(self, books):
        super().__init__(FakeHttp(books))


@override_settings(SCHAUTO_SHEET_IDS=SHEETS)
class SheetEnv(TestCase):
    """Две таблицы (LL: лист 1, JJ: лист 10) с заказами, загруженными настоящим импортёром"""

    def setUp(self):
        self.ggr = Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ')
        self.rio = Venue.objects.create(name='Рио JJ', brand='JJ', sheet_tab_name='РИО JJ')
        self.ivan = Staff.objects.create(f_name='Петров', name='Иван', date_empl='2026-01-01')
        fake = FakeSheets()
        fake.rows = {1: [list(r) for r in LL_ROWS], 2: [['дата', 'Время', 'адрес', 'Фотограф']], 3: [['мусор']],
                     10: [list(r) for r in JJ_ROWS]}
        run_import(today=TODAY, lister=fake.lister, fetcher=fake.fetcher)
        self.ll = FakeWorksheet(LL_ROWS, 'ГАГАРИНСКИЙ')
        self.jj = FakeWorksheet(JJ_ROWS, 'РИО JJ')
        self.client = FakeClient({'ll-sheet': {1: self.ll}, 'jj-sheet': {10: self.jj}})
        self.http = self.client.http

    def order(self, **kwargs):
        return PhotoOrder.objects.get(**kwargs)

    def items(self, *orders, name='Иван Петров'):
        return [SheetItem(order=o, value=name) for o in orders]


class ProcessTests(SheetEnv):
    def test_dry_run_reads_but_never_writes(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        result = process(self.items(o), write=False, client=self.client, today=TODAY)
        self.assertEqual(result[o.pk].status, READY)
        self.assertEqual(self.ll.updates, [])
        self.assertEqual(self.ll.rows[2][9], '')

    def test_empty_cell_gets_the_name(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        result = process(self.items(o), write=True, client=self.client, today=TODAY)
        self.assertEqual(result[o.pk].status, WRITTEN)
        self.assertEqual(self.ll.rows[2][9], 'Иван Петров')

    def test_manager_stays_and_name_goes_after_him(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2)
        process(self.items(o), write=True, client=self.client, today=TODAY)
        self.assertEqual(self.ll.rows[1][9], MANAGER + ' Иван Петров')

    def test_jj_photographer_column_is_found_by_header(self):
        o = self.order(brand='JJ')
        result = process(self.items(o), write=True, client=self.client, today=TODAY)
        self.assertEqual(result[o.pk].status, WRITTEN)
        self.assertEqual(self.jj.rows[1][8], 'Иван Петров')

    def test_several_orders_one_write_request_per_spreadsheet(self):
        a, b = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        process(self.items(a, b), write=True, client=self.client, today=TODAY)
        self.assertEqual(self.http.requests.count(('write', 'll-sheet')), 1)
        self.assertEqual(sorted(self.ll.updates), ['J2', 'J3'])

    def test_someone_else_already_in_the_cell_is_a_conflict_and_is_not_overwritten(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=4)
        result = process(self.items(o), write=True, client=self.client, today=TODAY)
        self.assertEqual(result[o.pk].status, CONFLICT)
        self.assertIn('Даша Чужая', result[o.pk].detail)
        self.assertEqual(self.ll.rows[3][9], MANAGER + ' Даша Чужая')

    def test_the_same_name_is_idempotent(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=4)
        result = process(self.items(o, name='Даша Чужая'), write=True, client=self.client, today=TODAY)
        self.assertEqual(result[o.pk].status, ALREADY)
        self.assertEqual(self.ll.updates, [])

    def test_rows_shifted_since_import_are_still_found_by_fingerprint(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)   # при загрузке была строка 3
        self.ll.rows.insert(1, ['22.10', '09:00-09:30', 'Г2000', 'Новый', '', '', '', '', '', ''])   # сверху вставили строку
        result = process(self.items(o), write=True, client=self.client, today=TODAY)
        self.assertEqual(result[o.pk].status, WRITTEN)
        self.assertEqual(self.ll.updates, ['J4'])           # теперь это строка 4
        self.assertEqual(self.ll.rows[3][9], 'Иван Петров')
        self.assertEqual(self.ll.rows[1][9], '')            # вставленная строка не тронута

    def test_deleted_or_changed_rows_are_reported_not_written(self):
        gone, moved = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3), self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2)
        del self.ll.rows[2]                                  # строку заказа удалили
        self.ll.rows[1][1] = '11:00-12:00'                   # у другого перенесли время
        result = process(self.items(gone, moved), write=True, client=self.client, today=TODAY)
        self.assertEqual(result[gone.pk].status, NOT_FOUND)
        self.assertEqual(result[moved.pk].status, CHANGED)
        self.assertEqual(self.ll.updates, [])

    def test_write_failure_is_reported_per_order_and_nothing_is_marked_written(self):
        a, b = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(brand='JJ')
        self.ll.fail_on_write = True
        result = process(self.items(a, b), write=True, client=self.client, today=TODAY)
        self.assertEqual(result[a.pk].status, ERROR)
        self.assertIn('Google API недоступен', result[a.pk].detail)
        self.assertEqual(result[b.pk].status, WRITTEN)       # сбой одного листа не мешает другому

    def test_unreachable_spreadsheet_is_an_error_for_its_orders(self):
        o = self.order(brand='JJ')
        client = FakeClient({'ll-sheet': {1: self.ll}})   # таблицы JJ нет в доступе
        result = process(self.items(o), write=True, client=client, today=TODAY)
        self.assertEqual(result[o.pk].status, ERROR)

    def test_order_without_sheet_gid_is_read_by_title_and_fails_only_if_the_tab_was_renamed(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        PhotoOrder.objects.filter(pk=o.pk).update(sheet_gid=None)
        o.refresh_from_db()
        self.assertEqual(process(self.items(o), write=False, client=self.client, today=TODAY)[o.pk].status, READY)
        self.ll.title = 'Переименован'          # теперь без номера листа найти его нельзя
        result = process(self.items(o), write=False, client=self.client, today=TODAY)[o.pk]
        self.assertEqual(result.status, ERROR)
        self.assertIn('не сохранён номер листа', result.detail)

    def test_trips_sheet_is_handled(self):
        fake = FakeSheets()
        trip_rows = [['Дата', 'Время', '№ Банкета', 'Заказчик', 'Телефон', 'адрес', 'ФОТО', 'Фотограф '],
                     ['25.10', '14:00-15:00', '', 'Заказчик Г', '', 'м. Новаторская, ТРЦ РИО Ленинский', '', MANAGER]]
        fake.rows[2] = trip_rows
        from .models import VenueAlias
        VenueAlias.objects.create(fragment='трц рио ленинский', venue=self.rio)
        run_import(today=TODAY, lister=fake.lister, fetcher=fake.fetcher)
        o = self.order(tab_name='ВЫЕЗДЫ')
        trips = FakeWorksheet(trip_rows, 'ВЫЕЗДЫ')
        client = FakeClient({'ll-sheet': {2: trips}, 'jj-sheet': {}})
        result = process(self.items(o), write=True, client=client, today=TODAY)
        self.assertEqual(result[o.pk].status, WRITTEN)
        self.assertEqual(trips.rows[1][7], MANAGER + ' Иван Петров')


class RevertTests(SheetEnv):
    """Откат: ячейка возвращается к виду до записи, но только если её не меняли после"""

    def write(self, *orders, name='Иван Петров'):
        results = process(self.items(*orders, name=name), write=True, client=self.client, today=TODAY)
        return [RevertItem(o, name, results[o.pk].before, results[o.pk].after) for o in orders], results

    def test_write_remembers_what_was_in_the_cell(self):
        manager_row, empty_row = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        _, results = self.write(manager_row, empty_row)
        self.assertEqual((results[manager_row.pk].before, results[manager_row.pk].after), (MANAGER, MANAGER + ' Иван Петров'))
        self.assertEqual((results[empty_row.pk].before, results[empty_row.pk].after), ('', 'Иван Петров'))

    def test_revert_restores_manager_and_empty_cells(self):
        a, b, jj = (self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3),
                    self.order(brand='JJ'))
        items, _ = self.write(a, b, jj)
        result = revert(items, write=True, client=self.client, today=TODAY)
        self.assertEqual({r.status for r in result.values()}, {REVERTED})
        self.assertEqual((self.ll.rows[1][9], self.ll.rows[2][9], self.jj.rows[1][8]), (MANAGER, '', ''))

    def test_dry_run_changes_nothing(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        items, _ = self.write(o)
        self.assertEqual(revert(items, write=False, client=self.client, today=TODAY)[o.pk].status, READY)
        self.assertEqual(self.ll.rows[2][9], 'Иван Петров')

    def test_cell_changed_after_the_write_is_not_touched(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        items, _ = self.write(o)
        self.ll.rows[2][9] = 'Иван Петров и Даша'                  # руками дописали
        result = revert(items, write=True, client=self.client, today=TODAY)
        self.assertEqual(result[o.pk].status, CONFLICT)
        self.assertIn('Иван Петров и Даша', result[o.pk].detail)
        self.assertEqual(self.ll.rows[2][9], 'Иван Петров и Даша')

    def test_already_restored_cell_is_clean(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        items, _ = self.write(o)
        self.ll.rows[2][9] = ''                                      # кто-то уже очистил
        self.assertEqual(revert(items, write=True, client=self.client, today=TODAY)[o.pk].status, CLEAN)

    def test_missing_row_has_nothing_to_revert(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        items, _ = self.write(o)
        del self.ll.rows[2]
        status = revert(items, write=True, client=self.client, today=TODAY)[o.pk].status
        self.assertEqual(status, NOT_FOUND)
        self.assertIn(status, REVERT_OK_STATUSES)

    def test_shifted_rows_are_found_by_fingerprint(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        items, _ = self.write(o)
        self.ll.rows.insert(1, ['22.10', '09:00-09:30', 'Г2000', 'Новый', '', '', '', '', '', 'Другой Человек'])
        self.assertEqual(revert(items, write=True, client=self.client, today=TODAY)[o.pk].status, REVERTED)
        self.assertEqual((self.ll.rows[3][9], self.ll.rows[1][9]), ('', 'Другой Человек'))

    def test_old_runs_without_saved_cell_state_are_reverted_by_name(self):
        manager_row, empty_row = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        self.write(manager_row, empty_row)
        legacy = [RevertItem(manager_row, 'Иван Петров'), RevertItem(empty_row, 'Иван Петров')]   # before/after неизвестны
        result = revert(legacy, write=True, client=self.client, today=TODAY)
        self.assertEqual({r.status for r in result.values()}, {REVERTED})
        self.assertEqual((self.ll.rows[1][9], self.ll.rows[2][9]), (MANAGER, ''))

    def test_write_failure_is_an_error_and_keeps_the_cell(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        items, _ = self.write(o)
        self.ll.fail_on_write = True
        self.assertEqual(revert(items, write=True, client=self.client, today=TODAY)[o.pk].status, ERROR)
        self.assertEqual(self.ll.rows[2][9], 'Иван Петров')


class RetoucherTests(SheetEnv):
    """Таблица Joki Joya: фотограф, который обрабатывает фото сам, вписывается и в «Ретушер» (индекс 7), «Фотограф» - индекс 8"""

    def item(self, order, retoucher='Иван Петров', name='Иван Петров'):
        return [SheetItem(order=order, value=name, retoucher_value=retoucher)]

    def test_retoucher_is_written_together_with_the_photographer_in_one_batch(self):
        jj = self.order(brand='JJ')
        result = process(self.item(jj), write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual(self.http.requests.count(('write', 'jj-sheet')), 1)
        self.assertEqual((self.jj.rows[1][8], self.jj.rows[1][7]), ('Иван Петров', 'Иван Петров'))
        self.assertEqual((result.status, result.ret_status, result.ret_before, result.ret_after), (WRITTEN, WRITTEN, '', 'Иван Петров'))

    def test_dry_run_reports_without_writing(self):
        jj = self.order(brand='JJ')
        result = process(self.item(jj), write=False, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (READY, READY))
        self.assertEqual(self.jj.updates, [])

    def test_no_retoucher_value_means_the_cell_is_not_touched(self):
        jj = self.order(brand='JJ')
        result = process(self.item(jj, retoucher=''), write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (WRITTEN, ''))
        self.assertEqual((self.jj.rows[1][8], self.jj.rows[1][7]), ('Иван Петров', ''))

    def test_a_retoucher_already_in_the_cell_is_kept_and_does_not_block_the_photographer(self):
        jj = self.order(brand='JJ')
        self.jj.rows[1][7] = 'Даша Ретушёр'
        result = process(self.item(jj), write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (WRITTEN, RET_OTHER))
        self.assertIn('Даша Ретушёр', result.ret_detail)
        self.assertEqual((self.jj.rows[1][8], self.jj.rows[1][7]), ('Иван Петров', 'Даша Ретушёр'))

    def test_originals_means_no_retouching_is_needed(self):
        jj = self.order(brand='JJ')
        self.jj.rows[1][7] = 'исходники'
        result = process(self.item(jj), write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (WRITTEN, RET_ORIGINALS))
        self.assertEqual(self.jj.rows[1][7], 'исходники')

    def test_same_name_in_the_retoucher_cell_is_already_there(self):
        jj = self.order(brand='JJ')
        self.jj.rows[1][7] = 'Иван Петров'
        result = process(self.item(jj), write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual(result.ret_status, ALREADY)
        self.assertEqual(self.jj.updates, ['I2'])                        # только «Фотограф»

    def test_unclear_content_is_not_overwritten(self):
        jj = self.order(brand='JJ')
        self.jj.rows[1][7] = '?'
        result = process(self.item(jj), write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual(result.ret_status, RET_OTHER)
        self.assertEqual(self.jj.rows[1][7], '?')

    def test_laserland_has_no_retoucher_column(self):
        ll = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        result = process(self.item(ll), write=True, client=self.client, today=TODAY)[ll.pk]
        self.assertEqual((result.status, result.ret_status), (WRITTEN, RET_NO_COLUMN))
        self.assertEqual(self.ll.updates, ['J3'])

    def written(self, jj):
        r = process(self.item(jj), write=True, client=self.client, today=TODAY)[jj.pk]
        return RevertItem(jj, 'Иван Петров', r.before, r.after, r.ret_before, r.ret_after)

    def test_revert_restores_both_cells(self):
        jj = self.order(brand='JJ')
        item = self.written(jj)
        result = revert([item], write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (REVERTED, REVERTED))
        self.assertEqual((self.jj.rows[1][8], self.jj.rows[1][7]), ('', ''))

    def test_retoucher_changed_after_the_write_is_kept_but_the_order_is_reverted(self):
        jj = self.order(brand='JJ')
        item = self.written(jj)
        self.jj.rows[1][7] = 'Маша Ретушёр'                              # заменили ретушёра
        result = revert([item], write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (REVERTED, CONFLICT))
        self.assertEqual((self.jj.rows[1][8], self.jj.rows[1][7]), ('', 'Маша Ретушёр'))

    def test_photographer_conflict_keeps_the_retoucher_too(self):
        jj = self.order(brand='JJ')
        item = self.written(jj)
        self.jj.rows[1][8] = 'Иван Петров и Маша'
        result = revert([item], write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (CONFLICT, ''))
        self.assertEqual((self.jj.rows[1][8], self.jj.rows[1][7]), ('Иван Петров и Маша', 'Иван Петров'))

    def test_retoucher_is_reverted_even_if_the_photographer_cell_is_already_clean(self):
        jj = self.order(brand='JJ')
        item = self.written(jj)
        self.jj.rows[1][8] = ''
        result = revert([item], write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (CLEAN, REVERTED))
        self.assertEqual(self.jj.rows[1][7], '')

    def test_old_applications_without_retoucher_info_leave_the_retoucher_alone(self):
        jj = self.order(brand='JJ')
        self.jj.rows[1][7] = 'Иван Петров'
        self.jj.rows[1][8] = 'Иван Петров'
        result = revert([RevertItem(jj, 'Иван Петров', '', 'Иван Петров')], write=True, client=self.client, today=TODAY)[jj.pk]
        self.assertEqual((result.status, result.ret_status), (REVERTED, ''))
        self.assertEqual((self.jj.rows[1][8], self.jj.rows[1][7]), ('', 'Иван Петров'))


class QuotaTests(SheetEnv):
    def test_google_rate_limit_gets_a_clear_message_and_can_be_retried(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)

        class QuotaError(Exception):
            code = 429

        with mock.patch.object(self.http, 'values_batch_get', side_effect=QuotaError('Quota exceeded')):
            result = process(self.items(o), write=False, client=self.client, today=TODAY)[o.pk]
        self.assertEqual(result.status, ERROR)
        self.assertIn('лимит запросов Google', result.detail)
        self.assertIn('подождите минуту', result.detail)
        # лимит прошёл - та же запись проходит
        self.assertEqual(process(self.items(o), write=True, client=self.client, today=TODAY)[o.pk].status, WRITTEN)

    def test_rate_limit_on_write_is_explained_too(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)

        class QuotaError(Exception):
            code = 429

        with mock.patch.object(self.http, 'values_batch_update', side_effect=QuotaError('Quota exceeded')):
            result = process(self.items(o), write=True, client=self.client, today=TODAY)[o.pk]
        self.assertEqual(result.status, ERROR)
        self.assertIn('лимит запросов Google', result.detail)


class TransportTests(SheetEnv):
    """Как мы обращаемся к Google: сколько запросов, что читаем, что сверяем перед записью"""

    def requests_by(self, sheet_id):
        return [kind for kind, sid in self.http.requests if sid == sheet_id]

    def test_check_reads_each_spreadsheet_with_one_request_and_writes_nothing(self):
        a, jj = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(brand='JJ')
        prepared = prepare(self.items(a, jj), client=self.client)
        self.assertEqual((self.requests_by('ll-sheet'), self.requests_by('jj-sheet')), (['read'], ['read']))   # метаданные не нужны
        self.assertEqual({r.status for r in prepared.results.values()}, {READY})
        self.assertEqual((self.ll.updates, self.jj.updates), ([], []))

    def test_apply_reuses_the_check_read_and_adds_one_verification_read_and_one_write(self):
        a, jj = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(brand='JJ')
        results = commit(prepare(self.items(a, jj), client=self.client))
        self.assertEqual({r.status for r in results.values()}, {WRITTEN})
        for sheet in ('ll-sheet', 'jj-sheet'):
            self.assertEqual(self.requests_by(sheet), ['read', 'read', 'write'])     # 3 запроса на таблицу, а не по 2-3 на каждый лист

    def test_many_tabs_are_read_in_one_request_per_spreadsheet(self):
        sheets = {i: FakeWorksheet([['Дата', 'Время', 'Фотограф'], ['01.01', '10:00-11:00', '']], f'Лист {i}') for i in range(1, 11)}
        client = FakeClient({'ll-sheet': sheets})
        values = client.book('ll-sheet').read_tabs([f'Лист {i}' for i in range(1, 11)])
        self.assertEqual(len(values), 10)
        self.assertEqual(values['Лист 3'][1], ['01.01', '10:00-11:00'])                   # пустой хвост строки Google не присылает
        self.assertEqual(client.http.requests, [('read', 'll-sheet')])

    def test_more_tabs_than_the_request_address_allows_are_split_into_chunks(self):
        sheets = {i: FakeWorksheet([['a']], f'Лист {i}') for i in range(1, 151)}
        client = FakeClient({'x': sheets})
        values = client.book('x').read_tabs([f'Лист {i}' for i in range(1, 151)])
        self.assertEqual(len(values), 150)
        self.assertEqual(client.http.requests, [('read', 'x'), ('read', 'x')])            # адрес одного запроса ограничен по длине

    def test_tab_titles_with_quotes_and_letters_of_far_columns(self):
        from .googleapi import col_letters
        self.assertEqual([col_letters(i) for i in (0, 9, 25, 26, 27, 51, 52, 701, 702)], ['A', 'J', 'Z', 'AA', 'AB', 'AZ', 'BA', 'ZZ', 'AAA'])
        ws = FakeWorksheet([['a', 'b'], ['1', '2']], "Ж'Ё JJ")
        client = FakeClient({'x': {5: ws}})
        book = client.book('x')
        self.assertEqual(book.titles(), {5: "Ж'Ё JJ"})
        self.assertEqual(book.read_tabs(["Ж'Ё JJ"]), {"Ж'Ё JJ": [['a', 'b'], ['1', '2']]})
        book.write([("Ж'Ё JJ", 2, 1, 'новое')])
        self.assertEqual(ws.rows[1], ['1', 'новое'])
        self.assertEqual(book.read_rows([("Ж'Ё JJ", 2)]), {("Ж'Ё JJ", 2): ['1', 'новое']})

    def test_incomplete_or_shifted_google_response_is_an_error_not_a_guess(self):
        ws = FakeWorksheet([['a']], 'Лист')
        client = FakeClient({'x': {1: ws}})
        with mock.patch.object(client.http, 'values_batch_get', return_value={'valueRanges': []}):
            with self.assertRaisesMessage(SheetError, 'неполный ответ'):
                client.book('x').read_tabs(['Лист'])
        with mock.patch.object(client.http, 'values_batch_get', return_value={'valueRanges': [{'range': "'Лист'!B2:C3", 'values': [['x']]}]}):
            with self.assertRaisesMessage(SheetError, 'не с первой ячейки'):
                client.book('x').read_tabs(['Лист'])

    def test_a_tab_that_is_gone_from_the_spreadsheet_is_reported(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        PhotoOrder.objects.filter(pk=o.pk).update(sheet_gid=999)
        o.refresh_from_db()
        self.ll.title = 'Другое'                                    # листа с прежним названием больше нет
        result = process(self.items(o), write=False, client=self.client)[o.pk]
        self.assertEqual(result.status, ERROR)
        self.assertIn('не найден в таблице', result.detail)

    def test_renamed_tab_is_found_by_its_id_through_the_metadata_fallback(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        self.ll.title = 'Гагаринский (новое название)'
        self.assertEqual(process(self.items(o), write=True, client=self.client)[o.pk].status, WRITTEN)
        self.assertEqual(self.requests_by('ll-sheet'), ['read', 'meta', 'read', 'read', 'write'])   # неудачное чтение, метаданные, чтение заново
        self.assertEqual(self.ll.rows[2][9], 'Иван Петров')

    def test_normal_path_never_asks_for_metadata(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        process(self.items(o), write=True, client=self.client)
        self.assertNotIn('meta', self.requests_by('ll-sheet'))

    def test_row_changed_between_check_and_write_is_not_written(self):
        a, b = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        prepared = prepare(self.items(a, b), client=self.client)
        self.ll.rows[2][9] = 'Лена Новая'                          # пока шла проверка, в строку заказа b вписали человека
        results = commit(prepared)
        self.assertEqual(results[b.pk].status, CHANGED)
        self.assertIn('изменилась, пока шла проверка', results[b.pk].detail)
        self.assertEqual(results[a.pk].status, WRITTEN)           # остальные строки листа записываются
        self.assertEqual((self.ll.rows[1][9], self.ll.rows[2][9]), (MANAGER + ' Иван Петров', 'Лена Новая'))

    def test_rows_shifted_between_check_and_write_are_never_written_to_the_wrong_row(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        prepared = prepare(self.items(o), client=self.client)
        self.ll.rows.insert(1, ['22.10', '09:00-09:30', 'Г2000', 'Новый', '', '', '', '', '', ''])   # сверху вставили строку
        results = commit(prepared)
        self.assertEqual(results[o.pk].status, CHANGED)
        self.assertEqual(self.ll.updates, [])

    def test_unchanged_rows_pass_the_verification_even_if_other_rows_changed(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        prepared = prepare(self.items(o), client=self.client)
        self.ll.rows[3][3] = 'Заказчик 3 (исправили имя)'        # правят другую строку
        self.assertEqual(commit(prepared)[o.pk].status, WRITTEN)

    def test_a_failed_check_makes_commit_a_no_op(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=4)         # конфликт: чужой исполнитель
        results = commit(prepare(self.items(o), client=self.client))
        self.assertEqual(results[o.pk].status, CONFLICT)
        self.assertNotIn(('write', 'll-sheet'), self.http.requests)

    def test_a_broken_spreadsheet_does_not_stop_the_other_one(self):
        a, jj = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2), self.order(brand='JJ')
        client = FakeClient({'ll-sheet': {1: self.ll}, 'jj-sheet': {10: self.jj}})
        real_get = client.http.values_batch_get

        def flaky(sid, ranges, params=None):
            if sid == 'll-sheet':
                raise RuntimeError('нет доступа')
            return real_get(sid, ranges, params)

        with mock.patch.object(client.http, 'values_batch_get', side_effect=flaky):
            results = process(self.items(a, jj), write=True, client=client)
        self.assertEqual((results[a.pk].status, results[jj.pk].status), (ERROR, WRITTEN))
        self.assertIn('нет доступа', results[a.pk].detail)


class SharedClientTests(SheetEnv):
    """Клиент Google живёт в процессе: токен и соединение переиспользуются, а после ошибки сеанс начинается заново"""

    def setUp(self):
        super().setUp()
        googleapi._CLIENTS.clear()
        self.addCleanup(googleapi._CLIENTS.clear)
        patch_conf = mock.patch.object(googleapi, 'check_configured')
        patch_conf.start()
        self.addCleanup(patch_conf.stop)

    def test_client_is_created_once_per_brand_and_reused_by_later_operations(self):
        ll, jj = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3), self.order(brand='JJ')
        with mock.patch.object(googleapi, 'get_client', side_effect=lambda: self.client) as new_client:
            process(self.items(ll, jj), write=False)                   # без client: берётся общий
            process(self.items(ll, jj), write=True)
            process(self.items(ll), write=False)
        self.assertEqual(new_client.call_count, 2)                      # по одному входу на бренд за три операции
        self.assertEqual(set(googleapi._CLIENTS), {'LL', 'JJ'})

    def test_a_failure_drops_that_brands_client_so_the_next_attempt_starts_clean(self):
        ll, jj = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3), self.order(brand='JJ')
        real_get = self.http.values_batch_get

        def flaky(sheet_id, ranges, params=None):
            if sheet_id == 'll-sheet':
                raise ConnectionError('соединение разорвано')
            return real_get(sheet_id, ranges, params)

        with mock.patch.object(googleapi, 'get_client', side_effect=lambda: self.client) as new_client, \
                mock.patch.object(self.http, 'values_batch_get', side_effect=flaky):
            results = process(self.items(ll, jj), write=False)
        self.assertEqual((results[ll.pk].status, results[jj.pk].status), (ERROR, READY))
        self.assertEqual(set(googleapi._CLIENTS), {'JJ'})              # у сбойного бренда клиент выброшен, у здорового остался
        with mock.patch.object(googleapi, 'get_client', side_effect=lambda: self.client) as new_client:
            self.assertEqual(process(self.items(ll), write=False)[ll.pk].status, READY)
        self.assertEqual(new_client.call_count, 1)                      # заново вошли только для сбойного бренда

    def test_network_calls_of_one_client_are_serialized_by_its_lock(self):
        client = FakeClient({'x': {1: FakeWorksheet([['a']], 'Лист')}})
        book = client.book('x')
        seen = []
        real = client.http.values_batch_get

        def spy(sheet_id, ranges, params=None):
            seen.append(client.lock._is_owned())                       # вызов идёт, пока блокировка удерживается
            return real(sheet_id, ranges, params)

        with mock.patch.object(client.http, 'values_batch_get', side_effect=spy):
            book.read_tabs(['Лист'])
        self.assertEqual(seen, [True])

    def test_missing_configuration_is_reported_before_any_network_call(self):
        mock.patch.stopall()                                            # снимаем подмену check_configured
        ll = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        with override_settings(SCHAUTO_GOOGLE_CREDENTIALS_FILE=''):
            with self.assertRaisesMessage(SheetError, 'SCHAUTO_GOOGLE_CREDENTIALS_FILE'):
                prepare(self.items(ll))
        self.assertEqual(self.http.requests, [])


class ClientTests(TestCase):
    @override_settings(SCHAUTO_GOOGLE_CREDENTIALS_FILE='')
    def test_missing_setting_is_reported(self):
        with self.assertRaisesMessage(SheetError, 'SCHAUTO_GOOGLE_CREDENTIALS_FILE'):
            googleapi.get_client()

    @override_settings(SCHAUTO_GOOGLE_CREDENTIALS_FILE='/nonexistent/key.json')
    def test_missing_file_is_reported_without_leaking_the_path(self):
        with self.assertRaises(SheetError) as ctx:
            googleapi.get_client()
        self.assertNotIn('/nonexistent', str(ctx.exception))

    def test_client_gets_network_timeouts_so_a_stuck_google_cannot_hold_the_server(self):
        http = mock.MagicMock()
        fake_gspread = mock.MagicMock()
        fake_gspread.service_account.return_value.http_client = http
        with override_settings(SCHAUTO_GOOGLE_CREDENTIALS_FILE=__file__), mock.patch.dict('sys.modules', {'gspread': fake_gspread}):
            client = googleapi.get_client()
        http.set_timeout.assert_called_once_with(googleapi.HTTP_TIMEOUT)
        self.assertIs(client.http, http)
