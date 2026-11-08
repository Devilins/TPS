from django.contrib.auth.models import Permission, User
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from tph_system.forms import StaffForm
from tph_system.models import Staff, Store

from .forms import RouteCreateForm, VenueForm
from .gsheet import (KIND_CENTER, KIND_IGNORED, KIND_TRIPS, KIND_VIDEO, SheetError, _TAB_RE, center_name, classify_tab,
                     get_sheet_id)
from .models import PhotoOrder, Route, Venue
from .routes_io import RoutesImportError, export_routes_csv, import_routes_csv


class TabParsingTests(SimpleTestCase):
    def test_tabs_regex_on_htmlview_fragment(self):
        html = ('items.push({name: "ГАГАРИНСКИЙ", pageUrl: "https:\\/\\/docs.google.com\\/x?gid\\x3d0", gid: "0",'
                'initialSheet: ("0" == gid)});items.push({name: "ВЫЕЗДЫ", pageUrl: "u", gid: "724735900",'
                'initialSheet: false});')
        self.assertEqual(_TAB_RE.findall(html), [('ГАГАРИНСКИЙ', '0'), ('ВЫЕЗДЫ', '724735900')])

    def test_jj_sheet_takes_only_jj_centers(self):
        self.assertEqual(classify_tab('JJ', 'Облака JJ'), (KIND_CENTER, 'Облака'))
        self.assertEqual(classify_tab('JJ', 'РИО JJ'), (KIND_CENTER, 'РИО'))
        # листы Laserland и служебные в таблице Joki Joya игнорируются
        for name in ('ГАГАРИНСКИЙ LL', 'Каширка LL', 'ВЫЕЗДЫ', 'ВИДЕО ВСЕ ЦЕНТРЫ'):
            self.assertEqual(classify_tab('JJ', name)[0], KIND_IGNORED, name)

    def test_ll_sheet_kinds(self):
        for name in ('ГАГАРИНСКИЙ', 'БЕГОВАЯ', 'Каширка', 'АЗОВСКИЙ', 'Миниляндия'):
            self.assertEqual(classify_tab('LL', name), (KIND_CENTER, name), name)
        self.assertEqual(classify_tab('LL', 'ШОУ ВСЕ ЦЕНТРЫ')[0], KIND_IGNORED)
        self.assertEqual(classify_tab('LL', 'ВЫЕЗДЫ')[0], KIND_TRIPS)
        self.assertEqual(classify_tab('LL', ' Видео все центры ')[0], KIND_VIDEO)

    def test_center_name(self):
        self.assertEqual(center_name('ГАГАРИНСКИЙ', 'LL'), 'Гагаринский LL')
        self.assertEqual(center_name('Гагаринский', 'JJ'), 'Гагаринский JJ')
        self.assertEqual(center_name('Каширка', 'LL'), 'Каширка LL')

    @override_settings(SCHAUTO_SHEET_IDS={'LL': '', 'JJ': 'jj-id'})
    def test_sheet_id_required(self):
        with self.assertRaises(SheetError):
            get_sheet_id('LL')
        self.assertEqual(get_sheet_id('JJ'), 'jj-id')
        self.assertEqual(get_sheet_id('LL', 'abc'), 'abc')


class VenueTests(TestCase):
    def test_tab_is_unique_within_brand_only(self):
        Venue.objects.create(name='Гагаринский LL', brand='LL', sheet_tab_name='ГАГАРИНСКИЙ')
        # тот же лист в таблице другого бренда - это другой центр
        Venue.objects.create(name='Гагаринский JJ', brand='JJ', sheet_tab_name='ГАГАРИНСКИЙ')
        form = VenueForm({'name': 'Дубль', 'brand': 'LL', 'difficulty': 5, 'sheet_tab_name': 'ГАГАРИНСКИЙ',
                          'is_active': 'on'})
        self.assertFalse(form.is_valid())
        # центры без листа не конфликтуют друг с другом
        Venue.objects.create(name='Без листа 1', brand='LL')
        Venue.objects.create(name='Без листа 2', brand='LL')


class VenueStoreTests(TestCase):
    def test_only_active_stores_can_be_linked(self):
        active = Store.objects.create(name='Laserland Кунцево', short_name='LLKun', store_status='Действующая')
        closed = Store.objects.create(name='Laserland Азовский', short_name='LLAzv', store_status='Закрытая')
        technical = Store.objects.create(name='Запас', short_name='Запас', store_status='Техническая')
        base = {'name': 'Кунцево LL', 'brand': 'LL', 'difficulty': 5, 'is_active': 'on'}
        self.assertTrue(VenueForm({**base, 'store': active.id}).is_valid())
        for store in (closed, technical):
            form = VenueForm({**base, 'store': store.id})
            self.assertFalse(form.is_valid(), store)
            self.assertIn('store', form.errors)
        self.assertEqual(list(VenueForm().fields['store'].queryset), [active])


class RouteTests(TestCase):
    def setUp(self):
        self.a = Venue.objects.create(name='Центр А', brand='LL')
        self.b = Venue.objects.create(name='Центр Б', brand='JJ')

    def test_create_form_makes_reverse_route_once(self):
        data = {'from_venue': self.a.id, 'to_venue': self.b.id, 'description': 'метро', 'duration_min': 35,
                'create_reverse': 'on'}
        form = RouteCreateForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(Route.objects.get(from_venue=self.b, to_venue=self.a, description='метро').duration_min, 35)
        # существующий обратный вариант не перезатирается
        Route.objects.filter(from_venue=self.b).update(duration_min=50)
        RouteCreateForm({**data, 'description': 'метро', 'duration_min': 40}).is_valid()
        self.assertEqual(Route.objects.get(from_venue=self.b, to_venue=self.a).duration_min, 50)

    def test_same_venue_rejected(self):
        form = RouteCreateForm({'from_venue': self.a.id, 'to_venue': self.a.id, 'duration_min': 5})
        self.assertFalse(form.is_valid())

    def test_import_with_mirror_and_blank_rows(self):
        csv_bytes = ('Откуда;Куда;Минут;Вариант\n'
                     'Центр А;Центр Б;30;метро\n'
                     'Центр Б;Центр А;;\n').encode('utf-8-sig')
        res = import_routes_csv(csv_bytes, mirror=True)
        self.assertEqual(res, {'created': 1, 'updated': 0, 'mirrored': 1, 'skipped': 1})
        self.assertEqual(Route.objects.get(from_venue=self.b, to_venue=self.a, description='метро').duration_min, 30)
        # повторная загрузка обновляет, а не дублирует
        res = import_routes_csv(csv_bytes.replace(b'30', b'25'), mirror=False)
        self.assertEqual((res['created'], res['updated']), (0, 1))
        self.assertEqual(Route.objects.count(), 2)

    def test_import_is_all_or_nothing(self):
        csv_bytes = 'Центр А;Центр Б;30;\nЦентр А;Неизвестный;10;\nЦентр Б;Центр А;abc;\n'.encode('utf-8')
        with self.assertRaises(RoutesImportError) as ctx:
            import_routes_csv(csv_bytes, mirror=True)
        self.assertEqual(len(ctx.exception.errors), 2)
        self.assertEqual(Route.objects.count(), 0)

    def test_import_cp1251_and_comma_delimiter(self):
        csv_bytes = 'Откуда,Куда,Минут\nЦентр А,Центр Б,20\n'.encode('cp1251')
        import_routes_csv(csv_bytes, mirror=False)
        self.assertEqual(Route.objects.get().duration_min, 20)

    def test_export_contains_missing_pairs_as_template(self):
        Route.objects.create(from_venue=self.a, to_venue=self.b, duration_min=30)
        lines = export_routes_csv().strip().splitlines()
        self.assertEqual(lines[0], 'Откуда;Куда;Минут;Вариант')
        self.assertIn('Центр А;Центр Б;30;', lines)
        self.assertIn('Центр Б;Центр А;;', lines)


class StaffFormTests(TestCase):
    base = {'f_name': 'Иванов', 'name': 'Иван', 'date_empl': '01.01.2026', 'dism_status': 'Работает',
            'staff_type': 'Штат', 'retouches_own': 'on'}

    def test_outbound_requires_skill_and_limit(self):
        form = StaffForm({**self.base, 'staff_type': 'Выездной'})
        self.assertFalse(form.is_valid())
        self.assertIn('skill_score', form.errors)
        self.assertIn('max_orders_per_day', form.errors)
        self.assertFalse(StaffForm({**self.base, 'staff_type': 'Выездной', 'skill_score': 7}).is_valid())

    def test_retoucher_requires_only_skill(self):
        self.assertFalse(StaffForm({**self.base, 'staff_type': 'Ретушер'}).is_valid())
        self.assertTrue(StaffForm({**self.base, 'staff_type': 'Ретушер', 'skill_score': 6}).is_valid())

    def test_skill_range(self):
        data = {**self.base, 'staff_type': 'Выездной', 'max_orders_per_day': 3}
        self.assertFalse(StaffForm({**data, 'skill_score': 11}).is_valid())
        self.assertFalse(StaffForm({**data, 'skill_score': 0}).is_valid())
        self.assertTrue(StaffForm({**data, 'skill_score': 7}).is_valid())

    def test_regular_staff_needs_no_skill(self):
        self.assertTrue(StaffForm(self.base).is_valid())


class PagesSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('admin_t', 'a@example.com', 'x')
        a = Venue.objects.create(name='Центр А', brand='LL')
        b = Venue.objects.create(name='Центр Б', brand='JJ')
        Route.objects.create(from_venue=a, to_venue=b, duration_min=30)
        Staff.objects.create(f_name='Тестов', name='Тест', date_empl='2026-01-01', staff_type='Выездной')

    def setUp(self):
        self.client.force_login(self.user)

    def test_pages_render(self):
        for name in ('schauto:index', 'schauto:venues', 'schauto:routes'):
            resp = self.client.get(reverse(name) + ('?is_active=1' if name == 'schauto:venues' else ''))
            self.assertEqual(resp.status_code, 200, name)
        self.assertEqual(self.client.get(reverse('schauto:routes_export')).status_code, 200)

    def test_lists_are_paginated_by_40(self):
        for i in range(45):
            Venue.objects.create(name=f'Центр {i:02d}', brand='LL')
        resp = self.client.get(reverse('schauto:venues') + '?is_active=1')
        self.assertEqual((len(resp.context['page_obj']), resp.context['paginator'].num_pages), (40, 2))
        self.assertContains(resp, 'page=2')
        self.assertEqual(len(self.client.get(reverse('schauto:venues') + '?is_active=1&page=2').context['page_obj']), 7)  # 47 всего

    def test_venues_redirects_to_default_filter(self):
        resp = self.client.get(reverse('schauto:venues'))
        self.assertRedirects(resp, reverse('schauto:venues') + '?is_active=1')

    def test_address_is_saved_and_counted(self):
        form = VenueForm({'name': 'Кунцево LL', 'brand': 'LL', 'address': 'ТЦ Вегас (Кунцево), Хорошёвский пр., 14', 'difficulty': 5,
                          'is_active': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        resp = self.client.get(reverse('schauto:index'))
        self.assertEqual(resp.context['venues_no_address'], 2)   # «Центр А» и «Центр Б» без адреса, новый - с адресом
        resp = self.client.get(reverse('schauto:venues') + '?is_active=1')
        self.assertContains(resp, 'Хорошёвский пр., 14')
        self.assertContains(resp, 'не указан')

    def test_index_reports_outbound_without_skill(self):
        resp = self.client.get(reverse('schauto:index'))
        self.assertEqual(resp.context['outbound_count'], 1)
        self.assertEqual(resp.context['outbound_no_skill'], 1)
        self.assertEqual(resp.context['pairs_missing'], 1)  # есть А->Б, нет Б->А

    def test_update_pages_render(self):
        venue, route = Venue.objects.first(), Route.objects.first()
        for url in (reverse('schauto:venue_update', args=[venue.pk]), reverse('schauto:venue_delete', args=[venue.pk]),
                    reverse('schauto:route_update', args=[route.pk]), reverse('schauto:route_delete', args=[route.pk])):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_staff_page_renders_with_new_columns(self):
        resp = self.client.get(reverse('staff') + '?dism_status=Работает')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Навыки')


class IndexPageTests(TestCase):
    """Главная страница раздела: статус готовности, плитки разделов, карточки показателей"""

    def setUp(self):
        self.user = User.objects.create(username='boss', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.a = Venue.objects.create(name='Центр А', brand='LL', address='ул. Первая, 1')
        self.b = Venue.objects.create(name='Центр Б', brand='JJ', address='ул. Вторая, 2')

    def ready(self):
        Route.objects.create(from_venue=self.a, to_venue=self.b, duration_min=30)
        Route.objects.create(from_venue=self.b, to_venue=self.a, duration_min=30)
        Staff.objects.create(f_name='Тестов', name='Тест', date_empl='2026-01-01', staff_type='Выездной', skill_score=7, max_orders_per_day=3)

    def order(self, **kw):
        return PhotoOrder.objects.create(brand='LL', tab_name='Лист', sheet_row=1, fingerprint=f'fp{PhotoOrder.objects.count()}',
                                         date=timezone.localdate(), venue=self.a, last_seen_at=timezone.now(), **kw)

    def test_everything_filled_shows_the_success_banner_and_no_attention_list(self):
        self.ready()
        resp = self.client.get(reverse('schauto:index'))
        self.assertEqual(resp.context['attention'], [])
        self.assertContains(resp, 'Данные готовы к распределению')
        self.assertNotContains(resp, 'Чтобы распределение было точным')

    def test_problems_are_listed_with_links_to_where_they_are_fixed(self):
        Staff.objects.create(f_name='Тестов', name='Тест', date_empl='2026-01-01', staff_type='Выездной')       # без навыка и лимита
        Venue.objects.create(name='Центр В', brand='LL')                                                       # без адреса
        self.order(status=PhotoOrder.STATUS_NEEDS_FIX)
        self.order(status=PhotoOrder.STATUS_ASSIGNED, photographer_raw='Какая-то Даша')
        resp = self.client.get(reverse('schauto:index'))
        found = {item['label']: item for item in resp.context['attention']}
        self.assertEqual(set(found), {'Выездные без оценки навыка', 'Выездные без лимита заказов в день', 'Центры без адреса',
                                      'Пары центров без маршрута', 'Не сопоставлено имён / адресов выездов', 'Заказы на ручную правку'})
        self.assertEqual(found['Не сопоставлено имён / адресов выездов']['url'], reverse('schauto:mapping'))
        self.assertEqual(found['Пары центров без маршрута']['url'], reverse('schauto:routes'))
        self.assertEqual(found['Центры без адреса']['url'], reverse('schauto:venues'))
        self.assertIn('status=needs_fix', found['Заказы на ручную правку']['url'])
        self.assertContains(resp, 'Чтобы распределение было точным, обратите внимание:')
        self.assertNotContains(resp, 'Данные готовы к распределению')

    def test_tiles_link_to_all_sections_for_a_full_access_user(self):
        resp = self.client.get(reverse('schauto:index'))
        for name in ('schauto:plan', 'schauto:orders', 'schauto:mapping', 'schauto:venues', 'schauto:routes', 'staff'):
            self.assertContains(resp, f'href="{reverse(name)}', msg_prefix=name)

    def test_user_with_the_section_permission_only_sees_no_forbidden_links(self):
        self.order(status=PhotoOrder.STATUS_NEEDS_FIX)
        viewer, _ = User.objects.get_or_create(username='viewer')
        viewer.user_permissions.set(Permission.objects.filter(content_type__app_label='schauto', codename='view_venue'))
        self.client.force_login(viewer)
        resp = self.client.get(reverse('schauto:index'))
        self.assertEqual(resp.status_code, 200)
        for name in ('schauto:plan', 'schauto:orders', 'schauto:mapping', 'staff'):
            self.assertNotContains(resp, f'href="{reverse(name)}', msg_prefix=name)
        for item in resp.context['attention']:
            if item['label'] == 'Заказы на ручную правку':
                self.assertEqual(item['url'], '')                      # просмотра заказов нет - ссылки нет, но проблема видна
        self.assertContains(resp, 'Заказы на ручную правку')
        self.assertContains(resp, f'href="{reverse("schauto:venues")}')
        self.assertContains(resp, f'href="{reverse("schauto:routes")}')
