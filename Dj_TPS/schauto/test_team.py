"""Заказ с перерывом снимают двое: в ячейке «Фотограф» записано «Роман + Лиза Гужвенко»"""
from datetime import time

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from tph_system.models import Staff

from .applying import apply_plan, rollback_plan
from .gsheet import KIND_CENTER, Tab
from .importer import apply_mappings, run_import
from .models import PhotoOrder, StaffAlias, Venue
from .parsers import clean_people, same_people, split_people
from .planning import collect, fixed_parts
from .sheetwrite import ALREADY, CONFLICT, process
from .test_applying import ApplyBase, MON, TUE
from .test_import import SHEETS, TODAY, FakeSheets
from .test_parsers import LL_HEADER, WINDOW
from .test_sheetwrite import SheetEnv
from .sheetrows import parse_rows
from .views import _unmatched


class SplitPeopleTests(SimpleTestCase):
    def test_plus_comma_and_lowercase_and_separate_people(self):
        self.assertEqual(split_people('Роман + Лиза Гужвенко'), ['Роман', 'Лиза Гужвенко'])
        self.assertEqual(split_people('Роман+Лиза'), ['Роман', 'Лиза'])
        self.assertEqual(split_people('ДИНА , ЮРА'), ['ДИНА', 'ЮРА'])
        self.assertEqual(split_people('pchelovek и Тигран'), ['pchelovek', 'Тигран'])
        self.assertEqual(split_people('Роман + Лиза + Дина'), ['Роман', 'Лиза', 'Дина'])

    def test_trailing_plus_is_a_mark_in_the_table_not_a_second_person(self):
        for cell in ('Екатерина Львова+ - -', 'Елизавета Гужвенко +', 'Эльдар + - -', 'Катя Ш+ - -', 'Сергей+'):
            self.assertEqual(len(split_people(cell)), 1, cell)
        self.assertEqual(split_people('Екатерина Львова+ - -'), ['Екатерина Львова'])

    def test_initials_phones_links_and_empty_cells(self):
        self.assertEqual(split_people('Даша И'), ['Даша И'])                      # «И» - первая буква фамилии
        self.assertEqual(split_people('Дина 89180158874'), ['Дина'])
        self.assertEqual(split_people('Дина +7 918 015-88-74'), ['Дина'])
        self.assertEqual(len(split_people('Е https://vk.com/totorokate')), 1)       # ссылка не превращается в несколько «имён»
        self.assertEqual(split_people(''), [])
        self.assertEqual(split_people(' + - '), [])
        self.assertEqual(split_people('Лиза + лиза  +  ЛИЗА'), ['Лиза'])           # повторы убираются

    def test_clean_and_compare(self):
        self.assertEqual(clean_people('Роман+  Лиза Гужвенко +'), 'Роман + Лиза Гужвенко')
        self.assertEqual(clean_people('Иван Петров 89688649620'), 'Иван Петров')
        self.assertTrue(same_people('Лиза Гужвенко + Роман', 'роман + лиза гужвенко'))
        self.assertFalse(same_people('Роман + Лиза', 'Роман'))
        self.assertFalse(same_people('Роман + Лиза', 'Роман + Дина'))

    def test_the_sheet_parser_keeps_both_names(self):
        rows = [LL_HEADER, ['22.10', '10:00-11:00', 'Г1', 'Заказчик', '', '', '', '', '', 'Катерина 89688649620 Роман + Лиза Гужвенко'],
                ['22.10', '12:00-13:00', 'Г2', 'Заказчик 2', '', '', '', '', '', 'Дина+ - -']]
        res = parse_rows(KIND_CENTER, rows, TODAY, *WINDOW, manager='Катерина')
        self.assertEqual([o.photographer for o in res.orders], ['Роман + Лиза Гужвенко', 'Дина'])


def row(n, cell):
    return ['22.10', f'{9 + n}:00-{9 + n}:30', f'Г{n}', f'Заказчик {n}', '', '', '', '', '', cell]


@override_settings(SCHAUTO_SHEET_IDS=SHEETS)
class TeamImportTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ')
        self.ivan = Staff.objects.create(f_name='Петров', name='Иван', date_empl='2026-01-01')
        self.liza = Staff.objects.create(f_name='Гужвенко', name='Лиза', date_empl='2026-01-01')
        self.fake = FakeSheets()
        self.fake.tabs['LL'] = [Tab('ГАГАРИНСКИЙ', 1, KIND_CENTER, 'ГАГАРИНСКИЙ')]
        self.fake.tabs['JJ'] = []

    def load(self, *cells):
        self.fake.rows[1] = [LL_HEADER] + [row(i + 1, cell) for i, cell in enumerate(cells)]
        return run_import(brands=('LL',), today=TODAY, lister=self.fake.lister, fetcher=self.fake.fetcher)

    def order(self, n=1):
        return PhotoOrder.objects.get(sheet_row=n + 1)

    def team(self, n=1):
        return set(self.order(n).photographers.all())

    def test_two_matched_people_become_a_team(self):
        self.load('Иван Петров + Лиза Гужвенко')
        o = self.order()
        self.assertEqual((o.photographer, o.photographer_raw, o.status), (None, 'Иван Петров + Лиза Гужвенко', 'assigned'))
        self.assertEqual(self.team(), {self.ivan, self.liza})
        self.assertTrue(o.people_matched)
        self.assertEqual(o.people, ['Иван Петров', 'Лиза Гужвенко'])

    def test_one_person_still_lives_in_the_photographer_field(self):
        self.load('Иван Петров', 'Иван Петров+ - -', 'Лиза Гужвенко +')
        for n, expected in ((1, self.ivan), (2, self.ivan), (3, self.liza)):
            o = self.order(n)
            self.assertEqual((o.photographer, o.photographer_raw, self.team(n)), (expected, str(expected), set()))

    def test_only_the_unknown_name_is_unmatched_and_it_can_be_mapped_later(self):
        self.load('Иван Петров + Роман')
        o = self.order()
        self.assertEqual((o.photographer, o.photographer_raw, o.people_matched), (None, 'Иван Петров + Роман', False))
        self.assertEqual(self.team(), {self.ivan})                                    # известный человек уже занят
        names, _ = _unmatched()
        self.assertEqual({key: cnt for key, (_, cnt) in names.items()}, {'роман': 1})   # к сопоставлению - только Роман
        roman = Staff.objects.create(f_name='Орлов', name='Роман', date_empl='2026-01-01')
        StaffAlias.objects.create(alias='роман', staff=roman)
        self.assertEqual(apply_mappings(), 1)
        self.assertEqual(self.team(), {self.ivan, roman})
        self.assertTrue(self.order().people_matched)
        self.assertEqual(apply_mappings(), 0)                                          # повтор ничего не меняет
        self.assertEqual(_unmatched()[0], {})

    def test_ignored_name_drops_out_and_the_order_has_one_photographer_again(self):
        StaffAlias.objects.create(alias='штат', staff=None)
        self.load('Иван Петров + штат')
        o = self.order()
        self.assertEqual((o.photographer, o.photographer_raw, self.team()), (self.ivan, 'Иван Петров', set()))

    def test_mapping_screen_saves_one_name_of_a_pair(self):
        self.load('Иван Петров + Роман', 'Роман + Дина')
        user = User.objects.create(username='boss', is_superuser=True)
        self.client.force_login(user)
        roman = Staff.objects.create(f_name='Орлов', name='Роман', date_empl='2026-01-01')
        page = self.client.get(reverse('schauto:mapping'))
        self.assertContains(page, 'Роман')
        self.assertNotContains(page, 'Иван Петров + Роман')                             # пара не показывается одной строкой
        self.client.post(reverse('schauto:mapping_person'), {'alias': 'Роман', 'staff': roman.pk})
        self.assertEqual(self.team(1), {self.ivan, roman})
        self.assertEqual(self.team(2), {roman})                                         # «Дина» ещё не сопоставлена
        self.assertEqual(set(_unmatched()[0]), {'дина'})

    def test_reimport_follows_the_cell_and_never_duplicates(self):
        self.load('Иван Петров + Лиза Гужвенко')
        self.load('Иван Петров + Лиза Гужвенко')
        self.assertEqual(PhotoOrder.photographers.through.objects.count(), 2)
        self.load('Лиза Гужвенко')                                                        # второго из ячейки убрали
        o = self.order()
        self.assertEqual((o.photographer, self.team()), (self.liza, set()))
        self.load('Лиза Гужвенко + Иван Петров')                                          # снова двое, порядок другой
        self.assertEqual((self.order().photographer, self.team()), (None, {self.ivan, self.liza}))
        self.load('')                                                                     # ячейку очистили
        self.assertEqual((self.order().status, self.order().photographer_raw, self.team()), ('open', '', set()))
        self.assertEqual(PhotoOrder.photographers.through.objects.count(), 0)

    def test_many_orders_in_one_load(self):
        self.load(*['Иван Петров + Лиза Гужвенко'] * 5, 'Иван Петров', '')
        self.assertEqual(PhotoOrder.photographers.through.objects.count(), 10)
        self.assertEqual(PhotoOrder.objects.filter(photographers=self.liza).distinct().count(), 5)

    def test_orders_page_shows_staff_names_and_marks_unknown_ones(self):
        self.load('Иван Петров + Лиза Гужвенко', 'Иван Петров + Роман')
        self.client.force_login(User.objects.create(username='boss', is_superuser=True))
        page = self.client.get(reverse('schauto:orders') + '?date_from=01.10.2026')
        self.assertContains(page, f'{self.ivan} + {self.liza}')
        self.assertContains(page, 'Не все имена сопоставлены с сотрудниками')


class TeamPlanningTests(ApplyBase):
    def team_order(self, day=MON, members=None, slots=None, **kw):
        members = members or [self.s1, self.s2]
        o = self.order(self.a, day, time(10), time(15), status=PhotoOrder.STATUS_ASSIGNED, slots=slots or [['10:00', '11:00'], ['14:00', '15:00']],
                       photographer_raw=' + '.join(str(s) for s in members), **kw)
        o.photographers.set(members)
        return o

    def test_each_member_is_busy_during_every_part_but_free_in_the_break(self):
        self.team_order()
        fixed, unknown = fixed_parts(MON, MON, [self.s1.pk, self.s2.pk])
        self.assertEqual(sorted((sid, p.part_no) for sid, p in fixed), [(self.s1.pk, 1), (self.s1.pk, 2), (self.s2.pk, 1), (self.s2.pk, 2)])
        self.assertEqual(unknown, 0)
        self.assertEqual(fixed_parts(MON, MON, [self.s2.pk])[0].__len__(), 2)

    def test_a_name_that_is_not_matched_at_all_is_still_unknown(self):
        self.order(self.a, MON, time(10), time(11), status=PhotoOrder.STATUS_ASSIGNED, photographer_raw='Роман + Дина')
        fixed, unknown = fixed_parts(MON, MON, [self.s1.pk])
        self.assertEqual((fixed, unknown), ([], 1))

    def test_one_known_member_is_enough_to_account_for_the_order(self):
        o = self.order(self.a, MON, time(10), time(11), status=PhotoOrder.STATUS_ASSIGNED, photographer_raw=f'{self.s1} + Роман')
        o.photographers.set([self.s1])
        fixed, unknown = fixed_parts(MON, MON, [self.s1.pk, self.s2.pk])
        self.assertEqual(([sid for sid, _ in fixed], unknown), ([self.s1.pk], 0))

    def test_the_plan_does_not_put_a_member_on_another_order_at_the_same_time(self):
        self.team_order(members=[self.s1, self.s2])
        open_order = self.order(self.a, MON, time(10, 15), time(10, 45))
        run = self.make_plan()
        a = run.assignments.get(order=open_order)
        self.assertIsNone(a.staff)                                                     # оба заняты съёмкой «вдвоём»
        data = collect(MON, MON)
        self.assertEqual(len(data.fixed), 4)

    def test_a_member_is_free_during_the_break(self):
        self.team_order(members=[self.s1])
        Staff.objects.filter(pk=self.s2.pk).update(dism_status='Уволен')
        in_the_break = self.order(self.a, MON, time(12), time(13))
        run = self.make_plan()
        self.assertEqual(run.assignments.get(order=in_the_break).staff, self.s1)

    def test_the_daily_limit_counts_a_team_order_for_every_member(self):
        self.team_order()
        data = collect(MON, MON)
        self.assertEqual({sid for sid, _ in data.fixed}, {self.s1.pk, self.s2.pk})

    def test_familiarity_counts_team_orders_of_earlier_days(self):
        self.team_order(day=MON)
        data = collect(TUE, TUE)
        self.assertEqual(data.familiarity.get((self.s1.pk, self.a.pk)), 1)
        self.assertEqual(data.familiarity.get((self.s2.pk, self.a.pk)), 1)


class TeamApplyTests(ApplyBase):
    def split_order(self):
        o = self.order(self.a, MON, time(10), time(15), slots=[['10:00', '11:00'], ['14:00', '15:00']])
        self.mark(self.s1, MON, 'Работает', 'до 12:00'), self.mark(self.s2, MON, 'Работает', 'с 13:00')
        return o

    def test_apply_writes_both_names_with_a_plus_and_remembers_the_team(self):
        calls = self.patch_sheets()
        o = self.split_order()
        run = self.make_plan()
        self.assertTrue(apply_plan(run, self.user).ok)
        self.assertEqual(calls[1][2][o.pk], f'{self.s1} + {self.s2}')
        o.refresh_from_db()
        self.assertEqual((o.status, o.photographer, o.photographer_raw), ('assigned', None, f'{self.s1} + {self.s2}'))
        self.assertEqual(set(o.photographers.all()), {self.s1, self.s2})
        self.assertEqual(o.people, [str(self.s1), str(self.s2)])

    def test_rollback_empties_the_team(self):
        self.patch_sheets()
        o = self.split_order()
        run = self.make_plan()
        apply_plan(run, self.user)
        self.assertTrue(rollback_plan(run, self.user).ok)
        o.refresh_from_db()
        self.assertEqual((o.status, o.photographer_raw, o.photographers.count()), ('open', '', 0))

    def test_one_photographer_order_does_not_get_a_team(self):
        self.patch_sheets()
        o = self.order(self.a, MON, time(10), time(11))
        apply_plan(self.make_plan(), self.user)
        o.refresh_from_db()
        self.assertEqual((o.photographer is not None, o.photographers.count()), (True, 0))

    def test_precise_parts_of_an_applied_order_beat_the_conservative_rule(self):
        self.patch_sheets()
        self.split_order()
        run = self.make_plan()
        apply_plan(run, self.user)
        fixed, _ = fixed_parts(MON, MON, [self.s1.pk, self.s2.pk])
        self.assertEqual(sorted((sid, p.part_no) for sid, p in fixed), [(self.s1.pk, 1), (self.s2.pk, 2)])


class TeamSheetWriteTests(SheetEnv):
    def test_the_same_people_in_any_order_are_already_there_and_others_are_a_conflict(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        self.ll.rows[2][9] = 'Лиза Гужвенко + Иван Петров'
        same = process(self.items(o, name='Иван Петров + Лиза Гужвенко'), write=False, client=self.client)
        self.assertEqual(same[o.pk].status, ALREADY)
        other = process(self.items(o, name='Иван Петров + Дина Другая'), write=False, client=self.client)
        self.assertEqual(other[o.pk].status, CONFLICT)

    def test_two_names_are_written_after_the_manager(self):
        o = self.order(tab_name='ГАГАРИНСКИЙ', sheet_row=2)
        result = process(self.items(o, name='Иван Петров + Лиза Гужвенко'), write=True, client=self.client)
        self.assertEqual(self.ll.rows[1][9], 'Катерина 89688649620 Иван Петров + Лиза Гужвенко')
        self.assertEqual(result[o.pk].after, 'Катерина 89688649620 Иван Петров + Лиза Гужвенко')
