from datetime import date, time
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from tph_system.models import ImplEvents, Salary, Sales, Schedule, Staff, Store, WorkVacSchedule

from . import sheetwrite
from .applying import (PlanNotDeletable, allowed_staff, apply_plan, delete_plan, rollback_plan, save_confirmations, save_edits,
                       validate_plan)
from .gsheet import SheetError
from .importer import run_import
from .models import Assignment, PhotoOrder, PlanRun, Route, Venue
from .planner import PlannerConfig, PlanPart, find_conflicts
from .planning import fixed_parts, run_plan
from .sheetwrite import CONFLICT, ERROR, NOT_FOUND, READY, RET_OTHER, REVERTED, WRITTEN, SheetResult
from .test_import import SHEETS, TODAY, FakeSheets
from .test_planning import MON, TUE, PlanningBase
from .test_sheetwrite import JJ_ROWS, LL_ROWS, MANAGER, FakeClient, FakeWorksheet


def mk_part(order_id, start, end, venue=1, day=MON, part_no=1):
    return PlanPart(key=f'{order_id}:{part_no}', order_id=order_id, date=day, start=round(start * 60), end=round(end * 60),
                    work_minutes=round((end - start) * 60),
                    venue_id=venue, venue_name=f'Центр {venue}', venue_difficulty=5, part_no=part_no)


class FindConflictsTests(TestCase):
    def travel(self, a, b):
        return {(1, 2): 20, (2, 1): 20}.get((a, b))

    def test_clean_day_has_no_conflicts(self):
        planned = [(1, mk_part(1, 10, 11, venue=1)), (1, mk_part(2, 12, 13, venue=2))]
        self.assertEqual(find_conflicts(planned, [], self.travel), {})

    def test_overlap_and_short_gap_are_reported_for_the_planned_part(self):
        planned = [(1, mk_part(1, 10, 12, venue=1)), (1, mk_part(2, 11, 13, venue=1)), (2, mk_part(3, 10, 11, venue=1)),
                   (2, mk_part(4, 11.25, 12, venue=2))]
        problems = find_conflicts(planned, [], self.travel)
        self.assertIn('занят в это время', problems['1:1'])
        self.assertIn('занят в это время', problems['2:1'])
        self.assertIn('не успеет', problems['3:1'] + problems.get('4:1', ''))
        self.assertTrue({'3:1', '4:1'} & set(problems))

    def test_manual_assignments_are_compared_with_but_not_blamed(self):
        manual = [(1, mk_part(9, 10, 12, venue=1)), (1, mk_part(8, 11, 13, venue=1))]   # налезают друг на друга
        planned = [(1, mk_part(1, 14, 15, venue=1))]
        self.assertEqual(find_conflicts(planned, manual, self.travel), {})
        clash = [(1, mk_part(2, 11.5, 12.5, venue=1))]
        self.assertIn('2:1', find_conflicts(clash, manual, self.travel))

    def test_default_travel_time_for_unknown_route(self):
        planned = [(1, mk_part(1, 10, 11, venue=1)), (1, mk_part(2, 12, 13, venue=3))]   # маршрута 1->3 нет, 90 + 15 > 60
        self.assertIn('2:1', find_conflicts(planned, [], self.travel, PlannerConfig(default_travel_min=90)))

    def test_parts_of_one_order_need_no_gap(self):
        planned = [(1, mk_part(1, 10, 11, venue=1, part_no=1)), (1, mk_part(1, 11, 12, venue=1, part_no=2))]
        self.assertEqual(find_conflicts(planned, [], self.travel), {})


class ApplyBase(PlanningBase):
    def setUp(self):
        super().setUp()
        self.store = Store.objects.create(name='Центр А', short_name='LLA', store_status='Действующая')
        Venue.objects.filter(pk=self.a.pk).update(store=self.store)

    def patch_sheets(self, preflight=None, final=None, access_error=None, write_error=None, revert_results=None, revert_error=None):
        """Подмена записи в таблицы: calls - список (write, [id заказов], {id: что вписывать}); откат пишет в self.revert_calls"""
        calls = []
        self.revert_calls = []
        self.retoucher_values = {}

        class FakePrepared:
            def __init__(self, items, results):
                self.items, self.results = items, results

        def prepare(items, *, client=None):
            calls.append((False, [i.order.pk for i in items], {i.order.pk: i.value for i in items}))
            if access_error:
                raise access_error
            table = preflight or {}
            return FakePrepared(items, {i.order.pk: table.get(i.order.pk) or SheetResult(READY, ret_status=READY if i.retoucher_value else '')
                                        for i in items})

        def commit(prepared):
            items = prepared.items
            calls.append((True, [i.order.pk for i in items], {i.order.pk: i.value for i in items}))
            self.retoucher_values.update({i.order.pk: i.retoucher_value for i in items})
            if write_error:
                raise write_error
            table = final or {}
            return {i.order.pk: table.get(i.order.pk) or SheetResult(
                WRITTEN, before='', after=i.value, ret_status=WRITTEN if i.retoucher_value else '', ret_after=i.retoucher_value)
                    for i in items}

        def revert(items, *, write, client=None, today=None):
            self.revert_calls.append((write, [i.order.pk for i in items], {i.order.pk: (i.value, i.before, i.after) for i in items}))
            if revert_error:
                raise revert_error
            return {i.order.pk: (revert_results or {}).get(i.order.pk) or SheetResult(REVERTED, ret_status=REVERTED if i.ret_after else '')
                    for i in items}

        mock.patch('schauto.sheetwrite.prepare', side_effect=prepare).start()
        mock.patch('schauto.sheetwrite.commit', side_effect=commit).start()
        mock.patch('schauto.sheetwrite.revert', side_effect=revert).start()
        self.addCleanup(mock.patch.stopall)
        return calls

    def only_ivan(self):
        Staff.objects.filter(pk=self.s2.pk).update(dism_status='Уволен')

    def assignment(self, run, order, part_no=1):
        return run.assignments.get(order=order, part_no=part_no)

    def tight_pair(self):
        """Два заказа одному фотографу: А 10:00-11:00 и Б 11:10-12:00; А -> Б минимум 25 + запас 15 = 40, есть 10: не хватает 30"""
        first, second = self.order(self.a, MON, time(10), time(11)), self.order(self.b, MON, time(11, 10), time(12))
        run = self.make_plan()
        a1, a2 = self.assignment(run, first), self.assignment(run, second)
        save_edits(run, {a2.pk: a1.staff_id})
        return run, a1, a2

    def tight_pair_with_tuesday(self):
        first, second = self.order(self.a, MON, time(10), time(11)), self.order(self.b, MON, time(11, 10), time(12))
        third = self.order(self.a, TUE, time(10), time(11))
        run = self.make_plan()
        a1, a2, a3 = self.assignment(run, first), self.assignment(run, second), self.assignment(run, third)
        save_edits(run, {a2.pk: a1.staff_id})
        self.mark(a3.staff, TUE, 'Работает', 'с 10:15')                                   # не хватает 15 минут
        return run, a1, a2


class ValidationTests(ApplyBase):
    def test_clean_plan_passes(self):
        self.order(self.a, MON, time(10), time(11))
        check = validate_plan(self.make_plan())
        self.assertTrue(check.ok, check)
        self.assertEqual(check.checked, 1)

    def test_part_without_photographer_blocks(self):
        o = self.order(self.a, MON, time(10), time(11))
        self.mark(self.s1, MON, 'Отпуск'), self.mark(self.s2, MON, 'Отгул')
        run = self.make_plan()
        check = validate_plan(run)
        self.assertFalse(check.ok)
        self.assertEqual(check.row_errors[self.assignment(run, o).pk], ['не назначен фотограф'])

    def test_manual_choice_of_a_person_who_does_not_work_that_day_is_rejected(self):
        o = self.order(self.a, MON, time(10), time(11))
        self.mark(self.s1, MON, 'Отпуск')
        run = self.make_plan()
        a = self.assignment(run, o)
        self.assertEqual(a.staff, self.s2)
        self.mark(self.s2, MON, 'Больничный')
        save_edits(run, {a.pk: self.s1.pk})
        errors = validate_plan(run).row_errors[a.pk]
        self.assertEqual(len(errors), 1)
        self.assertIn('не работает в этот день', errors[0])
        self.assertIn('Отпуск', errors[0])

    def test_absence_added_after_the_calculation_blocks_but_removing_a_record_does_not(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        WorkVacSchedule.objects.filter(staff=a.staff, date=MON).delete()          # записи нет - ставить можно
        self.assertTrue(validate_plan(run).ok)
        self.mark(a.staff, MON, 'Отпуск')
        errors = ' '.join(validate_plan(run).row_errors[a.pk])
        self.assertIn('не работает в этот день', errors)
        self.assertIn('«Отпуск»', errors)

    def test_time_window_from_the_schedule_must_cover_the_order(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        self.mark(a.staff, MON, 'Работает', 'с 15:00')
        check = validate_plan(run)
        self.assertFalse(check.ok)
        self.assertEqual(check.blocking_count, 0)                      # не блокирует, а ждёт подтверждения
        problem = check.row_soft[a.pk][0]
        self.assertIn('по графику доступен 15:00-24:00', problem.text)
        self.assertEqual((problem.kind, problem.shortfall), ('window', 300))

    def test_photographer_must_make_it_between_orders(self):
        first = self.order(self.a, MON, time(10), time(11))
        second = self.order(self.b, MON, time(11, 10), time(12))     # А -> Б минимум 25 + буфер 15, а есть 10
        run = self.make_plan()
        a1, a2 = self.assignment(run, first), self.assignment(run, second)
        self.assertNotEqual(a1.staff, a2.staff)                       # расчёт разводит их сам
        save_edits(run, {a2.pk: a1.staff_id})                         # руководитель отдаёт оба одному
        check = validate_plan(run)
        self.assertFalse(check.ok)
        self.assertEqual(check.blocking_count, 0)                      # подтвердить может руководитель: вдруг успеет
        texts = [p.text for p in check.row_soft.get(a1.pk, []) + check.row_soft.get(a2.pk, [])]
        self.assertTrue(any('не успевает' in t or 'не успеет' in t for t in texts), texts)

    def test_overlap_with_an_order_set_manually_in_the_table(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        self.order(self.a, MON, time(10, 30), time(11, 30), status=PhotoOrder.STATUS_ASSIGNED, photographer=a.staff)   # вписали позже
        self.assertIn('занят в это время', ' '.join(validate_plan(run).row_errors[a.pk]))

    def test_order_changed_or_taken_since_the_calculation_blocks(self):
        moved, taken = self.order(self.a, MON, time(10), time(11)), self.order(self.a, TUE, time(10), time(11))
        run = self.make_plan()
        PhotoOrder.objects.filter(pk=moved.pk).update(time_start=time(12), time_end=time(13), slots=[['12:00', '13:00']])
        PhotoOrder.objects.filter(pk=taken.pk).update(status=PhotoOrder.STATUS_ASSIGNED)
        check = validate_plan(run)
        self.assertIn('изменились после расчёта', check.row_errors[self.assignment(run, moved).pk][0])
        self.assertIn('уже не ждёт исполнителя', check.row_errors[self.assignment(run, taken).pk][0])

    def test_exceeding_the_daily_limit_blocks(self):
        orders = [self.order(self.a, MON, time(9 + 3 * i), time(10 + 3 * i)) for i in range(3)]
        Staff.objects.filter(pk=self.s2.pk).update(dism_status='Уволен')     # все три - Иванову, лимит у него 3
        Staff.objects.filter(pk=self.s1.pk).update(max_orders_per_day=3)
        run = self.make_plan()
        self.assertTrue(validate_plan(run).ok)
        Staff.objects.filter(pk=self.s1.pk).update(max_orders_per_day=2)     # лимит уменьшили
        check = validate_plan(run)
        self.assertFalse(check.ok)
        self.assertEqual(len(check.row_errors), 3)
        self.assertIn('3 заказов при лимите 2', check.row_errors[self.assignment(run, orders[0]).pk][0])

    def test_orders_set_manually_in_the_table_count_towards_the_limit(self):
        planned = self.order(self.a, MON, time(15), time(16))
        run = self.make_plan()
        a = self.assignment(run, planned)
        Staff.objects.filter(pk=a.staff_id).update(max_orders_per_day=2)
        for hour in (9, 11):                                                  # вручную вписали ещё два заказа
            self.order(self.a, MON, time(hour), time(hour + 1), status=PhotoOrder.STATUS_ASSIGNED, photographer=a.staff)
        errors = validate_plan(run).row_errors[a.pk]
        self.assertEqual(len(errors), 1)
        self.assertIn('3 заказов при лимите 2', errors[0])

    def test_the_limit_is_per_day(self):
        first, second = self.order(self.a, MON, time(10), time(11)), self.order(self.a, TUE, time(10), time(11))
        Staff.objects.filter(pk=self.s2.pk).update(dism_status='Уволен')
        Staff.objects.filter(pk=self.s1.pk).update(max_orders_per_day=1)
        self.assertTrue(validate_plan(self.make_plan()).ok)

    def test_order_split_between_photographers_is_a_warning(self):
        o = self.order(self.a, MON, time(10), time(15), slots=[['10:00', '11:00'], ['14:00', '15:00']])
        self.mark(self.s1, MON, 'Работает', 'до 12:00'), self.mark(self.s2, MON, 'Работает', 'с 13:00')
        run = self.make_plan()
        check = validate_plan(run)
        self.assertTrue(check.ok, check)
        self.assertIn('разделён между фотографами', check.row_warnings[self.assignment(run, o).pk][0])

    def test_done_parts_are_not_checked_again(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        Assignment.objects.filter(order=o).update(sheet_status='written')
        check = validate_plan(run)
        self.assertEqual(check.errors, ['Нечего применять: все части уже вписаны в таблицу'])


class ConfirmationTests(ApplyBase):
    """Проблемы «не хватает минут на дорогу» и «вне времени из графика» руководитель может подтвердить вручную"""

    def confirm_all(self, run):
        sigs = list(validate_plan(run).unconfirmed)
        return save_confirmations(run, self.user, shown=sigs, ticked=sigs)

    def test_a_tight_gap_is_one_confirmable_problem_shown_in_both_rows(self):
        run, a1, a2 = self.tight_pair()
        check = validate_plan(run)
        self.assertEqual((check.blocking_count, len(check.row_soft), len(check.unconfirmed)), (0, 2, 1))   # две строки, одна проблема
        problem = next(iter(check.unconfirmed.values()))
        self.assertEqual((problem.kind, problem.shortfall), ('gap', 30))
        self.assertIn('не хватает 30 мин', problem.text)
        self.assertEqual(check.error_count, 1)

    def test_apply_is_refused_until_the_problem_is_confirmed(self):
        calls = self.patch_sheets()
        run, a1, a2 = self.tight_pair()
        result = apply_plan(run, self.user)
        self.assertEqual((result.ok, result.stage), (False, 'validation'))
        self.assertIn('ждут вашего подтверждения 1', result.message)
        self.assertNotIn('блокирующих', result.message)
        self.assertEqual(calls, [])
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply', status='Бизнес ошибка').exists())

    def test_confirmed_plan_passes_is_applied_as_is_and_leaves_a_trail(self):
        calls = self.patch_sheets()
        run, a1, a2 = self.tight_pair()
        done = self.confirm_all(run)
        self.assertEqual((done.confirmed, done.revoked), (1, 0))
        check = validate_plan(run)
        self.assertTrue(check.ok)
        self.assertEqual((len(check.row_confirmed), len(check.confirmed)), (2, 1))         # видно в обеих строках, считается один раз
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Confirm', event_message__contains='не хватает 30 мин').exists())

        checked = apply_plan(run, self.user, only_check=True)
        self.assertTrue(checked.ok)
        self.assertIn('с подтверждёнными вручную проблемами: 1', checked.message)
        self.assertTrue(any('Подтверждено вручную (boss' in n and 'не хватает 30 мин' in n for n in checked.notes), checked.notes)

        result = apply_plan(run, self.user)
        self.assertTrue(result.ok, result.message)
        self.assertIn('применено с подтверждёнными вручную проблемами: 1', result.message)
        self.assertEqual([write for write, *_ in calls], [False, False, True])                # проверка, проверка при применении, запись
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')
        entry = run.apply_log[-1]
        self.assertEqual(len(entry['confirmed']), 1)
        self.assertIn('не хватает 30 мин', entry['confirmed'][0]['text'])
        self.assertEqual(entry['confirmed'][0]['by'], 'boss')
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply', status='Успешно',
                                                  event_message__contains='Подтверждено вручную').exists())

    def test_one_confirmation_covers_both_orders_and_unticking_takes_it_back(self):
        run, a1, a2 = self.tight_pair()
        self.confirm_all(run)
        sig = next(iter(validate_plan(run).confirmed))
        self.assertEqual(save_confirmations(run, self.user, shown=[sig, sig], ticked=[]).revoked, 1)   # снята с любой из двух строк
        check = validate_plan(run)
        self.assertEqual((check.ok, len(check.unconfirmed), len(check.confirmed)), (False, 1, 0))
        self.assertEqual(run.confirmed, {})

    def test_ticked_in_one_row_is_enough_when_the_other_row_is_not_ticked(self):
        run, a1, a2 = self.tight_pair()
        sig = next(iter(validate_plan(run).unconfirmed))
        save_confirmations(run, self.user, shown=[sig, sig], ticked=[sig])       # в одной строке отмечено, в другой нет
        self.assertTrue(validate_plan(run).ok)

    def test_confirmation_is_void_when_the_situation_changes(self):
        run, a1, a2 = self.tight_pair()
        self.confirm_all(run)
        self.assertTrue(validate_plan(run).ok)
        PlanRun.objects.filter(pk=run.pk).update(config={**run.config, 'buffer_min': 20})      # запас вырос -> нехватка уже 35
        run.refresh_from_db()
        check = validate_plan(run)
        self.assertFalse(check.ok)
        self.assertEqual(next(iter(check.unconfirmed.values())).shortfall, 35)
        self.assertEqual(len(check.confirmed), 0)

    def test_changing_the_photographer_removes_the_problem(self):
        run, a1, a2 = self.tight_pair()
        other = self.s2 if a1.staff == self.s1 else self.s1
        save_edits(run, {a2.pk: other.pk})
        self.assertTrue(validate_plan(run).ok)

    def test_overlap_cannot_be_confirmed(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        self.order(self.a, MON, time(10, 30), time(11, 30), status=PhotoOrder.STATUS_ASSIGNED, photographer=a.staff)
        check = validate_plan(run)
        self.assertEqual((check.blocking_count, len(check.unconfirmed)), (1, 0))
        done = save_confirmations(run, self.user, shown=['overlap'], ticked=['overlap'], upto=600)
        self.assertEqual(done.confirmed, 0)
        self.assertFalse(validate_plan(run).ok)
        self.assertIn('занят в это время', validate_plan(run).row_errors[a.pk][0])

    def test_absence_and_daily_limit_cannot_be_confirmed(self):
        orders = [self.order(self.a, MON, time(9 + 3 * i), time(10 + 3 * i)) for i in range(3)]
        Staff.objects.filter(pk=self.s2.pk).update(dism_status='Уволен')
        run = self.make_plan()
        Staff.objects.filter(pk=self.s1.pk).update(max_orders_per_day=2)
        self.mark(self.s1, TUE, 'Отпуск')
        check = validate_plan(run)
        self.assertEqual((len(check.row_errors), len(check.unconfirmed)), (3, 0))
        save_confirmations(run, self.user, upto=600)
        self.assertFalse(validate_plan(run).ok)

    def test_foreign_and_forged_signatures_are_ignored(self):
        run, a1, a2 = self.tight_pair()
        done = save_confirmations(run, self.user, shown=['gap|1|9:9|9:8|50|10'], ticked=['gap|1|9:9|9:8|50|10', 'window|1|2026-10-26|1-2|abc'])
        self.assertEqual(done.confirmed, 0)
        self.assertEqual(run.confirmed, {})
        self.assertFalse(ImplEvents.objects.filter(event_type='Schauto_Plan_Confirm').exists())

    def test_schedule_window_mismatch_can_be_confirmed_and_the_schedule_text_is_part_of_the_signature(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        self.mark(a.staff, MON, 'Работает', 'с 10:10')                                    # заказ начинается на 10 минут раньше
        problem = validate_plan(run).row_soft[a.pk][0]
        self.assertEqual((problem.kind, problem.shortfall), ('window', 10))
        self.confirm_all(run)
        self.assertTrue(validate_plan(run).ok)
        self.mark(a.staff, MON, 'Работает', 'с 10:20')                                    # график изменили - подтверждение не действует
        check = validate_plan(run)
        self.assertEqual((check.ok, next(iter(check.unconfirmed.values())).shortfall), (False, 20))

    def test_window_shortfall_counts_both_sides_and_the_nearest_window(self):
        o = self.order(self.a, MON, time(10), time(12))
        run = self.make_plan()
        a = self.assignment(run, o)
        self.mark(a.staff, MON, 'Работает', '10:30-11:30')                                # внутри заказа: 30 + 30 мин снаружи
        self.assertEqual(validate_plan(run).row_soft[a.pk][0].shortfall, 60)
        self.mark(a.staff, MON, 'Работает', 'Занят 11:00-13:00')                          # свободен до 11:00: заказ вылезает на час
        self.assertEqual(validate_plan(run).row_soft[a.pk][0].shortfall, 60)

    def test_confirm_everything_up_to_a_number_of_minutes(self):
        run, a1, a2 = self.tight_pair_with_tuesday()          # пара заказов (не хватает 30) и заказ вне времени из графика (не хватает 15)
        check = validate_plan(run)
        self.assertEqual(sorted(p.shortfall for p in check.unconfirmed.values()), [15, 30])
        self.assertEqual(save_confirmations(run, self.user, upto=20).confirmed, 1)         # только то, где не хватает не больше 20
        self.assertEqual([p.shortfall for p in validate_plan(run).unconfirmed.values()], [30])
        self.assertEqual(save_confirmations(run, self.user, upto=20).confirmed, 0)
        self.assertEqual(save_confirmations(run, self.user, upto=30).confirmed, 1)
        self.assertTrue(validate_plan(run).ok)

    def test_applied_run_cannot_be_confirmed_any_more(self):
        self.patch_sheets()
        run, a1, a2 = self.tight_pair()
        self.confirm_all(run)
        self.assertTrue(apply_plan(run, self.user).ok)
        with self.assertRaises(ValueError):
            save_confirmations(run, self.user, upto=600)

    def test_unconfirmed_problem_is_listed_even_if_another_one_is_confirmed(self):
        run, a1, a2 = self.tight_pair_with_tuesday()
        save_confirmations(run, self.user, upto=15)
        check = validate_plan(run)
        self.assertEqual((check.ok, len(check.confirmed), len(check.unconfirmed)), (False, 1, 1))
        result = apply_plan(run, self.user, only_check=True)
        self.assertIn('ждут вашего подтверждения 1', result.message)


class SaveEditsTests(ApplyBase):
    def test_changes_staff_and_logs(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        other = self.s2 if a.staff == self.s1 else self.s1
        self.assertEqual(save_edits(run, {a.pk: other.pk}), 1)
        a.refresh_from_db()
        self.assertEqual((a.staff, a.auto_staff, a.edited), (other, self.s1 if other == self.s2 else self.s2, True))
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Edit', event_message__contains='Правка распределения').exists())
        self.assertEqual(save_edits(run, {a.pk: other.pk}), 0)       # то же самое - не изменение

    def test_only_working_outbound_staff_can_be_chosen(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        regular = self.staff('Штатный', 'Сергей', staff_type='Штат')
        fired = self.staff('Уволенный', 'Олег')
        Staff.objects.filter(pk=fired.pk).update(dism_status='Уволен')
        for who in (regular, fired, 99999):
            self.assertEqual(save_edits(run, {a.pk: getattr(who, 'pk', who)}), 0)
        self.assertNotIn(regular, allowed_staff())
        self.assertIn(self.s1, allowed_staff())

    def test_can_unassign_and_assign_unassigned(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        save_edits(run, {a.pk: None})
        a.refresh_from_db()
        self.assertIsNone(a.staff)
        save_edits(run, {a.pk: self.s2.pk})
        a.refresh_from_db()
        self.assertEqual(a.staff, self.s2)

    def test_applied_runs_and_done_parts_are_locked(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        Assignment.objects.filter(pk=a.pk).update(sheet_status='written')
        self.assertEqual(save_edits(run, {a.pk: self.s2.pk if a.staff == self.s1 else self.s1.pk}), 0)
        PlanRun.objects.filter(pk=run.pk).update(status='applied')
        run.refresh_from_db()
        with self.assertRaises(ValueError):
            save_edits(run, {a.pk: None})


class ApplyTests(ApplyBase):
    def test_validation_failure_changes_nothing_and_does_not_touch_google(self):
        calls = self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        self.mark(self.s1, MON, 'Отпуск'), self.mark(self.s2, MON, 'Отгул')
        run = self.make_plan()
        result = apply_plan(run, self.user)
        self.assertEqual((result.ok, result.stage), (False, 'validation'))
        self.assertEqual(calls, [])
        self.assertEqual(Schedule.objects.count(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply', status='Бизнес ошибка').exists())

    def test_check_only_reads_google_and_writes_nothing(self):
        calls = self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        result = apply_plan(run, self.user, only_check=True)
        self.assertTrue(result.ok, result)
        self.assertIn('Все проверки успешны', result.message)
        self.assertEqual([c[0] for c in calls], [False])
        self.assertEqual(Schedule.objects.count(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')
        self.assertFalse(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply').exists())

    def test_google_access_problem_blocks_before_any_write(self):
        self.patch_sheets(access_error=SheetError('Не настроен доступ к Google: не задана переменная SCHAUTO_GOOGLE_CREDENTIALS_FILE'))
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        result = apply_plan(run, self.user)
        self.assertEqual((result.ok, result.stage), (False, 'sheets_access'))
        self.assertIn('SCHAUTO_GOOGLE_CREDENTIALS_FILE', result.message)
        self.assertEqual(Schedule.objects.count(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')

    def test_conflict_found_by_the_table_precheck_blocks_everything(self):
        o1, o2 = self.order(self.a, MON, time(10), time(11)), self.order(self.a, TUE, time(10), time(11))
        calls = self.patch_sheets(preflight={o1.pk: SheetResult(CONFLICT, 'в таблице уже указан исполнитель: «Даша»')})
        run = self.make_plan()
        result = apply_plan(run, self.user)
        self.assertEqual((result.ok, result.stage), (False, 'sheets_check'))
        self.assertEqual([c[0] for c in calls], [False])             # дошли только до предпроверки
        self.assertIn('Google-таблица: в таблице уже указан исполнитель', result.validation.row_errors[self.assignment(run, o1).pk][0])
        self.assertEqual(Schedule.objects.count(), 0)
        self.assertEqual(run.assignments.exclude(sheet_status='').count(), 0)

    def test_success_writes_sheet_then_schedule_only_for_centers_with_a_store(self):
        calls = self.patch_sheets()
        with_store = self.order(self.a, MON, time(10), time(11))
        without_store = self.order(self.b, MON, time(13), time(14))
        self.only_ivan()
        run = self.make_plan()
        result = apply_plan(run, self.user)
        self.assertTrue(result.ok, result.message)
        self.assertIn('Все проверки успешны, фотографы проставлены в график работы и в Google-таблицы', result.message)
        self.assertEqual([c[0] for c in calls], [False, True])       # сначала предпроверка, потом запись
        self.assertEqual(calls[1][2], {with_store.pk: str(self.s1), without_store.pk: str(self.s1)})

        run.refresh_from_db()
        self.assertEqual((run.status, run.applied_by, len(run.apply_log)), ('applied', self.user, 1))
        self.assertIsNotNone(run.applied_at)
        row = Schedule.objects.get()                                  # только центр с фототочкой
        self.assertEqual((row.staff, row.store, row.date, row.position, row.work_time), (self.s1, self.store, MON, 'Выездной фотограф', '10:00'))
        a1, a2 = self.assignment(run, with_store), self.assignment(run, without_store)
        self.assertEqual((a1.sheet_status, a1.schedule_status, a1.schedule), ('written', 'created', row))
        self.assertEqual((a2.sheet_status, a2.schedule_status, a2.schedule), ('written', 'no_store', None))
        for order in (with_store, without_store):
            order.refresh_from_db()
            self.assertEqual((order.status, order.photographer, order.photographer_raw), ('assigned', self.s1, str(self.s1)))
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply', status='Успешно').exists())

    def test_one_schedule_row_per_day_and_store_with_the_earliest_start(self):
        self.patch_sheets()
        late, early = self.order(self.a, MON, time(14), time(15)), self.order(self.a, MON, time(10), time(11))
        self.only_ivan()
        run = self.make_plan()
        self.assertTrue(apply_plan(run, self.user).ok)
        row = Schedule.objects.get()
        self.assertEqual(row.work_time, '10:00')
        self.assertEqual({self.assignment(run, o).schedule_id for o in (late, early)}, {row.pk})

    def test_existing_schedule_row_is_kept_as_is(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        self.only_ivan()
        Schedule.objects.create(staff=self.s1, store=self.store, date=MON, position='Фотограф', work_time='09:00')
        result = apply_plan(self.make_plan(), self.user)
        self.assertTrue(result.ok)
        row = Schedule.objects.get()
        self.assertEqual((row.position, row.work_time), ('Фотограф', '09:00'))
        self.assertEqual(Assignment.objects.get().schedule_status, 'exists')
        self.assertTrue(any('с ролью «Фотограф»' in n for n in result.notes))

    def test_failed_sheet_write_means_no_schedule_for_that_order_and_retry_finishes_the_job(self):
        first, second = self.order(self.a, MON, time(10), time(11)), self.order(self.a, TUE, time(10), time(11))
        self.only_ivan()
        run = self.make_plan()
        self.patch_sheets(final={second.pk: SheetResult(ERROR, 'ошибка записи в таблицу: сбой')})
        result = apply_plan(run, self.user)
        self.assertEqual((result.ok, result.stage), (False, 'partial'))
        run.refresh_from_db()
        self.assertEqual(run.status, 'partial')
        self.assertTrue(run.editable)
        a1, a2 = self.assignment(run, first), self.assignment(run, second)
        self.assertEqual((a1.sheet_status, a1.schedule_status), ('written', 'created'))
        self.assertEqual((a2.sheet_status, a2.schedule_status), ('error', ''))
        self.assertEqual(list(Schedule.objects.values_list('date', flat=True)), [MON])   # во вторник в графике ничего нет
        second.refresh_from_db()
        self.assertEqual(second.status, 'open')

        mock.patch.stopall()                                   # повтор: теперь таблица отвечает успехом
        calls = self.patch_sheets()
        result = apply_plan(run, self.user)
        self.assertTrue(result.ok, result.message)
        self.assertEqual({o for c in calls for o in c[1]}, {second.pk})          # первый заказ повторно не пишется
        run.refresh_from_db()
        self.assertEqual((run.status, len(run.apply_log)), ('applied', 2))
        self.assertEqual(Schedule.objects.count(), 2)

    def test_unexpected_failure_leaves_a_retryable_state(self):
        self.patch_sheets(write_error=RuntimeError('boom'))
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        result = apply_plan(run, self.user)
        self.assertEqual((result.ok, result.stage), (False, 'partial'))
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')                  # ничего не записано - можно применять заново
        self.assertEqual(Schedule.objects.count(), 0)
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply', status='Системная ошибка').exists())

    def test_applied_run_cannot_be_applied_again(self):
        calls = self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.assertTrue(apply_plan(run, self.user).ok)
        n = len(calls)
        again = apply_plan(run, self.user)
        self.assertEqual((again.ok, again.stage), (False, 'locked'))
        self.assertEqual(len(calls), n)
        self.assertEqual(Schedule.objects.count(), 1)

    def test_run_that_is_being_applied_is_locked(self):
        calls = self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        PlanRun.objects.filter(pk=run.pk).update(status='applying')
        run.refresh_from_db()
        self.assertEqual(apply_plan(run, self.user).stage, 'locked')
        self.assertEqual(calls, [])

    def test_order_split_between_photographers_is_written_as_a_list_and_stays_busy_for_later_plans(self):
        calls = self.patch_sheets()
        o = self.order(self.a, MON, time(10), time(15), slots=[['10:00', '11:00'], ['14:00', '15:00']])
        self.mark(self.s1, MON, 'Работает', 'до 12:00'), self.mark(self.s2, MON, 'Работает', 'с 13:00')
        run = self.make_plan()
        self.assertTrue(apply_plan(run, self.user).ok)
        self.assertEqual(calls[1][2][o.pk], f'{self.s1} + {self.s2}')              # так двух фотографов пишут в таблице
        o.refresh_from_db()
        self.assertEqual((o.status, o.photographer, o.photographer_raw), ('assigned', None, f'{self.s1} + {self.s2}'))
        self.assertEqual(set(o.photographers.all()), {self.s1, self.s2})
        fixed, unknown = fixed_parts(MON, MON, [self.s1.pk, self.s2.pk])
        self.assertEqual(sorted((sid, p.part_no) for sid, p in fixed), [(self.s1.pk, 1), (self.s2.pk, 2)])
        self.assertEqual(unknown, 0)


class RollbackTests(ApplyBase):
    def applied(self, **patch):
        """Применённый расчёт на двух заказах: в центре с фототочкой (10-11) и без неё (13-14); все - Иванову"""
        calls = self.patch_sheets(**patch)
        with_store = self.order(self.a, MON, time(10), time(11))
        without_store = self.order(self.b, MON, time(13), time(14))
        self.only_ivan()
        run = self.make_plan()
        self.assertTrue(apply_plan(run, self.user).ok)
        return run, with_store, without_store, calls

    def test_full_rollback_returns_the_draft_and_cleans_everything(self):
        run, with_store, without_store, _ = self.applied()
        self.assertTrue(run.rollbackable)
        result = rollback_plan(run, self.user)
        self.assertTrue(result.ok, result.message)
        self.assertIn('Откат выполнен', result.message)
        self.assertEqual((result.counts['cells'], result.counts['shifts']), (2, 1))

        # таблицы: откат просит вернуть именно то, что было до записи
        write, order_ids, state = self.revert_calls[0]
        self.assertTrue(write)
        self.assertEqual(state[with_store.pk], (str(self.s1), '', str(self.s1)))
        # график и заказы
        self.assertEqual(Schedule.objects.count(), 0)
        for order in (with_store, without_store):
            order.refresh_from_db()
            self.assertEqual((order.status, order.photographer, order.photographer_raw), ('open', None, ''))
        run.refresh_from_db()
        self.assertEqual((run.status, run.applied_at, run.applied_by), ('draft', None, None))
        self.assertTrue(run.editable)
        self.assertFalse(run.rollbackable)
        for a in run.assignments.all():
            self.assertEqual((a.sheet_status, a.schedule_status, a.schedule, a.sheet_before, a.sheet_after), ('', '', None, '', ''))
        self.assertEqual([e['action'] for e in run.apply_log], ['apply', 'rollback'])
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply', event_message__contains='откачено').exists())

    def test_the_draft_can_be_applied_again_after_a_rollback(self):
        run, with_store, _, calls = self.applied()
        self.assertTrue(rollback_plan(run, self.user).ok)
        again = apply_plan(run, self.user)
        self.assertTrue(again.ok, again.message)
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')
        self.assertEqual(Schedule.objects.count(), 1)
        self.assertEqual([e['action'] for e in run.apply_log], ['apply', 'rollback', 'apply'])

    def test_rollback_is_not_available_for_draft_or_twice(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.assertEqual(rollback_plan(run, self.user).stage, 'locked')           # ещё не применён
        self.assertTrue(apply_plan(run, self.user).ok)
        self.assertTrue(rollback_plan(run, self.user).ok)
        self.assertEqual(rollback_plan(run, self.user).stage, 'locked')           # уже откачен
        PlanRun.objects.filter(pk=run.pk).update(status='rolling_back')
        run.refresh_from_db()
        self.assertEqual(rollback_plan(run, self.user).stage, 'locked')

    def test_a_cell_changed_after_the_write_is_kept_with_its_shift_and_the_rest_is_reverted(self):
        run, with_store, without_store, _ = self.applied()
        mock.patch.stopall()                                                                   # откат: одна ячейка не откатывается
        self.patch_sheets(revert_results={with_store.pk: SheetResult(CONFLICT, 'в ячейке сейчас «Иван и Даша»: её изменили после записи')})
        result = rollback_plan(run, self.user)
        self.assertEqual((result.ok, result.stage), (False, 'rollback_partial'))
        self.assertIn('Иван и Даша', result.errors[0])
        run.refresh_from_db()
        self.assertEqual(run.status, 'partial')
        kept = self.assignment(run, with_store)
        self.assertEqual((kept.sheet_status, kept.schedule_status), ('written', 'created'))   # остаётся как есть
        self.assertIn('откат:', kept.sheet_detail)
        self.assertEqual(Schedule.objects.count(), 1)                                          # смена остаётся: заказ в таблице есть
        with_store.refresh_from_db(), without_store.refresh_from_db()
        self.assertEqual(with_store.status, 'assigned')
        self.assertEqual(without_store.status, 'open')                                         # второй заказ откачен
        self.assertEqual(self.assignment(run, without_store).sheet_status, '')

        mock.patch.stopall()                                                                   # конфликт устранили - повтор доводит дело
        self.patch_sheets()
        retry = rollback_plan(run, self.user)
        self.assertTrue(retry.ok, retry.message)
        self.assertEqual({o for c in self.revert_calls for o in c[1]}, {with_store.pk})        # откатывается только оставшееся
        run.refresh_from_db()
        self.assertEqual((run.status, Schedule.objects.count()), ('draft', 0))

    def test_a_name_that_was_already_in_the_table_is_left_there(self):
        run, with_store, _, _ = self.applied(final={})
        # имя уже стояло в таблице до применения: статус already, откат ячейки не нужен
        Assignment.objects.filter(order=with_store).update(sheet_status='already', sheet_before='', sheet_after='')
        self.assertTrue(rollback_plan(run, self.user).ok)
        self.assertNotIn(with_store.pk, [o for c in self.revert_calls for o in c[1]])
        with_store.refresh_from_db()
        self.assertEqual(with_store.status, 'assigned')                  # в таблице имя осталось - заказ не свободен
        self.assertEqual(Schedule.objects.count(), 0)                    # а график, созданный применением, убран

    def test_row_missing_from_the_table_is_reverted_with_a_note(self):
        run, with_store, without_store, _ = self.applied()
        mock.patch.stopall()
        self.patch_sheets(revert_results={without_store.pk: SheetResult(NOT_FOUND, 'строка заказа не найдена в таблице')})
        result = rollback_plan(run, self.user)
        self.assertTrue(result.ok, result.message)
        self.assertTrue(any('строка заказа не найдена' in n for n in result.notes))

    def test_shift_with_sales_or_salary_is_not_deleted(self):
        for kind in ('sales', 'salary'):
            with self.subTest(kind):
                Schedule.objects.all().delete(), Assignment.objects.all().delete(), PlanRun.objects.all().delete(), PhotoOrder.objects.all().delete()
                run, with_store, _, _ = self.applied()
                if kind == 'sales':
                    Sales.objects.create(store=self.store, date=MON, staff=self.s1, photographer=self.s1, photo_count=1, sum=100,
                                         cl_email='a@b.c', cl_phone='79991112233')
                else:
                    Salary.objects.create(store=self.store, staff=self.s1, date=MON, salary_sum=100)
                result = rollback_plan(run, self.user)
                self.assertTrue(result.ok, result.message)                                      # заказ откатан
                self.assertEqual(Schedule.objects.count(), 1)                                    # смена осталась
                self.assertTrue(any('оставлена' in n for n in result.notes), result.notes)
                self.assertEqual(result.counts['shifts'], 0)
                with_store.refresh_from_db()
                self.assertEqual(with_store.status, 'open')
                Sales.objects.all().delete(), Salary.objects.all().delete()

    def test_shift_edited_by_hand_or_used_by_another_run_is_not_deleted(self):
        run, with_store, _, _ = self.applied()
        Schedule.objects.update(position='Фотограф')
        self.assertTrue(any('роль в смене изменена' in n for n in rollback_plan(run, self.user).notes))
        self.assertEqual(Schedule.objects.count(), 1)

        Schedule.objects.all().delete(), Assignment.objects.all().delete(), PlanRun.objects.all().delete(), PhotoOrder.objects.all().delete()
        run, with_store, _, _ = self.applied()
        Schedule.objects.update(work_time='09:00')
        self.assertTrue(any('время работы изменено' in n for n in rollback_plan(run, self.user).notes))

        Schedule.objects.all().delete(), Assignment.objects.all().delete(), PlanRun.objects.all().delete(), PhotoOrder.objects.all().delete()
        run, with_store, _, _ = self.applied()
        other = PlanRun.objects.create(date_from=MON, date_to=MON, status='applied')
        Assignment.objects.create(plan=other, order=with_store, part_no=1, date=MON, start_min=600, end_min=660, staff=self.s1,
                                  schedule=Schedule.objects.get(), schedule_status='exists', sheet_status='already')
        self.assertTrue(any('используется другим расчётом' in n for n in rollback_plan(run, self.user).notes))
        self.assertEqual(Schedule.objects.count(), 1)

    def test_google_unreachable_blocks_the_rollback_without_changes(self):
        run, with_store, _, _ = self.applied()
        mock.patch.stopall()
        self.patch_sheets(revert_error=SheetError('Не настроен доступ к Google'))
        result = rollback_plan(run, self.user)
        self.assertEqual((result.ok, result.stage), (False, 'sheets_access'))
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')
        self.assertEqual(Schedule.objects.count(), 1)
        self.assertEqual(self.assignment(run, with_store).sheet_status, 'written')

    def test_unexpected_failure_restores_the_status_and_can_be_retried(self):
        run, _, _, _ = self.applied()
        mock.patch.stopall()
        self.patch_sheets(revert_error=RuntimeError('boom'))
        result = rollback_plan(run, self.user)
        self.assertFalse(result.ok)
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply', status='Системная ошибка').exists())
        mock.patch.stopall()
        self.patch_sheets()
        self.assertTrue(rollback_plan(run, self.user).ok)


class RetoucherApplyTests(ApplyBase):
    def two_orders(self):
        ll = self.order(self.a, MON, time(10), time(11))                    # Laserland: столбца «Ретушер» нет
        jj = self.order(self.b, MON, time(13), time(14), brand='JJ')        # Joki Joya
        self.only_ivan()
        return ll, jj

    def test_retoucher_is_requested_only_for_jj_and_only_for_photographers_who_retouch_themselves(self):
        self.patch_sheets()
        ll, jj = self.two_orders()
        self.assertTrue(apply_plan(self.make_plan(), self.user).ok)
        self.assertEqual(self.retoucher_values, {ll.pk: '', jj.pk: str(self.s1)})

    def test_written_retoucher_is_stored_on_the_order_and_reported(self):
        self.patch_sheets()
        ll, jj = self.two_orders()
        run = self.make_plan()
        result = apply_plan(run, self.user)
        self.assertIn('в «Ретушер» вписан сам фотограф: 1', result.message)
        jj.refresh_from_db(), ll.refresh_from_db()
        self.assertEqual((jj.retoucher, jj.retoucher_raw), (self.s1, str(self.s1)))
        self.assertEqual((ll.retoucher, ll.retoucher_raw), (None, ''))
        a = self.assignment(run, jj)
        self.assertEqual((a.ret_status, a.ret_after, a.ret_status_display), ('written', str(self.s1), 'ретушёр: вписан сам фотограф'))
        self.assertEqual(self.assignment(run, ll).ret_status, '')
        run.refresh_from_db()
        self.assertEqual(run.apply_log[0]['retoucher'], 1)

    def test_photographer_who_does_not_retouch_gets_a_note_and_no_retoucher(self):
        self.patch_sheets()
        ll, jj = self.two_orders()
        Staff.objects.filter(pk=self.s1.pk).update(retouches_own=False)
        run = self.make_plan()
        result = apply_plan(run, self.user)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.retoucher_values[jj.pk], '')
        self.assertTrue(any('сам не обрабатывает фото' in n for n in result.notes), result.notes)
        self.assertEqual(self.assignment(run, jj).ret_status, 'not_own')
        jj.refresh_from_db()
        self.assertIsNone(jj.retoucher)

    def test_existing_retoucher_is_kept_and_reported(self):
        ll, jj = self.two_orders()
        self.patch_sheets(final={jj.pk: SheetResult(WRITTEN, before='', after=str(self.s1), ret_status=RET_OTHER,
                                                    ret_detail='в «Ретушер» уже указано: «Даша»')})
        run = self.make_plan()
        result = apply_plan(run, self.user)
        self.assertTrue(result.ok, result.message)
        self.assertTrue(any('уже указано: «Даша»' in n for n in result.notes), result.notes)
        jj.refresh_from_db()
        self.assertEqual((jj.status, jj.retoucher, jj.retoucher_raw), ('assigned', None, ''))
        self.assertEqual(self.assignment(run, jj).ret_status, 'other')
        self.assertNotIn('в «Ретушер» вписан', result.message)

    def test_check_mentions_what_will_not_be_written_to_the_retoucher_column(self):
        ll, jj = self.two_orders()
        Staff.objects.filter(pk=self.s1.pk).update(retouches_own=False)
        self.patch_sheets()
        result = apply_plan(self.make_plan(), self.user, only_check=True)
        self.assertTrue(result.ok)
        self.assertTrue(any('ретушёр не будет указан' in n for n in result.notes), result.notes)

    def test_rollback_returns_the_retoucher_cell_and_the_order_field(self):
        ll, jj = self.two_orders()
        self.patch_sheets()
        run = self.make_plan()
        self.assertTrue(apply_plan(run, self.user).ok)
        result = rollback_plan(run, self.user)
        self.assertTrue(result.ok, result.message)
        self.assertIn('в том числе из «Ретушер»: 1', result.message)
        write, order_ids, state = next(c for c in self.revert_calls if jj.pk in c[1])
        self.assertEqual(state[jj.pk][1:], ('', str(self.s1)))
        jj.refresh_from_db()
        self.assertEqual((jj.status, jj.retoucher, jj.retoucher_raw), ('open', None, ''))
        a = self.assignment(run, jj)
        self.assertEqual((a.ret_status, a.ret_before, a.ret_after), ('', '', ''))

    def test_retoucher_replaced_after_the_apply_is_kept_on_rollback(self):
        ll, jj = self.two_orders()
        self.patch_sheets()
        run = self.make_plan()
        self.assertTrue(apply_plan(run, self.user).ok)
        mock.patch.stopall()
        self.patch_sheets(revert_results={jj.pk: SheetResult(REVERTED, ret_status=CONFLICT, ret_detail='«Ретушер» изменили после записи')})
        result = rollback_plan(run, self.user)
        self.assertTrue(result.ok, result.message)                       # заказ откатан, ретушёр - замечание
        self.assertTrue(any('«Ретушер» изменили после записи' in n for n in result.notes), result.notes)
        jj.refresh_from_db()
        self.assertEqual((jj.status, jj.retoucher_raw), ('open', str(self.s1)))   # поле ретушёра у заказа не трогаем


class ApplyViewTests(ApplyBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def messages(self, resp):
        return [str(m) for m in resp.context['messages']]

    def action(self, run, action, **fields):
        return self.client.post(reverse('schauto:plan_action', args=[run.pk]), {'action': action, **fields}, follow=True)

    def test_draft_page_has_selectors_buttons_and_problem_rows(self):
        o = self.order(self.a, MON, time(10), time(11))
        self.mark(self.s1, MON, 'Отпуск'), self.mark(self.s2, MON, 'Отгул')
        run = self.make_plan()
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertContains(page, f'name="staff_{self.assignment(run, o).pk}"')
        self.assertContains(page, 'Применить распределение')
        self.assertContains(page, 'Сохранить изменения')
        self.assertContains(page, 'не назначен фотограф')
        self.assertContains(page, 'Блокирующих проблем: 1')

    def test_page_offers_to_confirm_a_tight_gap_and_remembers_the_confirmation(self):
        run, a1, a2 = self.tight_pair()
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        sig = next(iter(validate_plan(run).unconfirmed))
        self.assertContains(page, 'Ждут вашего решения: 1')
        self.assertContains(page, 'Успеет, подтверждаю')
        self.assertContains(page, f'name="confirm" value="{sig}"', count=2)         # одна проблема - галочка в обеих строках
        self.assertContains(page, 'не хватает 30 мин')
        self.assertContains(page, 'name="upto"')
        self.assertContains(page, 'table-warning')
        self.assertNotContains(page, 'Блокирующих проблем')
        resp = self.action(run, 'save', shown=[sig, sig], confirm=[sig])
        self.assertIn('Подтверждено вручную проблем: 1', self.messages(resp))
        self.assertContains(resp, 'Проверка по текущим данным: проблем не найдено (кроме подтверждённых вами вручную: 1)')
        self.assertContains(resp, 'Подтверждено вручную</label>')
        self.assertNotContains(resp, 'table-warning')

    def test_unticking_in_the_form_takes_the_confirmation_back(self):
        run, a1, a2 = self.tight_pair()
        sig = next(iter(validate_plan(run).unconfirmed))
        self.action(run, 'save', shown=[sig], confirm=[sig])
        run.refresh_from_db()
        self.assertTrue(validate_plan(run).ok)
        resp = self.action(run, 'save', shown=[sig])                                  # галочку сняли
        self.assertIn('Снято подтверждений: 1', self.messages(resp))
        run.refresh_from_db()
        self.assertFalse(validate_plan(run).ok)

    def test_apply_with_a_ticked_problem_in_one_click(self):
        self.patch_sheets()
        run, a1, a2 = self.tight_pair()
        sig = next(iter(validate_plan(run).unconfirmed))
        refused = self.action(run, 'apply')
        self.assertTrue(any('ждут вашего подтверждения 1' in m for m in self.messages(refused)))
        applied = self.action(run, 'apply', shown=[sig], confirm=[sig])
        self.assertTrue(any('применено с подтверждёнными вручную проблемами: 1' in m for m in self.messages(applied)), self.messages(applied))
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')
        self.assertContains(applied, 'Применено с подтверждёнными вручную проблемами (1)')    # в истории применений
        self.assertContains(applied, 'подтвердил boss')

    def test_confirm_everything_up_to_n_minutes_from_the_panel(self):
        run, a1, a2 = self.tight_pair_with_tuesday()
        resp = self.action(run, 'confirm_upto', upto='20')
        self.assertIn('Подтверждено вручную проблем: 1', self.messages(resp))
        self.assertContains(resp, 'Ждут вашего решения: 1')                              # осталась пара с нехваткой 30
        none = self.action(run, 'confirm_upto', upto='20')
        self.assertTrue(any('Нет неподтверждённых проблем, где не хватает не больше 20 мин' in m for m in self.messages(none)))
        bad = self.action(run, 'confirm_upto', upto='много')
        self.assertTrue(any('Укажите число минут' in m for m in self.messages(bad)))
        run.refresh_from_db()
        self.assertEqual(len(validate_plan(run).confirmed), 1)

    def test_confirming_together_with_a_change_of_photographer_uses_the_new_situation(self):
        run, a1, a2 = self.tight_pair()
        other = self.s2 if a1.staff == self.s1 else self.s1
        sig = next(iter(validate_plan(run).unconfirmed))
        resp = self.action(run, 'save', **{f'staff_{a2.pk}': other.pk, 'shown': [sig], 'confirm': [sig]})
        self.assertIn('Изменено исполнителей: 1', self.messages(resp))
        self.assertNotIn('Подтверждено вручную проблем: 1', self.messages(resp))        # проблемы уже нет - нечего подтверждать
        run.refresh_from_db()
        self.assertEqual(run.confirmed, {})
        self.assertTrue(validate_plan(run).ok)

    def test_viewer_sees_the_problem_but_has_no_way_to_confirm_it(self):
        run, a1, a2 = self.tight_pair()
        user, _ = User.objects.get_or_create(username='viewer3')
        user.user_permissions.set(Permission.objects.filter(content_type__app_label='schauto', codename='view_planrun'))
        self.client.force_login(user)
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertContains(page, 'Ждут вашего решения: 1')
        self.assertNotContains(page, 'name="confirm"')
        self.assertNotContains(page, 'name="upto"')
        sig = next(iter(validate_plan(run).unconfirmed))
        self.assertEqual(self.client.post(reverse('schauto:plan_action', args=[run.pk]),
                                          {'action': 'save', 'shown': [sig], 'confirm': [sig]}).status_code, 403)
        run.refresh_from_db()
        self.assertEqual(run.confirmed, {})

    def test_save_changes_the_photographer(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        other = self.s2 if a.staff == self.s1 else self.s1
        resp = self.action(run, 'save', **{f'staff_{a.pk}': other.pk})
        self.assertEqual(resp.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.staff, other)
        self.assertIn('Изменено исполнителей: 1', self.messages(resp))
        self.assertContains(resp, 'изменено вручную')

    def test_check_and_apply_report_through_notifications(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        checked = self.action(run, 'check')
        self.assertTrue(any('Все проверки успешны: можно применять' in m for m in self.messages(checked)))
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')
        applied = self.action(run, 'apply')
        self.assertTrue(any('Все проверки успешны, фотографы проставлены в график работы и в Google-таблицы' in m
                            for m in self.messages(applied)), self.messages(applied))
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')
        self.assertEqual(Schedule.objects.count(), 1)

    def test_apply_saves_pending_selection_first(self):
        self.patch_sheets()
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        a = self.assignment(run, o)
        other = self.s2 if a.staff == self.s1 else self.s1
        self.action(run, 'apply', **{f'staff_{a.pk}': other.pk})
        a.refresh_from_db()
        self.assertEqual((a.staff, a.sheet_status), (other, 'written'))

    def test_failed_check_is_reported_and_nothing_is_written(self):
        calls = self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        self.mark(self.s1, MON, 'Отпуск'), self.mark(self.s2, MON, 'Отгул')
        run = self.make_plan()
        resp = self.action(run, 'apply')
        self.assertTrue(any('Проверка не пройдена' in m for m in self.messages(resp)))
        self.assertEqual(calls, [])
        self.assertEqual(Schedule.objects.count(), 0)

    def test_table_problem_is_shown_per_order(self):
        o = self.order(self.a, MON, time(10), time(11))
        self.patch_sheets(preflight={o.pk: SheetResult(CONFLICT, 'в таблице уже указан исполнитель: «Даша»')})
        resp = self.action(self.make_plan(), 'apply')
        text = ' '.join(self.messages(resp))
        self.assertIn('Запись в таблицу невозможна', text)
        self.assertIn('Google-таблица: в таблице уже указан исполнитель', text)

    def test_applied_page_is_read_only_and_shows_statuses(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.action(run, 'apply')
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertNotContains(page, 'name="staff_')
        self.assertNotContains(page, 'value="apply"')
        self.assertContains(page, 'вписан в таблицу')
        self.assertContains(page, 'запись в график создана')
        self.assertContains(page, 'История применения')
        again = self.action(run, 'apply')
        self.assertTrue(any('уже применён' in m for m in self.messages(again)))

    def test_actions_need_the_planning_permission(self):
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        user, _ = User.objects.get_or_create(username='viewer')
        user.user_permissions.set(Permission.objects.filter(content_type__app_label='schauto', codename='view_planrun'))
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse('schauto:plan_action', args=[run.pk]), {'action': 'apply'}).status_code, 403)
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="staff_')           # просмотр без права не даёт править
        self.assertNotContains(page, 'value="apply"')

    def test_rollback_button_and_action(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.assertNotContains(self.client.get(reverse('schauto:plan_detail', args=[run.pk])), 'Откатить применение')   # черновик
        self.action(run, 'apply')
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertContains(page, 'Откатить применение')
        resp = self.action(run, 'rollback')
        self.assertTrue(any('Откат выполнен' in m for m in self.messages(resp)), self.messages(resp))
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')
        self.assertEqual(Schedule.objects.count(), 0)
        self.assertNotContains(resp, 'Откатить применение')              # откатывать больше нечего
        self.assertContains(resp, 'name="staff_')                        # снова можно править
        self.assertContains(resp, '<b>откат</b>')                        # в истории применений

    def test_partial_rollback_is_reported_per_problem(self):
        o = self.order(self.a, MON, time(10), time(11))
        self.patch_sheets(revert_results={o.pk: SheetResult(CONFLICT, 'в ячейке сейчас «Другое»: её изменили после записи')})
        run = self.make_plan()
        self.action(run, 'apply')
        resp = self.action(run, 'rollback')
        text = ' '.join(self.messages(resp))
        self.assertIn('Откат выполнен частично', text)
        self.assertIn('в ячейке сейчас «Другое»', text)
        run.refresh_from_db()
        self.assertEqual(run.status, 'partial')

    def test_rollback_needs_the_planning_permission(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.action(run, 'apply')
        user, _ = User.objects.get_or_create(username='viewer2')
        user.user_permissions.set(Permission.objects.filter(content_type__app_label='schauto', codename='view_planrun'))
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse('schauto:plan_action', args=[run.pk]), {'action': 'rollback'}).status_code, 403)
        self.assertNotContains(self.client.get(reverse('schauto:plan_detail', args=[run.pk])), 'Откатить применение')
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')

    def test_rollback_error_does_not_become_a_500(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.action(run, 'apply')
        with mock.patch('schauto.views.rollback_plan', side_effect=RuntimeError('сбой')):
            resp = self.action(run, 'rollback')
        self.assertTrue(any('Откат не выполнен' in m for m in self.messages(resp)))
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Rollback', status='Системная ошибка').exists())

    def test_unexpected_error_does_not_become_a_500(self):
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        with mock.patch('schauto.views.apply_plan', side_effect=RuntimeError('сбой')):
            resp = self.action(run, 'apply')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Операция не выполнена' in m for m in self.messages(resp)))
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Apply', status='Системная ошибка').exists())


class DeleteDraftTests(ApplyBase):
    def test_draft_is_deleted_with_its_assignments_and_nothing_else_is_touched(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        other = self.make_plan()                                       # второй расчёт остаётся
        assignments = run.assignments.count()
        self.assertGreater(assignments, 0)
        orders, staff, schedule = PhotoOrder.objects.count(), Staff.objects.count(), Schedule.objects.count()
        text = delete_plan(run, self.user)
        self.assertIn(f'удалено вместе с назначениями ({assignments})', text)
        self.assertFalse(PlanRun.objects.filter(pk=run.pk).exists())
        self.assertFalse(Assignment.objects.filter(plan_id=run.pk).exists())
        self.assertTrue(PlanRun.objects.filter(pk=other.pk).exists())
        self.assertTrue(Assignment.objects.filter(plan=other).exists())
        self.assertEqual((PhotoOrder.objects.count(), Staff.objects.count(), Schedule.objects.count()), (orders, staff, schedule))
        o.refresh_from_db()
        self.assertEqual(o.status, PhotoOrder.STATUS_OPEN)
        event = ImplEvents.objects.get(event_type='Schauto_Plan_Delete')
        self.assertEqual((event.status, event.solved), ('Успешно', 'Да'))
        self.assertIn(f'№{run.pk}', event.event_message)
        self.assertTrue(ImplEvents.objects.filter(event_type='Delete_rec_from_planrun').exists())     # общий журнал удалений проекта

    def test_applied_and_partial_runs_cannot_be_deleted(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.assertTrue(run.deletable)
        apply_plan(run, self.user)
        run.refresh_from_db()
        self.assertEqual((run.status, run.deletable), ('applied', False))
        with self.assertRaisesMessage(PlanNotDeletable, 'сначала нажмите «Откатить применение»'):
            delete_plan(run, self.user)
        PlanRun.objects.filter(pk=run.pk).update(status='partial')
        run.refresh_from_db()
        with self.assertRaises(PlanNotDeletable):
            delete_plan(run, self.user)
        self.assertTrue(PlanRun.objects.filter(pk=run.pk).exists())
        self.assertTrue(run.assignments.exists())

    def test_runs_being_applied_or_rolled_back_cannot_be_deleted(self):
        self.order(self.a, MON, time(10), time(11))
        for status in ('applying', 'rolling_back'):
            run = self.make_plan()
            PlanRun.objects.filter(pk=run.pk).update(status=status)
            run.refresh_from_db()
            with self.assertRaisesMessage(PlanNotDeletable, 'применяется или откатывается'):
                delete_plan(run, self.user)
            self.assertTrue(PlanRun.objects.filter(pk=run.pk).exists())

    def test_a_rolled_back_run_is_a_draft_again_and_can_be_deleted(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        apply_plan(run, self.user)
        self.assertTrue(rollback_plan(run, self.user).ok)
        run.refresh_from_db()
        self.assertEqual((run.status, run.deletable), ('draft', True))
        delete_plan(run, self.user)
        self.assertFalse(PlanRun.objects.filter(pk=run.pk).exists())

    def test_a_draft_with_something_already_written_is_protected(self):
        o = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        Assignment.objects.filter(plan=run, order=o).update(sheet_status='written')
        self.assertFalse(PlanRun.objects.get(pk=run.pk).deletable)
        with self.assertRaises(PlanNotDeletable):
            delete_plan(run, self.user)


class DeleteDraftViewTests(ApplyBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def messages(self, resp):
        return [str(m) for m in resp.context['messages']]

    def post(self, run, action='delete'):
        return self.client.post(reverse('schauto:plan_action', args=[run.pk]), {'action': action}, follow=True)

    def test_draft_page_has_the_delete_button_on_the_right_and_no_rollback(self):
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertContains(page, 'Удалить распределение')
        self.assertContains(page, 'value="delete"')
        self.assertNotContains(page, 'Откатить применение')

    def test_delete_removes_the_draft_and_returns_to_the_list(self):
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        resp = self.post(run)
        self.assertEqual(resp.redirect_chain[-1][0], reverse('schauto:plan'))
        self.assertTrue(any('удалено вместе с назначениями' in m for m in self.messages(resp)), self.messages(resp))
        self.assertFalse(PlanRun.objects.filter(pk=run.pk).exists())
        self.assertEqual(self.client.get(reverse('schauto:plan_detail', args=[run.pk])).status_code, 404)

    def test_applied_run_has_no_delete_button_and_the_post_is_refused(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.post(run, 'apply')
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertNotContains(page, 'Удалить распределение')
        self.assertContains(page, 'Откатить применение')
        resp = self.post(run)
        self.assertTrue(any('сначала нажмите «Откатить применение»' in m for m in self.messages(resp)), self.messages(resp))
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')
        self.assertTrue(run.assignments.exists())

    def test_after_the_rollback_the_run_can_be_deleted_from_its_page(self):
        self.patch_sheets()
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.post(run, 'apply')
        self.post(run, 'rollback')
        self.assertContains(self.client.get(reverse('schauto:plan_detail', args=[run.pk])), 'Удалить распределение')
        self.post(run)
        self.assertFalse(PlanRun.objects.filter(pk=run.pk).exists())

    def test_viewer_neither_sees_the_button_nor_can_delete(self):
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        user, _ = User.objects.get_or_create(username='viewer4')
        user.user_permissions.set(Permission.objects.filter(content_type__app_label='schauto', codename='view_planrun'))
        self.client.force_login(user)
        self.assertNotContains(self.client.get(reverse('schauto:plan_detail', args=[run.pk])), 'Удалить распределение')
        self.assertEqual(self.client.post(reverse('schauto:plan_action', args=[run.pk]), {'action': 'delete'}).status_code, 403)
        self.assertTrue(PlanRun.objects.filter(pk=run.pk).exists())

    def test_unexpected_error_does_not_become_a_500_and_keeps_the_draft(self):
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        with mock.patch('schauto.views.delete_plan', side_effect=RuntimeError('сбой')):
            resp = self.post(run)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Удаление не выполнено' in m for m in self.messages(resp)))
        self.assertTrue(PlanRun.objects.filter(pk=run.pk).exists())
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan_Delete', status='Системная ошибка').exists())

    def test_deleting_one_run_leaves_the_other_runs_confirmations_alone(self):
        first = self.tight_pair()[0]
        second = self.make_plan()
        PlanRun.objects.filter(pk=second.pk).update(confirmed={'x': {'text': 't', 'by': 'b', 'at': 'a'}})
        self.post(first)
        second.refresh_from_db()
        self.assertEqual(second.confirmed, {'x': {'text': 't', 'by': 'b', 'at': 'a'}})


@override_settings(SCHAUTO_SHEET_IDS=SHEETS)
class EndToEndTests(TestCase):
    """Настоящие импортёр, расчёт, проверка и запись: только Google подменён таблицей в памяти"""

    def setUp(self):
        self.day = date(2026, 10, 22)
        self.store = Store.objects.create(name='Гагаринский LL', short_name='LLGgr', store_status='Действующая')
        self.ggr = Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ', store=self.store)
        self.rio = Venue.objects.create(name='Рио JJ', brand='JJ', sheet_tab_name='РИО JJ')
        Route.objects.create(from_venue=self.ggr, to_venue=self.rio, duration_min=20)
        Route.objects.create(from_venue=self.rio, to_venue=self.ggr, duration_min=20)
        self.ivan = Staff.objects.create(f_name='Петров', name='Иван', date_empl='2026-01-01', staff_type='Выездной',
                                         skill_score=8, max_orders_per_day=4)
        self.maria = Staff.objects.create(f_name='Сидорова', name='Мария', date_empl='2026-01-01', staff_type='Выездной',
                                          skill_score=9, max_orders_per_day=4)
        WorkVacSchedule.objects.create(staff=self.ivan, date=self.day, staff_wrk_status='Работает')
        WorkVacSchedule.objects.create(staff=self.maria, date=self.day, staff_wrk_status='Отпуск')
        self.user = User.objects.create(username='boss', is_staff=True, is_superuser=True)

        self.ll, self.jj = FakeWorksheet(LL_ROWS, 'ГАГАРИНСКИЙ'), FakeWorksheet(JJ_ROWS, 'РИО JJ')
        self.client_ = FakeClient({'ll-sheet': {1: self.ll}, 'jj-sheet': {10: self.jj}})
        self.import_sheets()

    def import_sheets(self):
        fake = FakeSheets()
        fake.rows = {1: self.ll.rows, 2: [['дата', 'Время', 'адрес', 'Фотограф']], 3: [['мусор']], 10: self.jj.rows}
        run_import(today=TODAY, lister=fake.lister, fetcher=fake.fetcher)

    def test_full_cycle(self):
        run = run_plan(self.user, self.day, self.day)
        self.assertEqual((run.summary['orders'], run.summary['unassigned']), (3, 0))
        self.assertEqual({a.staff for a in run.assignments.all()}, {self.ivan})        # Мария в отпуске

        result = apply_plan(run, self.user, client=self.client_)
        self.assertTrue(result.ok, result.message)

        # таблицы: имя вписано, руководитель Laserland сохранён
        self.assertEqual(self.ll.rows[1][9], MANAGER + ' Иван Петров')
        self.assertEqual(self.ll.rows[2][9], 'Иван Петров')
        self.assertEqual((self.jj.rows[1][8], self.jj.rows[1][7]), ('Иван Петров', 'Иван Петров'))   # Joki Joya: и в «Ретушер»
        self.assertEqual(self.ll.rows[3][9], MANAGER + ' Даша Чужая')                   # чужой заказ не тронут
        # график: одна смена на точке Гагаринского, у Рио JJ фототочки нет
        row = Schedule.objects.get()
        self.assertEqual((row.staff, row.store, row.date, row.work_time, row.position),
                         (self.ivan, self.store, self.day, '10:00', 'Выездной фотограф'))
        run.refresh_from_db()
        self.assertEqual(run.status, 'applied')
        self.assertEqual(sorted(a.schedule_status for a in run.assignments.all()), ['created', 'created', 'no_store'])

        # новая загрузка таблиц видит назначенных и ничего не ломает: заказы уже с исполнителем
        self.import_sheets()
        orders = PhotoOrder.objects.filter(date=self.day)
        self.assertEqual({(o.status, o.photographer) for o in orders}, {('assigned', self.ivan)})
        self.assertEqual(PhotoOrder.objects.get(brand='JJ', date=self.day).retoucher, self.ivan)   # ретушёр распознан импортом
        again = run_plan(self.user, self.day, self.day)
        self.assertEqual(again.summary['orders'], 0)
        self.assertEqual(again.summary['fixed_orders'], 3)

    def test_someone_filled_the_cell_after_the_calculation(self):
        run = run_plan(self.user, self.day, self.day)
        self.ll.rows[2][9] = 'Лена Новая'                                              # руками вписали после расчёта
        result = apply_plan(run, self.user, client=self.client_)
        self.assertEqual((result.ok, result.stage), (False, 'sheets_check'))
        self.assertEqual(self.ll.updates, [])                                          # в таблицах ничего не изменено
        self.assertEqual(self.jj.updates, [])
        self.assertEqual(Schedule.objects.count(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')

    def test_google_write_failure_on_one_sheet_gives_partial_result_and_retry_completes(self):
        run = run_plan(self.user, self.day, self.day)
        self.ll.fail_on_write = True
        result = apply_plan(run, self.user, client=self.client_)
        self.assertEqual((result.ok, result.stage), (False, 'partial'))
        self.assertEqual(self.jj.rows[1][8], 'Иван Петров')                              # JJ записан
        run.refresh_from_db()
        self.assertEqual(run.status, 'partial')
        self.assertEqual(Schedule.objects.count(), 0)                                  # Laserland не вписан - и графика нет (Рио без точки)
        self.ll.fail_on_write = False
        retry = apply_plan(run, self.user, client=self.client_)
        self.assertTrue(retry.ok, retry.message)
        self.assertEqual(self.ll.rows[2][9], 'Иван Петров')
        self.assertEqual(Schedule.objects.count(), 1)
        self.assertEqual(len(self.jj.updates), 2)                                      # «Фотограф» и «Ретушер» - одно применение; повторно JJ не писался

    def test_rollback_restores_the_tables_and_the_draft_can_be_applied_again(self):
        run = run_plan(self.user, self.day, self.day)
        self.assertTrue(apply_plan(run, self.user, client=self.client_).ok)
        self.assertEqual(self.ll.rows[1][9], MANAGER + ' Иван Петров')

        result = rollback_plan(run, self.user, client=self.client_)
        self.assertTrue(result.ok, result.message)
        # ячейки в точности как до применения: руководитель Laserland на месте, остальные пусты
        self.assertEqual((self.ll.rows[1][9], self.ll.rows[2][9], self.jj.rows[1][8], self.jj.rows[1][7]), (MANAGER, '', '', ''))
        self.assertEqual(self.ll.rows[3][9], MANAGER + ' Даша Чужая')            # чужая запись не тронута
        self.assertEqual(Schedule.objects.count(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')
        self.assertEqual(PhotoOrder.objects.filter(date=self.day, status='open').count(), 3)

        self.import_sheets()                                                        # обычная загрузка видит свободные заказы
        self.assertEqual({o.status for o in PhotoOrder.objects.filter(date=self.day)}, {'open'})
        again = apply_plan(run, self.user, client=self.client_)                     # и тот же черновик применяется заново
        self.assertTrue(again.ok, again.message)
        self.assertEqual(self.ll.rows[1][9], MANAGER + ' Иван Петров')
        self.assertEqual(Schedule.objects.count(), 1)

    def test_rollback_does_not_touch_a_cell_edited_after_the_apply(self):
        run = run_plan(self.user, self.day, self.day)
        self.assertTrue(apply_plan(run, self.user, client=self.client_).ok)
        self.ll.rows[2][9] = 'Иван Петров, а ещё Маша'                             # руками дописали
        result = rollback_plan(run, self.user, client=self.client_)
        self.assertEqual((result.ok, result.stage), (False, 'rollback_partial'))
        self.assertEqual(self.ll.rows[2][9], 'Иван Петров, а ещё Маша')            # не тронута
        self.assertEqual((self.ll.rows[1][9], self.jj.rows[1][8]), (MANAGER, ''))   # остальное откачено
        run.refresh_from_db()
        self.assertEqual(run.status, 'partial')
        self.assertEqual(Schedule.objects.count(), 1)                              # смена остаётся: заказ в таблице всё ещё есть
        order = PhotoOrder.objects.get(tab_name='ГАГАРИНСКИЙ', sheet_row=3)
        self.assertEqual(order.status, 'assigned')
