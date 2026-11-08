from datetime import date, time
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from django.core.management import call_command
from tph_system.models import ImplEvents, Staff, Store

from .gsheet import KIND_CENTER, KIND_TRIPS, SheetError, Tab
from .importer import ImportReport, apply_mappings, run_import
from .mapping import PERSON_IGNORED, PERSON_MATCHED, PERSON_UNMATCHED, Resolver
from .models import PhotoOrder, StaffAlias, Venue, VenueAlias
from .tabsource import PublicSource
from .test_parsers import JJ_HEADER, LL_HEADER

TODAY = date(2026, 10, 21)
SHEETS = {'LL': 'll-sheet', 'JJ': 'jj-sheet'}
TRIPS_HEADER = ['Дата', 'Время', '№ Банкета', 'Заказчик', 'Телефон', 'адрес', 'ФОТО', 'Фотограф ']
RIO_ADDRESS = 'м. Новаторская, ТРЦ РИО Ленинский, Ленинский проспект 1'


class FakeSheets:
    """Подмена Google-таблиц: листы бренда и их строки по gid"""

    def __init__(self):
        self.tabs = {
            'LL': [Tab('ГАГАРИНСКИЙ', 1, KIND_CENTER, 'ГАГАРИНСКИЙ'), Tab('ВЫЕЗДЫ', 2, KIND_TRIPS),
                   Tab('ШОУ ВСЕ ЦЕНТРЫ', 3, 'ignored')],
            'JJ': [Tab('РИО JJ', 10, KIND_CENTER, 'РИО')],
        }
        self.rows = {
            1: [LL_HEADER,
                ['22.10', '17:30-18:30', 'Г1001', 'Заказчик А', '', 'Маша', '', '', '', 'Иван Петров 89688649620'],
                ['23.10', '12:00-13:00', 'Г1002', 'Заказчик Б', '', 'Саша', '', '', '', ''],
                ['24.10', '1 час', 'Г1003', 'Заказчик В', '', 'Коля', '', '', '', 'Даша И']],
            2: [TRIPS_HEADER, ['25.10', '14:00-15:00', '', 'Заказчик Г', '', RIO_ADDRESS, '', '']],
            3: [['мусор']],
            10: [JJ_HEADER, ['22.10', '15:00-16:00', '', 'Заказчик', 'Именинник', '', '', 'исходники', 'Иван Петров']],
        }
        self.failing_gids = set()

    def lister(self, brand):
        return self.tabs[brand]

    def fetcher(self, sheet_id, gid):
        if gid in self.failing_gids:
            raise SheetError('таймаут')
        return self.rows[gid]


@override_settings(SCHAUTO_SHEET_IDS=SHEETS)
class ImportTests(TestCase):
    def setUp(self):
        self.ggr_ll = Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ')
        self.rio_jj = Venue.objects.create(name='Рио JJ', brand='JJ', sheet_tab_name='РИО JJ')
        self.ivan = Staff.objects.create(f_name='Петров', name='Иван', date_empl='2026-01-01')
        self.sheets = FakeSheets()

    def run_import(self, **kwargs):
        return run_import(today=TODAY, lister=self.sheets.lister, fetcher=self.sheets.fetcher, **kwargs)

    def order(self, **kwargs):
        return PhotoOrder.objects.get(**kwargs)

    def test_first_import(self):
        report = self.run_import()
        self.assertEqual((report.created, report.updated, report.gone), (5, 0, 0))
        self.assertEqual(len(report.tabs), 3)  # "ШОУ ВСЕ ЦЕНТРЫ" не читается

        matched = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2)
        self.assertEqual((matched.venue, matched.photographer, matched.status), (self.ggr_ll, self.ivan, 'assigned'))
        self.assertEqual((matched.time_start, matched.time_end), (time(17, 30), time(18, 30)))
        self.assertEqual(matched.photographer_raw, 'Иван Петров')  # телефон отброшен
        self.assertEqual(matched.duration_minutes, 60)

        self.assertEqual(self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3).status, 'open')
        unmatched = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=4)
        self.assertEqual((unmatched.status, unmatched.photographer, unmatched.photographer_raw),
                         ('needs_fix', None, 'Даша И'))
        self.assertIn('только длительность', unmatched.notes)

        jj = self.order(brand='JJ')
        self.assertEqual((jj.photographer, jj.no_retouch, jj.retoucher_raw), (self.ivan, True, ''))
        trip = self.order(tab_name='ВЫЕЗДЫ')
        self.assertEqual((trip.venue, trip.status, trip.place_raw), (None, 'needs_fix', RIO_ADDRESS))
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Import', status='Успешно').exists())

    def test_reimport_is_idempotent_and_updates_in_place(self):
        self.run_import()
        ids = set(PhotoOrder.objects.values_list('id', flat=True))
        self.sheets.rows[1][2][1] = '13:00-14:00'      # перенесли время
        self.sheets.rows[1][2][9] = 'Иван Петров'      # менеджер назначил фотографа
        report = self.run_import()
        self.assertEqual((report.created, report.updated, report.gone), (0, 5, 0))
        self.assertEqual(set(PhotoOrder.objects.values_list('id', flat=True)), ids)
        changed = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        self.assertEqual((changed.time_start, changed.status, changed.photographer), (time(13), 'assigned', self.ivan))

    def test_row_removed_from_sheet_becomes_gone_and_returns(self):
        self.run_import()
        removed = self.sheets.rows[1].pop(2)
        report = self.run_import()
        self.assertEqual(report.gone, 1)
        gone = self.order(brand='LL', status='gone')
        self.assertEqual(gone.raw_time, '12:00-13:00')
        self.sheets.rows[1].insert(2, removed)
        self.run_import()
        self.assertFalse(PhotoOrder.objects.filter(status='gone').exists())
        self.assertEqual(PhotoOrder.objects.filter(brand='LL').count(), 4)  # без дублей

    def test_failed_tab_does_not_break_others_and_keeps_data(self):
        self.run_import()
        self.sheets.failing_gids = {1}
        report = self.run_import()
        self.assertEqual([t.tab for t in report.failed_tabs], ['ГАГАРИНСКИЙ'])
        self.assertEqual(PhotoOrder.objects.filter(tab_name='ГАГАРИНСКИЙ', status='gone').count(), 0)
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Import', status='Системная ошибка').exists())

    def test_missing_sheet_id_is_reported(self):
        with override_settings(SCHAUTO_SHEET_IDS={'LL': '', 'JJ': 'jj-sheet'}):
            report = self.run_import()
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(PhotoOrder.objects.filter(brand='LL').count(), 0)
        self.assertEqual(PhotoOrder.objects.filter(brand='JJ').count(), 1)

    def test_missing_tab_and_inactive_venue(self):
        self.ggr_ll.sheet_tab_name = 'НЕТ ТАКОГО'
        self.ggr_ll.save()
        self.rio_jj.is_active = False
        self.rio_jj.save()
        report = self.run_import()
        self.assertEqual([t.error for t in report.failed_tabs], ['лист не найден в таблице'])
        self.assertEqual(PhotoOrder.objects.filter(brand='JJ').count(), 0)

    def test_person_mapping(self):
        self.run_import()
        resolver = Resolver()
        self.assertEqual(resolver.person('Иван Петров'), (PERSON_MATCHED, self.ivan.id))
        self.assertEqual(resolver.person('петров иван'), (PERSON_MATCHED, self.ivan.id))
        self.assertEqual(resolver.person('Даша И')[0], PERSON_UNMATCHED)

        dasha = Staff.objects.create(f_name='Иванова', name='Дарья', date_empl='2026-01-01')
        StaffAlias.objects.create(alias='даша и', staff=dasha)
        self.assertEqual(apply_mappings(), 1)
        order = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=4)
        self.assertEqual((order.photographer, order.status), (dasha, 'needs_fix'))  # время так и не распознано

    def test_ignored_alias_makes_order_open(self):
        self.sheets.rows[1][2][9] = 'ищем'
        self.run_import()
        self.assertEqual(self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3).status, 'assigned')
        StaffAlias.objects.create(alias='ищем', staff=None)
        apply_mappings()
        order = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        self.assertEqual((order.status, order.photographer_raw), ('open', ''))
        self.assertEqual(Resolver().person('ищем')[0], PERSON_IGNORED)
        # и при следующей загрузке тоже
        self.run_import()
        self.assertEqual(self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3).status, 'open')

    def test_trip_address_mapping_and_no_retouch_kept(self):
        self.run_import()
        VenueAlias.objects.create(fragment='рио ленинский', venue=self.rio_jj)
        apply_mappings()
        trip = self.order(tab_name='ВЫЕЗДЫ')
        self.assertEqual((trip.venue, trip.place_raw, trip.status), (self.rio_jj, '', 'open'))
        self.assertTrue(self.order(brand='JJ').no_retouch)
        # следующая загрузка применяет сопоставление сама
        self.run_import()
        self.assertEqual(self.order(tab_name='ВЫЕЗДЫ').venue, self.rio_jj)

    def test_longest_fragment_wins(self):
        VenueAlias.objects.create(fragment='рио', venue=self.rio_jj)
        VenueAlias.objects.create(fragment='рио ленинский', venue=self.ggr_ll)
        self.assertEqual(Resolver().place(RIO_ADDRESS), self.ggr_ll.id)
        self.assertIsNone(Resolver().place('ул. Ленина'))


@override_settings(SCHAUTO_SHEET_IDS=SHEETS)
class PagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('admin_i', 'a@example.com', 'x')
        cls.venue = Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ')
        cls.staff = Staff.objects.create(f_name='Петров', name='Иван', date_empl='2026-01-01')
        sheets = FakeSheets()
        run_import(today=TODAY, lister=sheets.lister, fetcher=sheets.fetcher)

    def setUp(self):
        self.client.force_login(self.user)

    def test_orders_page(self):
        url = reverse('schauto:orders')
        self.assertRedirects(self.client.get(url), f'{url}?date_from={timezone.localdate():%d.%m.%Y}', fetch_redirect_response=False)
        resp = self.client.get(url + '?date_from=01.10.2026')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['count'], 4)  # центра JJ в этом наборе нет - его лист не читается
        self.assertContains(resp, 'Даша И')              # неопознанное имя подсвечено
        self.assertContains(resp, 'edit#gid=1&amp;range=A2')  # ссылка на строку в таблице

    def test_orders_import_post_uses_importer(self):
        report = ImportReport(date_from=TODAY, date_to=TODAY)
        with mock.patch('schauto.views.run_import', return_value=report) as run:
            resp = self.client.post(reverse('schauto:orders_import'), {'brand': 'LL', 'date_from': '01.10.2026'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(run.call_args.args[0], ('LL',))
        self.assertEqual(str(run.call_args.args[1]), '2026-10-01')

    def test_orders_import_rejects_bad_dates(self):
        with mock.patch('schauto.views.run_import') as run:
            self.client.post(reverse('schauto:orders_import'), {'date_from': '10.10.2026', 'date_to': '01.10.2026'})
        run.assert_not_called()

    def test_mapping_page_and_actions(self):
        resp = self.client.get(reverse('schauto:mapping'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([n[1] for n in resp.context['names']], ['Даша И'])
        self.assertEqual([p[1] for p in resp.context['places']], [RIO_ADDRESS])

        # имя -> сотрудник
        self.client.post(reverse('schauto:mapping_person'), {'alias': 'Даша И', 'staff': self.staff.id})
        self.assertEqual(StaffAlias.objects.get().alias, 'даша и')
        self.assertEqual(PhotoOrder.objects.get(sheet_row=4, tab_name='ГАГАРИНСКИЙ').photographer, self.staff)

        # адрес -> новый центр
        key = resp.context['places'][0][0]
        self.client.post(reverse('schauto:mapping_place'), {'key': key, 'fragment': 'РИО Ленинский', 'new_venue': 'РИО Ленинский'})
        new_venue = Venue.objects.get(name='РИО Ленинский')
        self.assertEqual(new_venue.brand, 'OT')
        self.assertEqual(PhotoOrder.objects.get(tab_name='ВЫЕЗДЫ').venue, new_venue)
        self.assertEqual(self.client.get(reverse('schauto:mapping')).context['places'], [])

    def test_mapping_place_validation(self):
        key = 'м новаторская трц рио ленинский ленинский проспект 1'
        for data in ({'key': key, 'fragment': 'чужой адрес', 'new_venue': 'X'},            # фрагмента нет в адресе
                     {'key': key, 'fragment': 'рио ленинский'},                             # не выбран центр
                     {'key': key, 'fragment': 'рио ленинский', 'venue': self.venue.id, 'new_venue': 'X'}):  # и то и другое
            self.client.post(reverse('schauto:mapping_place'), data)
        self.assertFalse(VenueAlias.objects.exists())
        self.assertFalse(Venue.objects.filter(name='X').exists())

    def test_mapping_person_requires_choice(self):
        self.client.post(reverse('schauto:mapping_person'), {'alias': 'Даша И'})
        self.assertFalse(StaffAlias.objects.exists())

    def test_index_counters(self):
        resp = self.client.get(reverse('schauto:index'))
        self.assertEqual((resp.context['unmatched_names'], resp.context['unmatched_places']), (1, 1))


@override_settings(SCHAUTO_SHEET_IDS=SHEETS)
class ManagerAndSlotsTests(TestCase):
    """LL: руководитель в ячейке "Фотограф" - не исполнитель; заказы с разбивкой по времени хранят все интервалы"""

    def setUp(self):
        Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ')
        self.ivan = Staff.objects.create(f_name='Петров', name='Иван', date_empl='2026-01-01')
        self.sheets = FakeSheets()
        self.sheets.tabs['JJ'] = []
        self.sheets.rows[1] = [
            LL_HEADER,
            ['22.10', '10:00-11:00 и 12:30-13:30', 'Г1', 'А', '', 'Маша', '', '', '', 'Катерина 89688649620'],
            ['23.10', '14:00-15:00, 15:30-16:30 + доп час', 'Г2', 'Б', '', 'Саша', '', '', '', 'Катерина 89688649621 Иван Петров'],
            ['24.10', '12:00-13:00', 'Г3', 'В', '', 'Коля', '', '', '', 'Катерина'],
        ]
        run_import(today=TODAY, lister=self.sheets.lister, fetcher=self.sheets.fetcher)

    def order(self, row):
        return PhotoOrder.objects.get(tab_name='ГАГАРИНСКИЙ', sheet_row=row)

    def test_manager_default_means_unassigned(self):
        unassigned = self.order(2)
        self.assertEqual((unassigned.status, unassigned.photographer_raw, unassigned.photographer), ('open', '', None))

    def test_photographer_after_manager_is_read(self):
        assigned = self.order(3)
        self.assertEqual((assigned.status, assigned.photographer), ('assigned', self.ivan))

    def test_manager_name_without_phone_stays_a_name(self):
        self.assertEqual((self.order(4).status, self.order(4).photographer_raw), ('assigned', 'Катерина'))

    def test_full_intervals_are_stored_and_shown(self):
        order = self.order(2)
        self.assertEqual(order.slots, [['10:00', '11:00'], ['12:30', '13:30']])
        self.assertEqual((order.time_start, order.time_end), (time(10), time(13, 30)))
        self.assertEqual(order.intervals_display, '10:00-11:00, 12:30-13:30')
        self.assertEqual(order.duration_minutes, 120)          # перерыв не считается рабочим временем
        self.assertTrue(order.can_split)                       # перерыв 90 мин
        self.assertEqual(len(order.parts), 2)

    def test_short_break_keeps_order_together(self):
        order = self.order(3)
        self.assertEqual(order.intervals_display, '14:00-15:00, 15:30-16:30')
        self.assertEqual((order.duration_minutes, order.can_split), (120 + 60, False))  # +доп час

    def test_old_orders_without_slots_fall_back_to_span(self):
        order = self.order(4)
        order.slots = []
        self.assertEqual(order.intervals_display, '12:00-13:00')
        self.assertEqual(order.duration_minutes, 60)

    def test_reimport_keeps_slots(self):
        run_import(today=TODAY, lister=self.sheets.lister, fetcher=self.sheets.fetcher)
        self.assertEqual(self.order(2).slots, [['10:00', '11:00'], ['12:30', '13:30']])


def fake_tabs(brand):
    from .gsheet import Tab
    return {'LL': [Tab('ГАГАРИНСКИЙ', 1, KIND_CENTER, 'ГАГАРИНСКИЙ'), Tab('АЗОВСКИЙ', 2, KIND_CENTER, 'АЗОВСКИЙ'),
                   Tab('Миниляндия', 3, KIND_CENTER, 'Миниляндия'), Tab('ВЫЕЗДЫ', 4, KIND_TRIPS)],
            'JJ': [Tab('Гагаринский JJ', 10, KIND_CENTER, 'Гагаринский'), Tab('Облака JJ', 11, KIND_CENTER, 'Облака')]}[brand]


class SeedVenuesTests(TestCase):
    def setUp(self):
        Store.objects.create(name='Laserland Гагаринский', short_name='LLGgr', store_status='Действующая')
        Store.objects.create(name='Laserland Азовский', short_name='LLAzv', store_status='Закрытая')
        Store.objects.create(name='Joki Joya Гагаринский', short_name='JJGgr', store_status='Действующая')
        Store.objects.create(name='Техника в ремонте', short_name='Ремонт', store_status='Техническая')

    def seed(self, **kwargs):
        source = PublicSource(lister=lambda b, sid=None: fake_tabs(b))
        with mock.patch('schauto.management.commands.schauto_seed_venues.default_source', return_value=(source, '')):
            call_command('schauto_seed_venues', stdout=mock.MagicMock(), stderr=mock.MagicMock(), **kwargs)

    def test_creates_centers_links_active_stores_and_deactivates_closed(self):
        self.seed()
        ggr_ll, ggr_jj = Venue.objects.get(name='Гагаринский LL'), Venue.objects.get(name='Гагаринский JJ')
        self.assertEqual((ggr_ll.store.short_name, ggr_jj.store.short_name), ('LLGgr', 'JJGgr'))  # бренд различает одноимённые точки
        azov = Venue.objects.get(name='Азовский LL')
        self.assertEqual((azov.is_active, azov.store), (False, None))                             # точка закрыта
        for name in ('Миниляндия LL', 'Облака JJ'):
            venue = Venue.objects.get(name=name)
            self.assertEqual((venue.is_active, venue.store), (True, None), name)                   # нет точки в ERP - остаётся активным

    def test_trip_venues_and_aliases(self):
        self.seed()
        self.assertEqual(Venue.objects.get(name='Экзотаг Рио').brand, 'OT')
        resolver = Resolver()
        self.assertEqual(resolver.place('м. Новаторская, ТРЦ РИО Ленинский, Ленинский проспект 1'), Venue.objects.get(name='Экзотаг Рио').id)
        self.assertEqual(resolver.place('ТРЦ ГОРОД, Рязанский проспект 2'), Venue.objects.get(name='Экзотаг Город').id)

    def test_is_idempotent_and_does_not_flip_activity(self):
        self.seed()
        Venue.objects.filter(name='Азовский LL').update(is_active=True)   # владелец вернул вручную
        count = (Venue.objects.count(), VenueAlias.objects.count())
        self.seed()
        self.assertEqual((Venue.objects.count(), VenueAlias.objects.count()), count)
        self.assertTrue(Venue.objects.get(name='Азовский LL').is_active)

    def test_links_store_to_existing_venue_without_one(self):
        Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ')
        self.seed()
        self.assertEqual(Venue.objects.get(name='Гагаринский LL').store.short_name, 'LLGgr')

    def test_dry_run_writes_nothing(self):
        self.seed(dry_run=True)
        self.assertFalse(Venue.objects.exists() or VenueAlias.objects.exists())


class FillAddressesTests(TestCase):
    HEADER_WITH_ADDRESS = [LL_HEADER + ['м.Ленинский проспект, ул.Вавилова, д.3, тц Гагаринский, 3 этаж'], ['22.10', '12:00-13:00']]

    def run_command(self, **kwargs):
        def reader(sheet_id, gid):
            return self.HEADER_WITH_ADDRESS if gid == 1 else [LL_HEADER]   # у второго листа адреса нет
        tabs = lambda brand, sid=None: fake_tabs(brand) if brand == 'LL' else []
        source = PublicSource(lister=tabs, fetcher=reader)
        with mock.patch('schauto.management.commands.schauto_seed_venues.default_source', return_value=(source, '')), \
                override_settings(SCHAUTO_SHEET_IDS=SHEETS):
            call_command('schauto_seed_venues', '--brand', 'LL', fill_addresses=True, stdout=mock.MagicMock(), stderr=mock.MagicMock(), **kwargs)

    def test_fills_only_empty_addresses(self):
        Venue.objects.create(name='Азовский LL', brand='LL', sheet_tab_name='АЗОВСКИЙ', address='введён вручную')
        self.run_command()
        self.assertTrue(Venue.objects.get(name='Гагаринский LL').address.startswith('м.Ленинский проспект'))
        self.assertEqual(Venue.objects.get(name='Миниляндия LL').address, '')   # в листе адреса нет
        self.run_command()                                                       # повтор ничего не меняет
        self.assertEqual(Venue.objects.get(name='Азовский LL').address, 'введён вручную')

    def test_dry_run_writes_nothing(self):
        self.run_command(dry_run=True)
        self.assertFalse(Venue.objects.exists())
