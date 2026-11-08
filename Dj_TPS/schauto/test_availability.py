from django.test import SimpleTestCase

from .availability import ALL_DAY, DAY, day_availability, parse_availability

H = 60


class ParseAvailabilityTests(SimpleTestCase):
    def windows(self, text):
        result = parse_availability(text)
        self.assertTrue(result.ok, f'{text!r}: {result.note}')
        return result.windows

    def test_empty_means_free_all_day(self):
        for text in (None, '', '   '):
            self.assertEqual(parse_availability(text), ALL_DAY)

    def test_all_day_phrases(self):
        for text in ('весь день', 'Весь день ', 'Могу весь день', 'с утра'):
            self.assertTrue(parse_availability(text).all_day, text)

    def test_from_time(self):
        for text, start in (('с 15:00', 15 * H), ('С 13', 13 * H), ('c 18.00', 18 * H), ('c18.00', 18 * H),
                            ('c 15/00', 15 * H), ('после 16:00', 16 * H), ('После 18.00', 18 * H),
                            ('Работаю с 17.00', 17 * H), ('Примерно с 18.00', 18 * H), ('C 18.00 +/- час', 18 * H),
                            ('Заказы с 16:30 ', 16 * H + 30), ('с 15 ч', 15 * H), ('С 14 !!!', 14 * H),
                            ('c 15:30 могу', 15 * H + 30), ('после 16:00 съемки ', 16 * H)):
            self.assertEqual(self.windows(text), ((start, DAY),), text)

    def test_latin_c_is_treated_as_cyrillic(self):
        # в таблицах "c 18.00" часто набрано латинской буквой
        self.assertEqual(self.windows('c 18.00'), self.windows('с 18.00'))

    def test_until_time(self):
        self.assertEqual(self.windows('до 18:00'), ((0, 18 * H),))
        self.assertEqual(self.windows('До 16.00'), ((0, 16 * H),))
        self.assertEqual(self.windows('до 17'), ((0, 17 * H),))

    def test_ranges(self):
        self.assertEqual(self.windows('11:00-22:00'), ((11 * H, 22 * H),))
        self.assertEqual(self.windows('9.00-17.00'), ((9 * H, 17 * H),))
        self.assertEqual(self.windows('12-17'), ((12 * H, 17 * H),))
        self.assertEqual(self.windows('8:00-13:30'), ((8 * H, 13 * H + 30),))
        self.assertEqual(self.windows('с 10:00 до 14:00'), ((10 * H, 14 * H),))

    def test_several_windows(self):
        self.assertEqual(self.windows('9:00-12:00 и 19:00-21:00'), ((9 * H, 12 * H), (19 * H, 21 * H)))
        self.assertEqual(self.windows('До 14:30 и с 18:30'), ((0, 14 * H + 30), (18 * H + 30, DAY)))

    def test_busy_interval_is_complement(self):
        self.assertEqual(self.windows('Занят 17:00-19:00'), ((0, 17 * H), (19 * H, DAY)))
        self.assertEqual(self.windows('c 15.00 - до 16.00 занят'), ((0, 15 * H), (16 * H, DAY)))

    def test_alternative_times_take_the_later_one(self):
        self.assertEqual(self.windows('С 12:30/13:00'), ((13 * H, DAY),))
        self.assertEqual(self.windows('c 11:00/11:30'), ((11 * H + 30, DAY),))
        self.assertEqual(self.windows('С 18:00 (17:45) '), ((18 * H, DAY),))

    def test_bare_time_is_from_time_with_note(self):
        result = parse_availability('15:30')
        self.assertEqual(result.windows, ((15 * H + 30, DAY),))
        self.assertIn('без «с»', result.note)

    def test_unparsed_text_gives_no_windows(self):
        for text in ('ПОЛ ДНЯ', 'как получится', 'с 25:00', 'занят вечером'):
            result = parse_availability(text)
            self.assertFalse(result.ok, text)
            self.assertEqual(result.windows, ())
            self.assertIn('не разобрано', result.describe())

    def test_covers_requires_one_window_to_contain_the_interval(self):
        a = parse_availability('9:00-12:00 и 19:00-21:00')
        self.assertTrue(a.covers(10 * H, 11 * H))
        self.assertTrue(a.covers(9 * H, 12 * H))
        self.assertFalse(a.covers(11 * H, 13 * H))   # выходит за окно
        self.assertFalse(a.covers(12 * H, 19 * H))   # между окнами
        self.assertTrue(ALL_DAY.covers(0, DAY))

    def test_describe(self):
        self.assertEqual(parse_availability('весь день').describe(), 'весь день')
        self.assertEqual(parse_availability('с 15:00').describe(), '15:00-24:00')


class DayAvailabilityTests(SimpleTestCase):
    def test_vacation_sick_leave_and_day_off_block_the_day(self):
        for status in ('Отпуск', 'Отгул', 'Больничный'):
            a = day_availability(status, 'весь день')
            self.assertEqual((a.windows, a.blocked), ((), status))
            self.assertFalse(a.covers(600, 700))

    def test_working_status_uses_the_text(self):
        self.assertEqual(day_availability('Работает', 'с 15:00').windows, ((15 * H, DAY),))
        self.assertEqual(day_availability('Работает', None), ALL_DAY)

    def test_only_vacation_sick_leave_and_day_off_close_the_day(self):
        # пустой статус, «Работает» и отсутствие записи - ставить можно; время - по тексту
        for status in (None, '', 'Работает'):
            self.assertEqual(day_availability(status, None), ALL_DAY, status)
            self.assertEqual(day_availability(status, 'до 12').windows, ((0, 12 * H),), status)
        for status in ('Отпуск', 'Отгул', 'Больничный'):
            a = day_availability(status, 'весь день')
            self.assertEqual((a.windows, a.blocked), ((), status))
