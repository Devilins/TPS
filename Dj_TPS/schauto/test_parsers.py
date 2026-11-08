from datetime import date, time

from django.test import SimpleTestCase

from .gsheet import KIND_CENTER, KIND_TRIPS
from .parsers import (YearResolver, clean_person, norm_person, norm_place, parse_extra_minutes, parse_month_header,
                      parse_time, row_fingerprint, slot_gaps, split_date, split_parts, strip_manager)
from .sheetrows import SheetLayoutError, find_address, find_columns, parse_rows

TODAY = date(2026, 10, 21)
WINDOW = (date(2026, 10, 7), date(2027, 2, 18))


class DateTests(SimpleTestCase):
    def test_formats_seen_in_sheets(self):
        for text, expected in (('02.10', (2, 10, None)), ('2.10', (2, 10, None)), ('02.1', (2, 1, None)),
                               ('02.10.', (2, 10, None)), ('02.10.26', (2, 10, 2026)), ('02.10.2026', (2, 10, 2026)),
                               (' 03/10 ', (3, 10, None)), ('23.10 МЕГА', (23, 10, None))):
            parts = split_date(text)
            self.assertEqual((parts.day, parts.month, parts.year), expected, text)

    def test_garbage(self):
        for text in ('', 'ЯНВАРЬ 2026', '12:30', '12345', '12.103', 'абв'):
            self.assertIsNone(split_date(text), text)
        self.assertIsNone(YearResolver(TODAY).resolve(31, 2))  # 31 февраля разобралось как "день.месяц", но даты нет

    def test_note_after_date(self):
        self.assertEqual(split_date('23.10 МЕГА').note, 'МЕГА')
        self.assertTrue(split_date('23.10 (перенос с 03.10)').note.startswith('(перенос'))
        self.assertEqual(split_date('23.10').note, '')
        self.assertEqual(split_date('23.10.').note, '')

    def test_month_header(self):
        self.assertEqual(parse_month_header('ЯНВАРЬ 2026'), (2026, 1))
        self.assertEqual(parse_month_header('Июнь  2025'), (2025, 6))
        self.assertEqual(parse_month_header('Март 2026'), (2026, 3))
        self.assertEqual(parse_month_header('май 2024'), (2024, 5))
        self.assertEqual(parse_month_header('ОКТЯБРЬ'), (None, 10))  # у свежих месяцев года в разделителе нет
        self.assertIsNone(parse_month_header('02.10'))


class YearResolverTests(SimpleTestCase):
    def test_first_row_anchor_is_latest_date_not_far_in_the_future(self):
        self.assertEqual(YearResolver(TODAY).resolve(16, 10), date(2026, 10, 16))
        self.assertEqual(YearResolver(TODAY).resolve(15, 11), date(2026, 11, 15))   # заказ на следующий месяц
        self.assertEqual(YearResolver(TODAY).resolve(10, 1), date(2027, 1, 10))     # +81 день - ещё "будущее"
        self.assertEqual(YearResolver(TODAY).resolve(5, 2), date(2026, 2, 5))       # слишком далеко вперёд - значит, прошлое
        self.assertEqual(YearResolver(TODAY).resolve(10, 4), date(2026, 4, 10))     # заброшенный лист: самые свежие - апрельские

    def test_descending_month_blocks_across_year_boundary(self):
        resolver = YearResolver(TODAY)
        got = [resolver.resolve(15, m) for m in (11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 12, 11, 10)]
        self.assertEqual([(d.year, d.month) for d in got],
                         [(2026, 11), (2026, 10), (2026, 9), (2026, 8), (2026, 7), (2026, 6), (2026, 5), (2026, 4),
                          (2026, 3), (2026, 2), (2026, 1), (2025, 12), (2025, 11), (2025, 10)])

    def test_stray_rows_do_not_derail_the_sequence(self):
        resolver = YearResolver(TODAY)
        got = [resolver.resolve(d, m) for d, m in ((10, 10), (20, 10), (5, 9), (6, 6), (7, 6), (8, 6), (9, 9), (12, 9), (3, 8))]
        self.assertEqual([(d.year, d.month) for d in got], [(2026, 10)] * 2 + [(2026, 9), (2026, 6), (2026, 6), (2026, 6),
                                                                                (2026, 9), (2026, 9), (2026, 8)])

    def test_explicit_year_header_resets_the_anchor(self):
        resolver = YearResolver(TODAY)
        self.assertEqual(resolver.resolve(16, 10), date(2026, 10, 16))
        resolver.reset(2025, 1)                      # разделитель "ЯНВАРЬ 2025"
        self.assertEqual(resolver.resolve(25, 1), date(2025, 1, 25))
        self.assertEqual(resolver.resolve(1, 12), date(2024, 12, 1))

    def test_explicit_year_in_cell(self):
        self.assertEqual(YearResolver(TODAY).resolve(29, 3, 2026), date(2026, 3, 29))

    def test_leap_day(self):
        self.assertEqual(YearResolver(date(2028, 3, 1)).resolve(29, 2), date(2028, 2, 29))


class TimeTests(SimpleTestCase):
    def check(self, text, start, end, extra=0):
        res = parse_time(text)
        self.assertTrue(res.ok, f'{text}: {res.notes}')
        self.assertEqual((res.start, res.end, res.extra), (start, end, extra), text)
        return res

    def test_range_variants(self):
        for text in ('17:30-18:30', '17.30-18.30', '17:30 - 18:30', '17-30-18-30', '17/30-18.30', '17:30--18:30',
                     '17:30:00-18:30', '17 30-18:30', 'С 17:30-18:30', '17:30-18:30 фото', '17;30-18:30'):
            self.check(text, time(17, 30), time(18, 30))

    def test_extra_time(self):
        self.check('14:00-15:00 + доп час', time(14), time(15), 60)
        self.check('15:00-16:00 + доп 30 мин', time(15), time(16), 30)
        self.check('20:30-21:30+ 30 мин', time(20, 30), time(21, 30), 30)
        self.check('17:00-18:00+ доп час', time(17), time(18), 60)
        self.check('12.30-13.30 доп. полчаса', time(12, 30), time(13, 30), 30)

    def test_several_intervals_are_kept_separately(self):
        for text in ('14:00-15:00 и 15:30-16:30', '14:00-15:00, 15:30-16:30', '14:00-15:00\n15:30-16:30',
                     '14:00-15:00 + 15:30-16:30'):
            res = self.check(text, time(14), time(16, 30))
            self.assertEqual(res.slots, [(time(14), time(15)), (time(15, 30), time(16, 30))], text)
            self.assertIn('интервалов 2, перерывы 30 мин', ' '.join(res.notes), text)
            self.assertNotIn('разным фотографам', ' '.join(res.notes), text)  # перерыв короче часа
        self.assertEqual(self.check('16.00-17.00, 17/30-18.30', time(16), time(18, 30)).slots,
                         [(time(16), time(17)), (time(17, 30), time(18, 30))])

    def test_long_break_is_marked_splittable(self):
        res = self.check('10:00-11:00 и 12:30-13:30', time(10), time(13, 30))
        self.assertIn('части можно отдать разным фотографам', ' '.join(res.notes))
        self.assertEqual(slot_gaps(res.slots), [90])

    def test_overlapping_intervals_are_merged(self):
        res = self.check('10:00-11:00, 10:30-12:00', time(10), time(12))
        self.assertEqual(res.slots, [(time(10), time(12))])
        self.assertEqual(self.check('14:00-15:00 15:00-16:00', time(14), time(16)).slots, [(time(14), time(16))])

    def test_single_interval_has_one_slot(self):
        self.assertEqual(parse_time('17:30-18:30').slots, [(time(17, 30), time(18, 30))])

    def test_split_parts(self):
        slots = [(time(10), time(11)), (time(11, 30), time(12, 30)), (time(14), time(15))]
        # 30 мин - остаются вместе, 90 мин - отдельная часть
        self.assertEqual(split_parts(slots), [[(time(10), time(11)), (time(11, 30), time(12, 30))], [(time(14), time(15))]])
        self.assertEqual(split_parts(slots, min_gap=20), [[s] for s in slots])
        self.assertEqual(split_parts([(time(10), time(11)), (time(12), time(13))]), [[(time(10), time(11))], [(time(12), time(13))]])  # ровно час - делится
        self.assertEqual(split_parts([]), [])

    def test_unparsed(self):
        for text, note in (('1 час', 'только длительность'), ('2,5 часа', 'только длительность'), ('ТУРНИР', 'не распознано'),
                           ('', 'не распознано'), ('18:30-17:30', 'конец не позже начала'), ('25:00-26:00', 'нереальное')):
            res = parse_time(text)
            self.assertFalse(res.ok, text)
            self.assertIn(note, ' '.join(res.notes), text)

    def test_extra_minutes_parser(self):
        for text, expected in (('+30 мин Мария', 30), ('доп 30 мин', 30), ('доп час', 60), ('+ 1 час', 60),
                               ('+1,5 часа', 90), ('рав с доп пол часа в облаке', 30), ('без продления', 0), ('', 0),
                               ('доп час + 30 мин', 90)):
            self.assertEqual(parse_extra_minutes(text), expected, text)


class NamesTests(SimpleTestCase):
    def test_phone_is_stripped(self):
        self.assertEqual(clean_person('Катерина 89688649620'), 'Катерина')
        self.assertEqual(clean_person('Дина +7 (918) 015-88-74'), 'Дина')
        self.assertEqual(clean_person('Даша И.'), 'Даша И')
        self.assertEqual(clean_person('89688649620'), '')

    def test_manager_marker_is_stripped(self):
        manager = 'Катерина'
        for raw, expected in (('Катерина 89688649620', ''),
                              ('Катерина 89688649621', ''),                            # опечатка в конце номера
                              ('Катерина 89888649620', ''),                            # и в начале
                              ('катерина 8 968 864-96-20', ''),
                              ('Катерина89688649620', ''),
                              ('Катерина 89688649620 Арина Ершова', 'Арина Ершова'),
                              ('Катерина 89688649620\nИван Шабунов', 'Иван Шабунов'),
                              ('Катерина 89688649620 Иван Шабутов 8 912 345-67-89', 'Иван Шабутов'),
                              ('Дина 89180158874', 'Дина'),
                              ('Катерина', 'Катерина'),                                # без телефона - обычное имя
                              ('', '')):
            self.assertEqual(clean_person(strip_manager(raw, manager)), expected, raw)
        self.assertEqual(clean_person(strip_manager('Катерина 89688649620', '')), 'Катерина')  # у JJ маркера нет

    def test_norm(self):
        self.assertEqual(norm_person('  ЕЛЕНА   Лёвина 8900'), 'елена левина')
        self.assertEqual(norm_place('Адрес: м. Новаторская, ТРЦ РИО Ленинский'), 'м новаторская трц рио ленинский')

    def test_fingerprint_stable_and_case_insensitive(self):
        a = row_fingerprint('2026-10-02', 'Г123', 'Иванова', occurrence=0)
        self.assertEqual(a, row_fingerprint('2026-10-02', 'г123', 'ИВАНОВА', occurrence=0))
        self.assertNotEqual(a, row_fingerprint('2026-10-02', 'Г123', 'Иванова', occurrence=1))
        self.assertEqual(len(a), 32)


LL_HEADER = ['Дата', 'Время', '№ Банкета', 'Заказчик', 'Телефон', 'Именинник', 'ФОТО', 'ПОЖЕЛАНИЯ ПО ФОТОГРАФИИ',
             'Ссылка отправлена', 'Фотограф ']
JJ_HEADER = ['', 'Время', 'время/дата сдачи обработки', 'Заказчик', 'Именинник', 'Ссылка на готовые фото', 'Комментарии',
             'Ретушер', 'Фотограф ']


class SheetRowsTests(SimpleTestCase):
    def parse(self, kind, rows, window=WINDOW):
        return parse_rows(kind, rows, TODAY, *window)

    def test_ll_layout(self):
        rows = [LL_HEADER,
                ['22.10', '17:30-18:30', 'Г1001', 'Заказчик А', '', 'Маша', 'ссылка', '', '', 'Катерина 89688649620'],
                ['', '', '', '', ''],
                ['23.10', '', 'Г1002', 'Заказчик Б'],           # без времени
                ['мусор', '12:00-13:00'],                         # нераспознанная дата
                ['01.06', '12:00-13:00', 'Г1003'],               # вне окна (июнь - прошлое)
                ['24.10', '20.00-21.00 + доп час', 'Г1004', 'Заказчик В', '', '', '', '', '', '']]
        res = self.parse(KIND_CENTER, rows)
        self.assertEqual([(o.row, o.date, o.photographer) for o in res.orders],
                         [(2, date(2026, 10, 22), 'Катерина'), (7, date(2026, 10, 24), '')])
        self.assertEqual(res.orders[1].time.extra, 60)
        self.assertEqual({k: res.stats[k] for k in ('bad_date', 'no_time')}, {'bad_date': 1, 'no_time': 1})
        self.assertEqual(len(res.problems), 1)

    def test_year_is_taken_from_sheet_order_and_month_headers(self):
        rows = [LL_HEADER,
                ['15.11', '12:00-13:00', 'Г1'], ['10.10', '12:00-13:00', 'Г2'],
                ['ЯНВАРЬ 2025'],                                 # разделитель с годом: дальше январь 2025
                ['25.01', '12:00-13:00', 'Г3'], ['01.12', '12:00-13:00', 'Г4'],
                ['ОКТЯБРЬ'],                                     # без года - ни на что не влияет
                ['05.10', '12:00-13:00', 'Г5']]
        res = self.parse(KIND_CENTER, rows, window=(date(2000, 1, 1), date(2100, 1, 1)))
        self.assertEqual([o.date for o in res.orders],
                         [date(2026, 11, 15), date(2026, 10, 10), date(2025, 1, 25), date(2024, 12, 1), date(2024, 10, 5)])
        self.assertEqual(res.stats['bad_date'], 0)  # разделители месяцев - не ошибки

    def test_fingerprint_does_not_depend_on_resolved_year(self):
        row = ['22.10', '12:00-13:00', 'Г1', 'Заказчик', '', 'Маша', '', '', '', '']
        a = self.parse(KIND_CENTER, [LL_HEADER, row]).orders[0]
        b = parse_rows(KIND_CENTER, [LL_HEADER, row], date(2027, 9, 1), date(2026, 1, 1), date(2027, 12, 31)).orders[0]
        self.assertNotEqual(a.date, b.date)
        self.assertEqual(a.fingerprint, b.fingerprint)

    def test_jj_layout_with_untitled_date_column_and_retoucher(self):
        rows = [JJ_HEADER, ['22.10', '15:00-16:00', '', 'Заказчик', 'Именинник', '', '+30 мин', 'исходники', 'Алиса']]
        res = self.parse(KIND_CENTER, rows)
        order = res.orders[0]
        self.assertEqual((order.date, order.photographer, order.retoucher), (date(2026, 10, 22), 'Алиса', 'исходники'))
        self.assertEqual(order.extra_from_comment, 30)  # продление из комментария, т.к. в ячейке времени его нет

    def test_comment_extra_ignored_when_time_has_extra(self):
        rows = [JJ_HEADER, ['22.10', '15:00-16:00 + доп час', '', '', '', '', '+30 мин', '', '']]
        self.assertEqual(self.parse(KIND_CENTER, rows).orders[0].extra_from_comment, 0)

    def test_header_not_in_first_row_and_garbage_date_header(self):
        rows = [['Каширка', ''], ['М9706', 'Время', '№ Банкета', 'Заказчик', 'Телефон', 'Именинник', 'ФОТО', 'ПОЖЕЛАНИЯ',
                                   'Ссылка', 'Фотограф'],
                ['22.10', '12:00-13:00', 'КШ1', 'Х', '', '', '', '', '', 'Дина']]
        res = self.parse(KIND_CENTER, rows)
        self.assertEqual([(o.row, o.photographer) for o in res.orders], [(3, 'Дина')])

    def test_manager_default_is_not_a_photographer(self):
        def row(cell):
            return ['22.10', '12:00-13:00', 'Г1', 'Заказчик', '', 'Маша', '', '', '', cell]
        rows = [LL_HEADER, row('Катерина 89688649620'), row('Катерина 89688649620 Арина Ершова'), row('Дина 89180158874')]
        got = [o.photographer for o in parse_rows(KIND_CENTER, rows, TODAY, *WINDOW, manager='Катерина').orders]
        self.assertEqual(got, ['', 'Арина Ершова', 'Дина'])
        # без маркера (таблица JJ) прежнее поведение
        got = [o.photographer for o in parse_rows(KIND_CENTER, rows, TODAY, *WINDOW).orders]
        self.assertEqual(got, ['Катерина', 'Катерина Арина Ершова', 'Дина'])

    def test_duplicates_get_distinct_fingerprints_and_are_stable(self):
        row = ['22.10', '12:00-13:00', 'Г1', 'Заказчик', '', 'Маша', '', '', '', '']
        first = self.parse(KIND_CENTER, [LL_HEADER, row, row]).orders
        self.assertEqual(len({o.fingerprint for o in first}), 2)
        # время и исполнитель в отпечаток не входят
        moved = list(row); moved[1] = '13:00-14:00'; moved[9] = 'Дина'
        again = self.parse(KIND_CENTER, [LL_HEADER, moved, row]).orders
        self.assertEqual([o.fingerprint for o in again], [o.fingerprint for o in first])

    def test_rows_differing_only_in_case_or_spaces_still_get_distinct_fingerprints(self):
        a = ['22.10', '12:00-13:00', 'Г1', 'Иванова Анна', '', 'Маша', '', '', '', '']
        b = ['22.10', '12:00-13:00', 'Г1', 'иванова  анна', '', 'маша', '', '', '', '']
        fingerprints = [o.fingerprint for o in self.parse(KIND_CENTER, [LL_HEADER, a, b]).orders]
        self.assertEqual(len(set(fingerprints)), 2)

    def test_trips_sheet_keeps_address(self):
        header = ['Дата', 'Время', '№ Банкета', 'Заказчик', 'Телефон', 'адрес', 'ФОТО', 'Фотограф ']
        rows = [header, ['22.10', '12:00-13:00', '', 'Х', '', 'м. Новаторская, ТРЦ РИО Ленинский', '', 'Иван Петров']]
        order = self.parse(KIND_TRIPS, rows).orders[0]
        self.assertEqual(order.place, 'м. Новаторская, ТРЦ РИО Ленинский')
        # для обычного листа адрес не читается
        self.assertEqual(self.parse(KIND_CENTER, rows).orders[0].place, '')

    def test_layout_errors(self):
        with self.assertRaises(SheetLayoutError):
            find_columns([['a', 'b'], ['c', 'd']])
        with self.assertRaises(SheetLayoutError):
            find_columns([['Дата', 'Время', 'Заказчик']])  # нет столбца «Фотограф»
        self.assertEqual(self.parse(KIND_CENTER, []).orders, [])


class FindAddressTests(SimpleTestCase):
    LL = ['Дата', 'Время', '№ Банкета', 'Заказчик', 'Телефон', 'Именинник', 'ФОТО', 'ПОЖЕЛАНИЯ ПО ФОТОГРАФИИ',
          'Ссылка отправлена', 'Фотограф ']

    def header_with(self, *extra, base=None):
        return [(base or self.LL) + list(extra)]

    def test_addresses_as_written_in_real_sheets(self):
        for cell, expected in (
                ('м.Ленинский проспект, ул.Вавилова, д.3, тц Гагаринский, 3 этаж', 'м.Ленинский проспект, ул.Вавилова, д.3, тц Гагаринский, 3 этаж'),
                ('М. Беговая, Хорошёвское ш., 16, стр. 3, ТЦ «На Беговой», 3 этаж, Laserland. ', 'М. Беговая, Хорошёвское ш., 16, стр. 3, ТЦ «На Беговой», 3 этаж, Laserland'),
                ('МКАД, ТЦ Вегас (Каширский), 24-й километр, 1, посёлок Совхоза имени Ленина, 2 этаж. ', 'МКАД, ТЦ Вегас (Каширский), 24-й километр, 1, посёлок Совхоза имени Ленина, 2 этаж'),
                ('ТРЦ Весна!, Алтуфьевское шоссе, 1-й километр, вл. 3, строение 1, 2 этаж', 'ТРЦ Весна!, Алтуфьевское шоссе, 1-й километр, вл. 3, строение 1, 2 этаж'),
                ('М. Новаторская Ленинский просп., 109, Москва, (ТРЦ РИО Ленинский, этаж 3)', 'М. Новаторская Ленинский просп., 109, Москва, (ТРЦ РИО Ленинский, этаж 3)')):
            self.assertEqual(find_address(self.header_with(cell)), expected, cell)

    def test_address_is_chosen_among_service_cells(self):
        rows = self.header_with('Добрый день!  Фотографии с Вашего праздника готовы! Ниже ссылка для скачивания: ул. Ленина, д. 5',
                                'м. Мякинино, ул.Международная, д.12, тц Vegas City, 3 этаж')
        self.assertEqual(find_address(rows), 'м. Мякинино, ул.Международная, д.12, тц Vegas City, 3 этаж')

    def test_no_address(self):
        jj = ['', 'Время', 'Заказчик', 'Именинник', 'Ретушер', 'Фотограф ']
        self.assertEqual(find_address([jj + [' 1) Номер фото именинника. 2)Номер фото братьев/сестер (либо их нет)']]), '')
        self.assertEqual(find_address([jj]), '')
        self.assertEqual(find_address([['нет', 'заголовков']]), '')
