from datetime import date, timedelta

from django.test import SimpleTestCase

from .availability import Availability, day_availability, parse_availability
from .planner import PlanPart, Planner, PlannerConfig, PlanStaff, part_need, plan

D1, D2, D3 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)  # пн, вт, ср одной недели


def mk_part(order_id, day, start, end, venue=1, difficulty=5, extra=0, part_no=1, parts_total=1, work=None):
    """Часть заказа; время в часах (14.5 = 14:30)"""
    s, e = round(start * 60), round(end * 60)
    return PlanPart(key=f'{order_id}:{part_no}', order_id=order_id, date=day, start=s, end=e + extra,
                    work_minutes=work if work is not None else e - s + extra, venue_id=venue, venue_name=f'Центр {venue}',
                    venue_difficulty=difficulty, extra_minutes=extra, part_no=part_no, parts_total=parts_total)


def mk_staff(sid, skill=5, max_orders=3, avail=None):
    return PlanStaff(id=sid, name=f'Фото{sid}', skill=skill, max_orders=max_orders, availability=avail or {})


def routes(table):
    """travel-функция по словарю {(a, b): минуты}; пары без записи - нет маршрута"""
    return lambda a, b: table.get((a, b))


def owners(result):
    return {e.part.key: e.staff_id for e in result.entries}


class NeedTests(SimpleTestCase):
    def test_need_grows_with_duration_and_extra_time(self):
        self.assertEqual(part_need(mk_part(1, D1, 10, 11, difficulty=5)), 5.0)
        self.assertEqual(part_need(mk_part(1, D1, 10, 12, difficulty=5)), 6.0)
        self.assertEqual(part_need(mk_part(1, D1, 10, 14, difficulty=5)), 7.0)   # надбавка за длительность ограничена
        self.assertEqual(part_need(mk_part(1, D1, 10, 11, difficulty=5, extra=30, work=90)), 5.5 + 0.5)
        self.assertEqual(part_need(mk_part(1, D1, 10, 16, difficulty=10)), 10.0)  # потолок шкалы


class HardConstraintTests(SimpleTestCase):
    def test_vacation_and_unparsed_availability_block_the_day(self):
        away = {D1: day_availability('Отпуск', None)}
        garbled = {D1: parse_availability('ПОЛ ДНЯ')}
        result = plan([mk_part(1, D1, 10, 11)], [mk_staff(1, avail=away), mk_staff(2, avail=garbled)])
        entry = result.entries[0]
        self.assertIsNone(entry.staff_id)
        self.assertIn('Фото1: отпуск', entry.rejected)
        self.assertTrue(any('не разобрано' in r for r in entry.rejected))

    def test_time_window_must_cover_the_whole_order(self):
        late = {D1: parse_availability('с 15:00')}
        early = {D1: parse_availability('до 12:00')}
        morning = mk_part(1, D1, 10, 11)
        evening = mk_part(2, D1, 16, 17)
        result = plan([morning, evening], [mk_staff(1, avail=late), mk_staff(2, avail=early)])
        self.assertEqual(owners(result), {'1:1': 2, '2:1': 1})
        # заказ, выходящий за окно, не берётся
        edge = plan([mk_part(3, D1, 11, 13)], [mk_staff(1, avail=early)])
        self.assertIsNone(edge.entries[0].staff_id)
        self.assertIn('доступен 00:00-12:00', edge.entries[0].rejected[0])

    def test_daily_limit(self):
        parts = [mk_part(i, D1, 10 + 3 * i, 11 + 3 * i) for i in range(3)]
        result = plan(parts, [mk_staff(1, max_orders=2)], travel=routes({}))
        self.assertEqual(sum(1 for e in result.entries if e.staff_id), 2)
        left = result.unassigned
        self.assertEqual(len(left), 1)
        self.assertIn('уже 2 из 2 заказов', left[0].rejected[0])

    def test_overlapping_orders_go_to_different_photographers(self):
        parts = [mk_part(1, D1, 10, 12), mk_part(2, D1, 11, 13)]
        result = plan(parts, [mk_staff(1), mk_staff(2)])
        self.assertEqual(sorted(owners(result).values()), [1, 2])
        single = plan(parts, [mk_staff(1)])
        self.assertEqual(len(single.unassigned), 1)
        self.assertIn('занят в это время', single.unassigned[0].rejected[0])

    def test_travel_time_plus_buffer_is_required_between_centers(self):
        a, b = mk_part(1, D1, 10, 11, venue=1), mk_part(2, D1, 11.5, 12.5, venue=2)  # между ними 30 мин
        cfg = PlannerConfig(buffer_min=15)
        slow = plan([a, b], [mk_staff(1)], travel=routes({(1, 2): 20}), config=cfg)   # 20 + 15 = 35 > 30
        self.assertEqual(len(slow.unassigned), 1)
        self.assertIn('нужно 35 мин', slow.unassigned[0].rejected[0])
        fast = plan([a, b], [mk_staff(1)], travel=routes({(1, 2): 15}), config=cfg)   # 15 + 15 = 30 - впритык
        self.assertEqual(len(fast.unassigned), 0)

    def test_direction_of_route_matters(self):
        a, b = mk_part(1, D1, 10, 11, venue=1), mk_part(2, D1, 11.5, 12.5, venue=2)
        result = plan([a, b], [mk_staff(1)], travel=routes({(1, 2): 10, (2, 1): 60}))
        self.assertEqual(len(result.unassigned), 0)
        reverse = plan([b, a], [mk_staff(1)], travel=routes({(1, 2): 60, (2, 1): 10}))
        self.assertEqual(len(reverse.unassigned), 1)

    def test_same_center_needs_only_the_buffer(self):
        a, b = mk_part(1, D1, 10, 11, venue=1), mk_part(2, D1, 11.25, 12, venue=1)
        self.assertEqual(len(plan([a, b], [mk_staff(1)]).unassigned), 0)
        tight = mk_part(3, D1, 11.1, 12, venue=1)
        self.assertEqual(len(plan([a, tight], [mk_staff(1)]).unassigned), 1)

    def test_missing_route_uses_conservative_default_and_is_reported(self):
        a, b = mk_part(1, D1, 10, 11, venue=1), mk_part(2, D1, 12, 13, venue=2)   # между ними 60 мин
        result = plan([a, b], [mk_staff(1)], travel=routes({}), config=PlannerConfig(default_travel_min=90))
        self.assertEqual(len(result.unassigned), 1)
        self.assertEqual(result.defaulted_routes, [(1, 2)])
        # с коротким значением по умолчанию помещаются, но использование значения всё равно помечено
        ok = plan([a, b], [mk_staff(1)], travel=routes({}), config=PlannerConfig(default_travel_min=30))
        self.assertEqual(len(ok.unassigned), 0)
        self.assertEqual(ok.defaulted_routes, [(1, 2)])
        self.assertTrue(any('маршрут не задан' in r for e in ok.assigned for r in e.reasons))

    def test_manual_assignments_are_kept_and_occupy_time_and_limit(self):
        manual = mk_part(10, D1, 10, 12)
        busy = plan([mk_part(1, D1, 11, 13)], [mk_staff(1), mk_staff(2)], fixed=[(1, manual)])
        self.assertEqual(owners(busy), {'1:1': 2})
        full = plan([mk_part(1, D1, 15, 16)], [mk_staff(1, max_orders=1)], fixed=[(1, manual)])
        self.assertIn('уже 1 из 1 заказов', full.entries[0].rejected[0])
        # ручное назначение не попадает в результат и не меняется
        self.assertEqual([e.part.key for e in busy.entries], ['1:1'])

    def test_fixed_for_unknown_staff_is_ignored(self):
        result = plan([mk_part(1, D1, 10, 11)], [mk_staff(1)], fixed=[(99, mk_part(10, D1, 10, 11))])
        self.assertEqual(owners(result), {'1:1': 1})


class SplitOrderTests(SimpleTestCase):
    def two_parts(self):
        return [mk_part(1, D1, 10, 11, part_no=1, parts_total=2), mk_part(1, D1, 14, 15, part_no=2, parts_total=2)]

    def test_parts_of_one_order_count_once_against_the_limit(self):
        result = plan(self.two_parts(), [mk_staff(1, max_orders=1)])
        self.assertEqual(len(result.unassigned), 0)
        self.assertEqual(set(owners(result).values()), {1})

    def test_free_gap_can_host_another_order(self):
        middle = mk_part(2, D1, 12, 13)
        result = plan(self.two_parts() + [middle], [mk_staff(1)])
        self.assertEqual(len(result.unassigned), 0)

    def test_parts_may_go_to_different_photographers_when_one_cannot_take_both(self):
        morning_only = {D1: parse_availability('до 12:00')}
        evening_only = {D1: parse_availability('с 13:00')}
        result = plan(self.two_parts(), [mk_staff(1, avail=morning_only), mk_staff(2, avail=evening_only)])
        self.assertEqual(owners(result), {'1:1': 1, '1:2': 2})
        notes = [r for e in result.assigned for r in e.reasons if r.startswith('Часть')]
        self.assertEqual(len(notes), 2)

    def test_split_is_avoided_when_one_photographer_can_take_everything(self):
        result = plan(self.two_parts(), [mk_staff(1), mk_staff(2)])
        self.assertEqual(len(set(owners(result).values())), 1)


class SoftRulesTests(SimpleTestCase):
    def test_hard_orders_go_to_skilled_photographers_and_easy_ones_to_the_rest(self):
        hard = mk_part(1, D1, 10, 12, difficulty=9)
        easy = mk_part(2, D1, 10, 11, difficulty=2)
        result = plan([hard, easy], [mk_staff(1, skill=3), mk_staff(2, skill=9)])
        self.assertEqual(owners(result), {'1:1': 2, '2:1': 1})

    def test_load_is_spread_across_equal_photographers(self):
        parts = [mk_part(i, d, 10, 11) for i, d in enumerate((D1, D2, D3, D1, D2, D3))]
        result = plan(parts, [mk_staff(1), mk_staff(2)])
        counts = [list(owners(result).values()).count(s) for s in (1, 2)]
        self.assertEqual(counts, [3, 3])

    def test_known_center_is_preferred(self):
        part = mk_part(1, D1, 10, 11, venue=7)
        result = plan([part], [mk_staff(1), mk_staff(2)], familiarity={(2, 7): 4})
        self.assertEqual(result.entries[0].staff_id, 2)
        self.assertIn('Уже работал в этом центре: 4 зак.', result.entries[0].reasons)

    def test_result_is_deterministic(self):
        parts = [mk_part(i, d, 9 + i, 10 + i, venue=1 + i % 3, difficulty=3 + i % 5) for i, d in enumerate((D1, D2) * 4)]
        staff = [mk_staff(1, skill=4), mk_staff(2, skill=7), mk_staff(3, skill=9, max_orders=2)]
        table = routes({(a, b): 20 + 5 * abs(a - b) for a in (1, 2, 3) for b in (1, 2, 3) if a != b})
        first, second = plan(parts, staff, travel=table), plan(list(reversed(parts)), list(reversed(staff)), travel=table)
        self.assertEqual(owners(first), owners(second))
        self.assertEqual(round(first.total_cost, 6), round(second.total_cost, 6))


WEEK = D1.isocalendar()[:2]          # 2.11-8.11.2026
D_SAT, D_SUN, D_NEXT_MON = date(2026, 11, 7), date(2026, 11, 8), date(2026, 11, 9)


class WeekLoadTests(SimpleTestCase):
    """Распределение запускают на один день, поэтому нагрузка недели приходит из заказов, уже назначенных на остальные дни"""

    def test_without_outside_orders_equals_are_tied_and_the_lower_id_wins(self):
        self.assertEqual(plan([mk_part(1, D2, 10, 11)], [mk_staff(1), mk_staff(2)], date_from=D2, date_to=D2).entries[0].staff_id, 1)

    def test_orders_already_assigned_on_other_days_of_the_week_push_the_order_to_the_less_loaded(self):
        result = plan([mk_part(1, D2, 10, 11)], [mk_staff(1), mk_staff(2)], date_from=D2, date_to=D2,
                      week_load={(1, WEEK): 6})
        self.assertEqual(result.entries[0].staff_id, 2)

    def test_the_load_of_another_week_is_not_counted(self):
        result = plan([mk_part(1, D_SUN, 10, 11)], [mk_staff(1), mk_staff(2)], date_from=D_SUN, date_to=D_SUN,
                      week_load={(1, D_NEXT_MON.isocalendar()[:2]): 9})
        self.assertEqual(result.entries[0].staff_id, 1)

    def test_a_one_day_plan_is_balanced_by_the_week_not_by_the_day(self):
        # трое заказов в один день, лимит 3: без недели всё ушло бы одному; у первого уже 5 заказов на неделе - берут и другие
        parts = [mk_part(i, D2, 9 + 3 * i, 10 + 3 * i) for i in range(3)]
        staff = [mk_staff(1, skill=5, max_orders=3), mk_staff(2, skill=5, max_orders=3)]
        calm = plan(parts, staff, date_from=D2, date_to=D2)
        busy = plan(parts, staff, date_from=D2, date_to=D2, week_load={(1, WEEK): 5})
        self.assertEqual(sorted(owners(calm).values()).count(2), 0 if len(set(owners(calm).values())) == 1 else sorted(owners(calm).values()).count(2))
        self.assertGreater(list(owners(busy).values()).count(2), list(owners(calm).values()).count(2))

    def test_the_marginal_cost_is_what_matters_not_the_whole_week(self):
        # у обоих по 4 заказа вне периода - ничья, как и у обоих без заказов: важен прирост, а не накопленная нагрузка
        both = plan([mk_part(1, D2, 10, 11)], [mk_staff(1), mk_staff(2)], date_from=D2, date_to=D2,
                    week_load={(1, WEEK): 4, (2, WEEK): 4})
        self.assertEqual(both.entries[0].staff_id, 1)

    def test_stronger_photographer_carries_more_of_the_week(self):
        # у сильного вес выше: при одинаковых 3 заказах вне периода слабому лишний заказ обходится дороже
        result = plan([mk_part(1, D2, 10, 11, difficulty=5)], [mk_staff(1, skill=5), mk_staff(2, skill=7)], date_from=D2, date_to=D2,
                      week_load={(1, WEEK): 3, (2, WEEK): 3})
        self.assertEqual(result.entries[0].staff_id, 2)

    def test_available_days_are_counted_over_the_whole_week_even_for_a_one_day_plan(self):
        away = {D1 + timedelta(days=i): day_availability('Отпуск', None) for i in range(5)}      # пн-пт в отпуске
        planner = Planner([mk_part(1, D_SAT, 10, 11)], [mk_staff(1, avail=away), mk_staff(2)], date_from=D_SAT, date_to=D_SAT)
        self.assertEqual((planner._week_days[(1, WEEK)], planner._week_days[(2, WEEK)]), (2, 7))
        self.assertLess(planner._week_cap(planner.staff[1], WEEK), planner._week_cap(planner.staff[2], WEEK))
        # у кого доступных дней меньше, тому лишний заказ обходится дороже
        self.assertEqual(planner.solve().entries[0].staff_id, 2)

    def test_a_period_crossing_the_week_boundary_knows_both_weeks(self):
        planner = Planner([mk_part(1, D_SUN, 10, 11), mk_part(2, D_NEXT_MON, 10, 11)], [mk_staff(1)], date_from=D_SUN, date_to=D_NEXT_MON)
        self.assertEqual({week for _, week in planner._week_days}, {WEEK, D_NEXT_MON.isocalendar()[:2]})

    def test_explanation_shows_both_parts_of_the_weekly_load(self):
        result = plan([mk_part(1, D2, 10, 11)], [mk_staff(1), mk_staff(2)], date_from=D2, date_to=D2, week_load={(2, WEEK): 2, (1, WEEK): 1})
        entry = result.entries[0]
        text = '\n'.join(entry.reasons)
        owner = entry.staff_id
        outside = {1: 1, 2: 2}[owner]
        self.assertIn(f'Нагрузка за неделю 02.11-08.11: заказов {1 + outside} (в периоде расчёта 1, вне него уже назначено в таблицах {outside})', text)
        self.assertIn('расчётная ёмкость недели ≈ 14.0', text)
        self.assertIn('дневной лимит 3 - только жёсткий потолок', text)

    def test_explanation_calls_the_runner_up_the_best_replacement(self):
        entry = plan([mk_part(1, D2, 10, 11)], [mk_staff(1), mk_staff(2)], date_from=D2, date_to=D2).entries[0]
        text = '\n'.join(entry.reasons)
        self.assertIn('Подходило фотографов: 2; лучшая замена - Фото2', text)
        self.assertNotIn('по очереди', text)


class EjectionTests(SimpleTestCase):
    def test_unassigned_part_displaces_another_that_can_move(self):
        # у стоит только фотограф 1 (у 2 окно с 12:00), но он занят заказом, который мог бы взять и фотограф 2
        early = mk_part(1, D1, 10, 11)
        late = mk_part(2, D1, 14, 15)
        staff = [mk_staff(1, max_orders=1), mk_staff(2, max_orders=1, avail={D1: parse_availability('с 12:00')})]
        planner = Planner([early, late], staff)
        planner._place(late, 1)   # неудачное начальное состояние
        self.assertTrue(planner._try_eject())
        self.assertEqual(planner.owner, {'1:1': 1, '2:1': 2})

    def test_full_solve_finds_the_same_arrangement(self):
        early, late = mk_part(1, D1, 10, 11), mk_part(2, D1, 14, 15)
        staff = [mk_staff(1, max_orders=1), mk_staff(2, max_orders=1, avail={D1: parse_availability('с 12:00')})]
        self.assertEqual(owners(plan([early, late], staff)), {'1:1': 1, '2:1': 2})


class ExplanationTests(SimpleTestCase):
    def test_assigned_entry_explains_choice_and_alternatives(self):
        manual = mk_part(10, D1, 9, 10, venue=1)
        part = mk_part(1, D1, 12, 13, venue=2, difficulty=6)
        result = plan([part], [mk_staff(1, skill=6), mk_staff(2, skill=5)], fixed=[(1, manual)], travel=routes({(1, 2): 30}),
                      familiarity={(1, 2): 2}, date_from=D1, date_to=date(2026, 11, 8))   # неделя целиком
        entry = result.entries[0]
        self.assertEqual(entry.staff_id, 1)
        text = '\n'.join(entry.reasons)
        self.assertIn('Навык 6, сложность заказа 6.0', text)
        self.assertIn('До этого: Центр 1 09:00-10:00 (назначен вручную), дорога 30 мин', text)
        self.assertIn('Подходило фотографов: 2', text)
        self.assertEqual(entry.candidates, 2)
        self.assertTrue(entry.alternatives[0].startswith('Фото2: штраф'))

    def test_unassigned_entry_lists_a_reason_for_each_photographer(self):
        staff = [mk_staff(1, avail={D1: day_availability('Больничный', None)}), mk_staff(2, max_orders=1)]
        result = plan([mk_part(1, D1, 10, 11), mk_part(2, D1, 15, 16)], staff)
        entry = result.unassigned[0]
        self.assertEqual(len(entry.rejected), 2)
        self.assertTrue(any('больничный' in r for r in entry.rejected))
        self.assertTrue(any('уже 1 из 1' in r for r in entry.rejected))

    def test_no_staff_at_all(self):
        entry = plan([mk_part(1, D1, 10, 11)], []).entries[0]
        self.assertIsNone(entry.staff_id)
        self.assertIn('нет выездных фотографов', entry.reasons[0])

    def test_empty_input(self):
        self.assertEqual(plan([], [mk_staff(1)]).entries, [])


def verify_plan(testcase, result, parts, staff, fixed, travel, cfg=PlannerConfig()):
    """Независимая проверка жёстких ограничений итогового плана (не использует внутренности Planner).
    Ручные назначения - входные данные: конфликты между ними не проверяются, только конфликты с распределёнными частями."""
    by_id = {s.id: s for s in staff}
    days = {}
    for sid, part in fixed:
        if sid in by_id:
            days.setdefault((sid, part.date), []).append((part, False))
    for e in result.entries:
        if e.staff_id is not None:
            days.setdefault((e.staff_id, e.part.date), []).append((e.part, True))

    def gap_needed(x, y):
        if x.order_id == y.order_id:
            return 0
        return (0 if x.venue_id == y.venue_id else (travel(x.venue_id, y.venue_id) or cfg.default_travel_min)) + cfg.buffer_min

    for (sid, day), entries in days.items():
        s = by_id[sid]
        items = [p for p, _ in entries]
        fixed_orders = {p.order_id for p, planned in entries if not planned}
        testcase.assertLessEqual(len({p.order_id for p in items}), max(s.max_orders, len(fixed_orders)),
                                 f'{s.name} {day}: превышен лимит заказов')
        for p, planned in entries:
            if not planned:
                continue
            a = s.avail(day)
            testcase.assertTrue(a.covers(p.start, p.end), f'{s.name} {day}: {p.title} вне доступности {a.describe()}')
            others = [x for x in items if x is not p]
            for x in others:
                testcase.assertFalse(x.start < p.end and p.start < x.end, f'{s.name} {day}: {p.title} пересекается с {x.title}')
            before = [x for x in others if x.end <= p.start]
            after = [x for x in others if x.start >= p.end]
            if before:
                x = max(before, key=lambda i: i.end)
                testcase.assertGreaterEqual(p.start - x.end, gap_needed(x, p), f'{s.name} {day}: {x.title} -> {p.title}')
            if after:
                y = min(after, key=lambda i: i.start)
                testcase.assertGreaterEqual(y.start - p.end, gap_needed(p, y), f'{s.name} {day}: {p.title} -> {y.title}')


class InvariantTests(SimpleTestCase):
    """Случайные сценарии: что бы ни было на входе, жёсткие ограничения в итоговом плане соблюдены, а результат воспроизводим"""

    def scenario(self, seed, n_parts=30, n_staff=5):
        import random
        rnd = random.Random(seed)
        days = [D1, D2, D3]
        venues = list(range(1, 5))
        table = {(a, b): rnd.choice([None, 15, 30, 45, 70]) for a in venues for b in venues if a != b}
        staff = []
        for sid in range(1, n_staff + 1):
            avail = {}
            for d in days:
                roll = rnd.random()
                if roll < 0.15:
                    avail[d] = day_availability('Отпуск', None)
                elif roll < 0.35:
                    avail[d] = parse_availability(rnd.choice(['с 14:00', 'до 15:00', '11:00-19:00', 'ПОЛ ДНЯ', 'Занят 12:00-14:00']))
            staff.append(mk_staff(sid, skill=rnd.randint(3, 10), max_orders=rnd.randint(1, 4), avail=avail))
        parts, fixed = [], []
        for oid in range(1, n_parts + 1):
            start = rnd.choice([9, 10, 11, 12, 13, 14, 15, 16, 17, 18]) + rnd.choice([0, 0.5])
            dur = rnd.choice([1, 1, 1.5, 2, 3])
            if rnd.random() < 0.2:
                first = mk_part(oid, rnd.choice(days), start, start + 1, venue=rnd.choice(venues), part_no=1, parts_total=2,
                                difficulty=rnd.randint(1, 10))
                second = mk_part(oid, first.date, start + 3, start + 4, venue=first.venue_id, part_no=2, parts_total=2,
                                 difficulty=first.venue_difficulty)
                new = [first, second]
            else:
                new = [mk_part(oid, rnd.choice(days), start, start + dur, venue=rnd.choice(venues), difficulty=rnd.randint(1, 10))]
            if rnd.random() < 0.15:
                fixed.extend((rnd.randint(1, n_staff), p) for p in new)   # назначено вручную, может нарушать что угодно
            else:
                parts.extend(new)
        return parts, staff, fixed, routes(table), table

    def test_hard_constraints_hold_on_random_scenarios(self):
        for seed in range(60):
            parts, staff, fixed, travel, _ = self.scenario(seed)
            result = plan(parts, staff, fixed, travel, date_from=D1, date_to=D3)
            self.assertEqual(len(result.entries), len(parts), seed)
            for e in result.unassigned:
                self.assertTrue(e.rejected, f'seed {seed}: у нераспределённой части нет причин')
            verify_plan(self, result, parts, staff, fixed, travel)

    def test_manual_assignments_never_change(self):
        parts, staff, fixed, travel, _ = self.scenario(7)
        result = plan(parts, staff, fixed, travel)
        self.assertFalse({p.key for _, p in fixed} & {e.part.key for e in result.entries})

    def test_large_input_is_fast_enough(self):
        import time as _time
        parts, staff, fixed, travel, _ = self.scenario(3, n_parts=150, n_staff=8)
        started = _time.monotonic()
        result = plan(parts, staff, fixed, travel, date_from=D1, date_to=D3)
        self.assertLess(_time.monotonic() - started, 10)
        verify_plan(self, result, parts, staff, fixed, travel)
