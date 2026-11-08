"""Чтение листов для загрузки заказов: сервисный аккаунт (ApiSource) и запасной публичный путь (PublicSource)"""
from collections import Counter
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from tph_system.models import ImplEvents, Staff

from . import googleapi
from .gsheet import KIND_CENTER, KIND_IGNORED, KIND_TRIPS
from .importer import run_import
from .models import PhotoOrder, Venue
from .tabsource import ApiSource, PublicSource, default_source
from .test_import import SHEETS, TODAY, FakeSheets
from .test_parsers import LL_HEADER
from .test_sheetwrite import FakeApiError, FakeClient, FakeWorksheet


def books_of(fake: FakeSheets) -> dict:
    """Те же данные, что у подмены публичного чтения, но как таблицы Google: {id таблицы: {gid: лист}}"""
    return {
        'll-sheet': {1: FakeWorksheet(fake.rows[1], 'ГАГАРИНСКИЙ'), 2: FakeWorksheet(fake.rows[2], 'ВЫЕЗДЫ'),
                     3: FakeWorksheet(fake.rows[3], 'ШОУ ВСЕ ЦЕНТРЫ')},
        'jj-sheet': {10: FakeWorksheet(fake.rows[10], 'РИО JJ')},
    }


def state() -> list:
    return list(PhotoOrder.objects.order_by('brand', 'tab_name', 'fingerprint').values_list(
        'brand', 'tab_name', 'sheet_gid', 'sheet_row', 'fingerprint', 'venue_id', 'date', 'time_start', 'time_end', 'slots', 'notes',
        'photographer_raw', 'retoucher_raw', 'photographer_id', 'no_retouch', 'status'))


@override_settings(SCHAUTO_SHEET_IDS=SHEETS)
class ApiImportTests(TestCase):
    def setUp(self):
        self.ggr = Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ')
        self.rio = Venue.objects.create(name='Рио JJ', brand='JJ', sheet_tab_name='РИО JJ')
        self.ivan = Staff.objects.create(f_name='Петров', name='Иван', date_empl='2026-01-01')
        self.fake = FakeSheets()
        self.client = FakeClient(books_of(self.fake))
        self.source = ApiSource(factory=lambda brand: self.client)

    def import_api(self, **kwargs):
        return run_import(today=TODAY, source=self.source, **kwargs)

    def test_tabs_are_listed_in_order_and_classified(self):
        tabs = self.source.tabs('LL')
        self.assertEqual([(t.name, t.gid, t.kind) for t in tabs],
                         [('ГАГАРИНСКИЙ', 1, KIND_CENTER), ('ВЫЕЗДЫ', 2, KIND_TRIPS), ('ШОУ ВСЕ ЦЕНТРЫ', 3, KIND_IGNORED)])
        self.assertEqual([(t.name, t.kind, t.center) for t in self.source.tabs('JJ')], [('РИО JJ', KIND_CENTER, 'РИО')])

    def test_result_is_the_same_as_with_public_reading(self):
        run_import(today=TODAY, source=PublicSource(self.fake.lister, self.fake.fetcher))
        public = state()
        self.assertEqual(len(public), 5)
        PhotoOrder.objects.all().delete()
        report = self.import_api()
        self.assertEqual(state(), public)
        self.assertEqual((report.created, report.updated, report.gone), (5, 0, 0))

    def test_repeated_import_is_idempotent(self):
        self.import_api()
        first = state()
        report = self.import_api()
        self.assertEqual((report.created, report.gone), (0, 0))
        self.assertEqual(state(), first)

    def test_a_spreadsheet_costs_two_requests(self):
        self.import_api()
        self.assertEqual(Counter(self.client.http.requests),
                         Counter({('meta', 'll-sheet'): 1, ('read', 'll-sheet'): 1, ('meta', 'jj-sheet'): 1, ('read', 'jj-sheet'): 1}))
        self.assertNotIn('write', {kind for kind, _ in self.client.http.requests})

    def test_request_count_does_not_depend_on_the_number_of_tabs(self):
        for i in range(12):
            self.client.http.books['ll-sheet'][20 + i] = FakeWorksheet([LL_HEADER], f'ЦЕНТР{i}')
            Venue.objects.create(name=f'Центр {i} LL', brand='LL', sheet_tab_name=f'ЦЕНТР{i}')
        report = self.import_api()
        self.assertEqual(len(report.tabs), 3 + 12)
        self.assertEqual(self.client.http.requests.count(('read', 'll-sheet')), 1)
        self.assertEqual(self.client.http.requests.count(('meta', 'll-sheet')), 1)

    def test_only_needed_tabs_are_asked_for(self):
        asked = []
        real = self.client.http.values_batch_get
        self.client.http.values_batch_get = lambda sid, ranges, params=None: (asked.append((sid, tuple(ranges))), real(sid, ranges, params))[1]
        self.import_api()
        self.assertEqual(dict(asked)['ll-sheet'], ("'ГАГАРИНСКИЙ'", "'ВЫЕЗДЫ'"))     # «ШОУ ВСЕ ЦЕНТРЫ» не читаем
        self.assertEqual(dict(asked)['jj-sheet'], ("'РИО JJ'",))

    def test_hidden_tab_is_treated_as_missing_like_on_the_public_page(self):
        self.client.http.books['ll-sheet'][1].hidden = True
        report = self.import_api()
        self.assertEqual([(t.tab, t.error) for t in report.failed_tabs], [('ГАГАРИНСКИЙ', 'лист не найден в таблице')])

    def test_a_broken_spreadsheet_does_not_stop_the_other_one(self):
        real = self.client.http.values_batch_get

        def flaky(sheet_id, ranges, params=None):
            if sheet_id == 'll-sheet':
                raise RuntimeError('нет доступа')
            return real(sheet_id, ranges, params)

        with mock.patch.object(self.client.http, 'values_batch_get', side_effect=flaky):
            report = self.import_api()
        self.assertEqual(len(report.errors), 1)
        self.assertIn('[LL]', report.errors[0])
        self.assertIn('нет доступа', report.errors[0])
        self.assertEqual(PhotoOrder.objects.filter(brand='LL').count(), 0)
        self.assertEqual(PhotoOrder.objects.filter(brand='JJ').count(), 1)
        self.assertEqual([t.tab for t in report.tabs], ['РИО JJ'])          # за сбойную таблицу - одна ошибка, а не по записи на лист
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Import', status='Системная ошибка').exists())

    def test_rate_limit_is_explained(self):
        with mock.patch.object(self.client.http, 'values_batch_get', side_effect=FakeApiError(429, 'Quota exceeded')):
            report = self.import_api()
        self.assertEqual(len(report.errors), 2)
        self.assertTrue(all('лимит запросов' in e for e in report.errors))
        self.assertEqual(PhotoOrder.objects.count(), 0)

    def test_a_tab_renamed_while_loading_asks_to_repeat(self):
        with mock.patch.object(self.client.http, 'values_batch_get', side_effect=FakeApiError(400, "Unable to parse range: 'ГАГАРИНСКИЙ'")):
            report = self.import_api(brands=('LL',))
        self.assertEqual(len(report.errors), 1)
        self.assertIn('повторите загрузку', report.errors[0])

    def test_a_failure_drops_the_shared_client_of_that_brand_only(self):
        good, bad = self.client, FakeClient({'ll-sheet': {1: FakeWorksheet(self.fake.rows[1], 'ГАГАРИНСКИЙ')}})
        googleapi._CLIENTS.clear()
        self.addCleanup(googleapi._CLIENTS.clear)
        googleapi._CLIENTS.update({'LL': bad, 'JJ': good})
        with mock.patch.object(bad.http, 'fetch_sheet_metadata', side_effect=ConnectionError('соединение разорвано')):
            report = run_import(today=TODAY, source=ApiSource())
        self.assertEqual(set(googleapi._CLIENTS), {'JJ'})
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(PhotoOrder.objects.filter(brand='JJ').count(), 1)

    def test_empty_spreadsheet_is_an_error(self):
        self.client.http.books['ll-sheet'].clear()
        report = self.import_api()
        self.assertEqual(len(report.errors), 1)
        self.assertIn('не найдено ни одного листа', report.errors[0])
        self.assertEqual(PhotoOrder.objects.filter(brand='JJ').count(), 1)

    def test_missing_sheet_id_never_reaches_google(self):
        with override_settings(SCHAUTO_SHEET_IDS={'LL': '', 'JJ': 'jj-sheet'}):
            report = self.import_api()
        self.assertEqual(len(report.errors), 1)
        self.assertEqual({sid for _, sid in self.client.http.requests}, {'jj-sheet'})

    def test_one_brand_only(self):
        report = self.import_api(brands=('JJ',))
        self.assertEqual(PhotoOrder.objects.filter(brand='LL').count(), 0)
        self.assertEqual({sid for _, sid in self.client.http.requests}, {'jj-sheet'})
        self.assertEqual(report.created, 1)


class DefaultSourceTests(TestCase):
    @override_settings(SCHAUTO_GOOGLE_CREDENTIALS_FILE='')
    def test_without_credentials_public_reading_is_used_and_the_report_says_so(self):
        source, note = default_source()
        self.assertIsInstance(source, PublicSource)
        self.assertIn('SCHAUTO_GOOGLE_CREDENTIALS_FILE', note)

    @override_settings(SCHAUTO_GOOGLE_CREDENTIALS_FILE=__file__)
    def test_with_credentials_the_service_account_is_used(self):
        source, note = default_source()
        self.assertIsInstance(source, ApiSource)
        self.assertEqual(note, '')

    @override_settings(SCHAUTO_SHEET_IDS=SHEETS)
    def test_fallback_note_reaches_the_report_and_the_event_log(self):
        Venue.objects.create(name='Рио JJ', brand='JJ', sheet_tab_name='РИО JJ')
        fake = FakeSheets()
        fallback = (PublicSource(fake.lister, fake.fetcher), 'чтение идёт по публичной ссылке, это медленнее')
        with mock.patch('schauto.importer.default_source', return_value=fallback):
            report = run_import(brands=('JJ',), today=TODAY)
        self.assertEqual(report.notes, ['чтение идёт по публичной ссылке, это медленнее'])
        self.assertIn('Примечание: чтение идёт по публичной ссылке', report.summary())
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Import', event_message__contains='Примечание').exists())

    @override_settings(SCHAUTO_SHEET_IDS=SHEETS)
    def test_custom_readers_are_always_public_even_if_the_account_is_configured(self):
        Venue.objects.create(name='Рио JJ', brand='JJ', sheet_tab_name='РИО JJ')
        fake = FakeSheets()
        with override_settings(SCHAUTO_GOOGLE_CREDENTIALS_FILE=__file__), mock.patch('schauto.importer.default_source') as chosen:
            run_import(brands=('JJ',), today=TODAY, lister=fake.lister, fetcher=fake.fetcher)
        chosen.assert_not_called()


class PublicSourceTests(TestCase):
    @override_settings(SCHAUTO_SHEET_IDS=SHEETS)
    def test_a_failing_tab_is_reported_alone(self):
        fake = FakeSheets()
        fake.failing_gids = {2}
        source = PublicSource(fake.lister, fake.fetcher)
        data = source.read('LL', source.tabs('LL')[:2])
        self.assertEqual(data[2], (None, 'таймаут'))
        self.assertEqual(data[1][1], '')
        self.assertEqual(data[1][0], fake.rows[1])

    def test_brands_are_read_one_after_another_to_keep_the_old_connection_count(self):
        self.assertFalse(PublicSource.parallel_brands)
        self.assertTrue(ApiSource.parallel_brands)


@override_settings(SCHAUTO_SHEET_IDS=SHEETS)
class SeedVenuesThroughApiTests(TestCase):
    def test_addresses_are_filled_from_rows_read_through_the_service_account(self):
        address = 'м.Ленинский проспект, ул.Вавилова, д.3, тц Гагаринский, 3 этаж'
        client = FakeClient({'ll-sheet': {1: FakeWorksheet([LL_HEADER + [address], ['22.10', '12:00-13:00']], 'ГАГАРИНСКИЙ')}})
        with mock.patch('schauto.management.commands.schauto_seed_venues.default_source', return_value=(ApiSource(lambda b: client), '')):
            call_command('schauto_seed_venues', '--brand', 'LL', fill_addresses=True, stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.assertEqual(Venue.objects.get(name='Гагаринский LL').address, address)
        self.assertEqual(Counter(client.http.requests), Counter({('meta', 'll-sheet'): 1, ('read', 'll-sheet'): 1}))
