from datetime import date, time

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tph_system.models import ImplEvents, Schedule, Staff, Store, WorkVacSchedule

from .models import Assignment, PhotoOrder, PlanRun, Route, Venue
from .planning import MAX_SPAN_DAYS, collect, order_parts, run_plan, week_bounds, week_load

MON, TUE = date(2026, 11, 2), date(2026, 11, 3)
WED, THU, SUN, NEXT_MON = date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 8), date(2026, 11, 9)
WEEK = MON.isocalendar()[:2]


class PlanningBase(TestCase):
    def setUp(self):
        self.a = Venue.objects.create(name='Центр А', brand='LL', difficulty=5)
        self.b = Venue.objects.create(name='Центр Б', brand='JJ', difficulty=7)
        Route.objects.create(from_venue=self.a, to_venue=self.b, description='метро', duration_min=40)
        Route.objects.create(from_venue=self.a, to_venue=self.b, description='автобус', duration_min=25)
        Route.objects.create(from_venue=self.b, to_venue=self.a, duration_min=30)
        self.s1 = self.staff('Иванов', 'Иван', skill=8, limit=3)
        self.s2 = self.staff('Петрова', 'Мария', skill=6, limit=2)
        self.user = User.objects.create(username='boss', is_staff=True, is_superuser=True)  # без пароля: хеширование замедляет тесты
        self.n = 0

    def mark(self, staff, day, status='Работает', text=None):
        WorkVacSchedule.objects.update_or_create(staff=staff, date=day, defaults={'staff_wrk_status': status, 'time_availiable': text})

    def staff(self, f_name, name, skill=7, limit=3, staff_type='Выездной'):
        return Staff.objects.create(f_name=f_name, name=name, date_empl='2026-01-01', staff_type=staff_type,
                                    skill_score=skill, max_orders_per_day=limit)

    def order(self, venue, day, start, end, status=PhotoOrder.STATUS_OPEN, slots=None, **kw):
        self.n += 1
        slots = slots or [[f'{start:%H:%M}', f'{end:%H:%M}']]
        brand = kw.pop('brand', 'LL')
        return PhotoOrder.objects.create(
            brand=brand, tab_name='Лист', sheet_row=self.n, fingerprint=f'fp{self.n}', venue=venue, date=day,
            time_start=start, time_end=end, slots=slots, status=status, last_seen_at=timezone.now(), **kw)

    def make_plan(self, date_from=MON, date_to=TUE):
        return run_plan(self.user, date_from, date_to)

    def staff_of(self, run, order):
        return {a.part_no: a.staff for a in run.assignments.filter(order=order)}


class RunPlanTests(PlanningBase):
    def test_saves_draft_with_explanations_and_touches_nothing_else(self):
        o = self.order(self.a, MON, time(10), time(11))
        schedule_before, orders_before = Schedule.objects.count(), list(PhotoOrder.objects.values_list('photographer_id', 'status'))
        run = self.make_plan()
        self.assertEqual((run.status, run.created_by, run.summary['orders'], run.summary['assigned'], run.summary['unassigned']),
                         ('draft', self.user, 1, 1, 0))
        a = run.assignments.get()
        self.assertEqual(a.order, o)
        self.assertIn(a.staff, (self.s1, self.s2))
        self.assertTrue(a.reasons and 'Навык' in a.reasons[0])
        self.assertEqual((a.start_min, a.end_min, a.time_display), (600, 660, '10:00-11:00'))
        # этап 3 ничего не пишет в график и не трогает заказы
        self.assertEqual(Schedule.objects.count(), schedule_before)
        self.assertEqual(list(PhotoOrder.objects.values_list('photographer_id', 'status')), orders_before)
        event = ImplEvents.objects.get(event_type='Schauto_Plan')
        self.assertEqual(event.status, 'Успешно')
        self.assertIn('распределено 1', event.event_message)

    def test_only_open_orders_inside_the_period_are_planned(self):
        self.order(self.a, MON, time(10), time(11))
        self.order(self.a, date(2026, 12, 1), time(10), time(11))                                     # вне периода
        self.order(self.a, MON, time(12), time(13), status=PhotoOrder.STATUS_ASSIGNED, photographer=self.s1)  # уже назначен
        self.order(self.a, MON, time(14), time(15), status=PhotoOrder.STATUS_GONE)
        run = self.make_plan()
        self.assertEqual((run.summary['orders'], run.summary['parts'], run.summary['fixed_orders']), (1, 1, 1))

    def test_manual_assignment_occupies_the_photographer(self):
        self.order(self.a, MON, time(10), time(12), status=PhotoOrder.STATUS_ASSIGNED, photographer=self.s1)
        new = self.order(self.a, MON, time(11), time(12))
        run = self.make_plan()
        self.assertEqual(self.staff_of(run, new), {1: self.s2})
        self.assertEqual([f['staff'] for f in run.fixed], [str(self.s1)])

    def test_vacation_and_sick_leave_block_but_working_status_does_not(self):
        new = self.order(self.a, MON, time(10), time(11))
        self.mark(self.s1, MON, 'Отпуск')
        self.mark(self.s2, MON, 'Работает', 'весь день')
        self.assertEqual(self.staff_of(self.make_plan(), new), {1: self.s2})
        WorkVacSchedule.objects.filter(staff=self.s2).update(staff_wrk_status='Больничный')
        run = self.make_plan()
        a = run.assignments.get()
        self.assertIsNone(a.staff)
        self.assertEqual(run.summary['unassigned'], 1)
        self.assertEqual(sorted(r.split(':')[1].strip() for r in a.rejected), ['больничный', 'отпуск'])

    def test_no_record_or_empty_status_means_free_and_only_absence_statuses_block(self):
        new = self.order(self.a, MON, time(10), time(11))
        self.mark(self.s2, MON, '')                                                 # запись есть, статус пустой
        run = self.make_plan()                                                      # у s1 записи нет вовсе
        self.assertIn(run.assignments.get().staff, (self.s1, self.s2))
        self.mark(self.s1, MON, 'Отгул')
        self.mark(self.s2, MON, 'Больничный')
        a = self.make_plan().assignments.get()
        self.assertIsNone(a.staff)
        self.assertEqual(sorted(r.split(': ')[1] for r in a.rejected), ['больничный', 'отгул'])

    def test_time_window_text_is_respected_and_garbled_text_is_reported(self):
        morning = self.order(self.a, MON, time(10), time(11))
        evening = self.order(self.a, TUE, time(18), time(19))
        self.mark(self.s1, MON, 'Работает', 'с 15:00')
        self.mark(self.s2, TUE, 'Работает', 'ПОЛ ДНЯ')
        run = self.make_plan()
        self.assertEqual(self.staff_of(run, morning), {1: self.s2})   # у s1 окно с 15:00
        self.assertEqual(self.staff_of(run, evening), {1: self.s1})   # s2 в этот день не разобрано
        self.assertTrue(any('ПОЛ ДНЯ' in w for w in run.warnings))

    def test_unparsed_text_on_a_day_without_orders_is_not_a_warning(self):
        self.order(self.a, MON, time(10), time(11))
        self.mark(self.s2, TUE, 'Работает', 'ПОЛ ДНЯ')
        self.assertFalse(any('ПОЛ ДНЯ' in w for w in self.make_plan().warnings))

    def test_staff_without_skill_or_limit_is_left_out_with_a_warning(self):
        Staff.objects.create(f_name='Сидоров', name='Олег', date_empl='2026-01-01', staff_type='Выездной')
        self.staff('Штатный', 'Сергей', staff_type='Штат')   # другой тип - не выездной
        self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.assertEqual(run.summary['staff'], 2)
        self.assertTrue(any('Олег Сидоров' in w and 'не участвует' in w for w in run.warnings))
        self.assertFalse(any('Сергей' in w for w in run.warnings))

    def test_dismissed_outbound_staff_is_not_used(self):
        Staff.objects.filter(pk=self.s1.pk).update(dism_status='Уволен')
        self.order(self.a, MON, time(10), time(11))
        self.assertEqual(self.make_plan().summary['staff'], 1)

    def test_orders_of_inactive_venues_and_needing_fix_are_reported_not_planned(self):
        Venue.objects.filter(pk=self.b.pk).update(is_active=False)
        self.order(self.b, MON, time(10), time(11))
        self.order(self.a, MON, time(12), time(13), status=PhotoOrder.STATUS_NEEDS_FIX)
        run = self.make_plan()
        self.assertEqual(run.summary['orders'], 0)
        self.assertTrue(any('не участвующих в планировании' in w for w in run.warnings))
        self.assertTrue(any('требующих ручной правки: 1' in w for w in run.warnings))

    def test_manual_assignment_with_unknown_name_is_reported(self):
        self.order(self.a, MON, time(10), time(11), status=PhotoOrder.STATUS_ASSIGNED, photographer_raw='Какая-то Даша')
        self.assertTrue(any('не сопоставленный с сотрудником' in w for w in self.make_plan().warnings))

    def test_best_variant_of_route_is_used(self):
        # А -> Б: варианты 40 и 25 мин; между заказами 45 мин: хватает только с лучшим вариантом (25 + буфер 15)
        first = self.order(self.a, MON, time(10), time(11))
        second = self.order(self.b, MON, time(11, 45), time(12, 45))
        Staff.objects.filter(pk=self.s2.pk).update(dism_status='Уволен')
        run = self.make_plan()
        self.assertEqual(run.summary['unassigned'], 0)
        self.assertEqual(self.staff_of(run, first), self.staff_of(run, second))

    def test_missing_route_is_reported_with_default_value(self):
        Route.objects.filter(from_venue=self.b).delete()
        self.order(self.b, MON, time(10), time(11))
        self.order(self.a, MON, time(12, 15), time(13, 15))   # Б -> А без маршрута: принято 90 мин, а между заказами 75
        Staff.objects.filter(pk=self.s2.pk).update(dism_status='Уволен')
        run = self.make_plan()
        self.assertEqual(run.summary['unassigned'], 1)
        self.assertTrue(any('Нет маршрута «Центр Б» -> «Центр А»' in w for w in run.warnings))

    def test_order_with_a_long_break_is_split_into_parts(self):
        o = self.order(self.a, MON, time(10), time(15), slots=[['10:00', '11:00'], ['14:00', '15:00']], extra_minutes=30)
        parts = order_parts(o)
        self.assertEqual([(p.part_no, p.parts_total, p.start, p.end, p.work_minutes) for p in parts],
                         [(1, 2, 600, 660, 60), (2, 2, 840, 930, 90)])    # продление - к концу последней части
        run = self.make_plan()
        self.assertEqual(sorted(run.assignments.values_list('part_no', flat=True)), [1, 2])

    def test_familiarity_comes_from_past_shifts_at_the_venue_store(self):
        store = Store.objects.create(name='Центр А', short_name='LLA', store_status='Действующая')
        Venue.objects.filter(pk=self.a.pk).update(store=store)
        Staff.objects.filter(pk=self.s1.pk).update(skill_score=7)
        Staff.objects.filter(pk=self.s2.pk).update(skill_score=7, max_orders_per_day=3)
        for day in (date(2026, 10, 5), date(2026, 10, 12)):
            Schedule.objects.create(staff=self.s2, store=store, date=day, position='Выездной фотограф')
        data = collect(MON, TUE)
        self.assertEqual(data.familiarity, {(self.s2.pk, self.a.pk): 2})
        new = self.order(self.a, MON, time(10), time(11))
        run = self.make_plan()
        self.assertEqual(self.staff_of(run, new), {1: self.s2})
        self.assertIn('Уже работал в этом центре: 2 зак.', run.assignments.get().reasons)

    def test_empty_period_makes_an_empty_draft(self):
        run = self.make_plan()
        self.assertEqual((run.summary['parts'], run.assignments.count()), (0, 0))


class WeekLoadTests(PlanningBase):
    """Нагрузка недели берётся из заказов в таблицах («Заказы») на остальные дни недели, а не только из периода расчёта"""

    def assigned(self, day, staff=None, status=PhotoOrder.STATUS_ASSIGNED, hour=10, **kw):
        return self.order(self.a, day, time(hour), time(hour + 1), status=status, photographer=staff, **kw)

    def test_week_bounds(self):
        self.assertEqual(week_bounds(TUE, TUE), (MON, SUN))
        self.assertEqual(week_bounds(SUN, NEXT_MON), (MON, date(2026, 11, 15)))

    def test_counts_orders_of_the_other_days_of_the_week_before_and_after_the_period(self):
        self.assigned(MON, self.s1), self.assigned(WED, self.s1), self.assigned(SUN, self.s1)     # до, после и в конце недели
        self.assigned(TUE, self.s1)                                                                # внутри периода - не считается
        self.assigned(WED, self.s2)
        self.assertEqual(week_load(TUE, TUE, [self.s1.pk, self.s2.pk]), {(self.s1.pk, WEEK): 3, (self.s2.pk, WEEK): 1})

    def test_ignores_other_weeks_other_statuses_and_other_people(self):
        self.assigned(date(2026, 11, 1), self.s1)                                                   # воскресенье предыдущей недели
        self.assigned(NEXT_MON, self.s1)                                                            # следующая неделя
        self.assigned(MON, self.s1, status=PhotoOrder.STATUS_OPEN)
        self.assigned(WED, self.s1, status=PhotoOrder.STATUS_GONE)
        self.assigned(THU, self.s1, status=PhotoOrder.STATUS_NEEDS_FIX)
        self.assigned(MON, None, photographer_raw='Какая-то Даша')
        self.assertEqual(week_load(TUE, TUE, [self.s1.pk, self.s2.pk]), {})

    def test_team_orders_count_for_every_member_once(self):
        o = self.assigned(MON, None, photographer_raw='Иван Иванов + Мария Петрова')
        o.photographers.set([self.s1, self.s2])
        self.assertEqual(week_load(TUE, TUE, [self.s1.pk, self.s2.pk]), {(self.s1.pk, WEEK): 1, (self.s2.pk, WEEK): 1})

    def test_a_period_across_two_weeks_loads_both(self):
        self.assigned(MON, self.s1), self.assigned(date(2026, 11, 10), self.s1)
        self.assertEqual(week_load(SUN, NEXT_MON, [self.s1.pk]), {(self.s1.pk, WEEK): 1, (self.s1.pk, NEXT_MON.isocalendar()[:2]): 1})

    def test_collect_passes_the_week_load_and_the_availability_of_the_whole_week(self):
        self.assigned(MON, self.s1)
        self.mark(self.s1, THU, 'Отпуск')                                                         # за пределами периода
        self.mark(self.s1, THU, 'Отпуск', 'ПОЛ ДНЯ')
        self.mark(self.s2, WED, 'Работает', 'ПОЛ ДНЯ')                                              # не разобрано, но не в периоде
        data = collect(TUE, TUE)
        self.assertEqual(data.week_load, {(self.s1.pk, WEEK): 1})
        by_id = {s.id: s for s in data.staff}
        self.assertEqual(by_id[self.s1.pk].avail(THU).blocked, 'Отпуск')                           # график за целую неделю
        self.assertEqual(data.warnings, [])                                                       # предупреждение только про дни расчёта

    def test_one_day_plan_gives_the_order_to_the_less_loaded_photographer(self):
        order = self.order(self.a, TUE, time(10), time(11))
        for day in (MON, WED, THU, date(2026, 11, 6), date(2026, 11, 7), SUN):
            self.assigned(day, self.s1, hour=9)                                                    # у сильного уже шесть заказов на неделе
        first = self.make_plan(TUE, TUE)
        self.assertEqual(first.assignments.get(order=order).staff, self.s2)
        self.assertIn('вне него уже назначено в таблицах 0', ' '.join(first.assignments.get(order=order).reasons))

    def test_without_other_orders_the_stronger_photographer_is_preferred_as_before(self):
        order = self.order(self.a, TUE, time(10), time(11))
        self.assertEqual(self.make_plan(TUE, TUE).assignments.get(order=order).staff, self.s1)

    def test_orders_in_the_plan_period_are_not_counted_twice(self):
        self.assigned(TUE, self.s1)
        data = collect(MON, WED)
        self.assertEqual(data.week_load, {})
        self.assertEqual(len(data.fixed), 1)


class PlanPagesTests(PlanningBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def user_with(self, *codenames):
        user, _ = User.objects.get_or_create(username='limited')
        user.user_permissions.set(Permission.objects.filter(content_type__app_label='schauto', codename__in=codenames))
        self.client.force_login(user)
        return user

    def post_run(self, date_from='02.11.2026', date_to='03.11.2026'):
        return self.client.post(reverse('schauto:plan'), {'date_from': date_from, 'date_to': date_to})

    def test_list_page_renders(self):
        resp = self.client.get(reverse('schauto:plan'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="plan_form"')
        self.assertContains(resp, '>Распределить</button>')       # название кнопки формы расчёта
        self.assertContains(resp, 'Расчётов ещё не было')

    def test_run_redirects_to_detail_which_shows_everything(self):
        self.order(self.a, MON, time(10), time(11))
        self.order(self.a, MON, time(10), time(11, 30))       # пересекаются: придётся разным
        self.order(self.b, MON, time(12), time(13), status=PhotoOrder.STATUS_ASSIGNED, photographer=self.s1)
        resp = self.post_run()
        run = PlanRun.objects.get()
        self.assertRedirects(resp, reverse('schauto:plan_detail', args=[run.pk]))
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Предлагаемое распределение')
        self.assertContains(page, 'Нагрузка по фотографам')
        self.assertContains(page, 'Навык')
        self.assertContains(page, 'Уже назначено вручную')
        self.assertContains(page, 'Центр А')
        # в списке расчётов ссылки стоят на первых трёх столбцах, кнопки «Открыть» нет
        listing = self.client.get(reverse('schauto:plan'))
        self.assertNotContains(listing, 'Открыть')
        self.assertEqual(listing.content.decode().count(reverse('schauto:plan_detail', args=[run.pk])), 3)

    def test_detail_filters_by_staff_and_lists_unassigned_with_reasons(self):
        self.order(self.a, MON, time(10), time(11))
        self.mark(self.s1, MON, 'Отпуск')
        self.mark(self.s2, MON, 'Больничный')
        self.post_run()
        run = PlanRun.objects.get()
        page = self.client.get(reverse('schauto:plan_detail', args=[run.pk]))
        self.assertContains(page, 'Без исполнителя: 1')
        self.assertContains(page, 'больничный')
        filtered = self.client.get(reverse('schauto:plan_detail', args=[run.pk]) + f'?staff={self.s1.pk}')
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.context['count'], 0)

    def test_invalid_period_does_not_run(self):
        self.assertContains(self.post_run('05.11.2026', '03.11.2026'), 'Дата «с» позже даты «по»')
        self.assertContains(self.post_run('01.11.2026', '31.01.2027'), f'не длиннее {MAX_SPAN_DAYS} дней')
        self.assertEqual(PlanRun.objects.count(), 0)

    def test_view_permission_is_required_and_running_needs_its_own(self):
        self.user_with('view_planrun')
        self.assertEqual(self.client.get(reverse('schauto:plan')).status_code, 200)
        self.assertEqual(self.post_run().status_code, 403)
        self.assertEqual(PlanRun.objects.count(), 0)
        self.assertNotContains(self.client.get(reverse('schauto:plan')), 'id="plan_form"')
        self.user_with('view_venue')
        self.assertEqual(self.client.get(reverse('schauto:plan')).status_code, 403)
        self.user_with('view_planrun', 'run_planning')
        self.assertEqual(self.post_run().status_code, 302)

    def test_failure_is_logged_not_shown_as_500(self):
        from unittest import mock
        with mock.patch('schauto.views.run_plan', side_effect=RuntimeError('сбой')):
            resp = self.post_run()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Расчёт не выполнен')
        self.assertTrue(ImplEvents.objects.filter(event_type='Schauto_Plan', status='Системная ошибка').exists())

    def test_index_links_to_planning(self):
        self.assertContains(self.client.get(reverse('schauto:index')), reverse('schauto:plan'))
