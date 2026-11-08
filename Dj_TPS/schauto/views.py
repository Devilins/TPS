from datetime import date, timedelta
from itertools import permutations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.generic import DeleteView, UpdateView

from tph_system.funcs import dt_format
from tph_system.models import ImplEvents, Staff

from .filters import PhotoOrderFilter, RouteFilter, VenueFilter
from .forms import (OrdersImportForm, PersonAliasForm, PlaceAliasForm, PlanRunForm, RouteCreateForm, RouteForm,
                    RoutesImportForm, VenueForm)
from .gsheet import BRANDS
from .importer import apply_mappings, run_import
from .models import Assignment, PhotoOrder, PlanRun, Route, StaffAlias, Venue, VenueAlias
from .mapping import PERSON_UNMATCHED, Resolver
from .parsers import PEOPLE_SEPARATOR, norm_person, norm_place
from .applying import (ConfirmResult, PlanNotDeletable, allowed_staff, apply_plan, delete_plan, rollback_plan, save_confirmations,
                       save_edits, validate_plan)
from .planning import run_plan
from .routes_io import RoutesImportError, MAX_ERRORS_SHOWN, export_routes_csv, import_routes_csv


PAGE_SIZE = 40  # строк на странице списков schauto
MAPPING_ROWS_SHOWN = 40  # строк в каждой таблице экрана сопоставлений (после сохранения список сокращается)


def _paginate(request, queryset):
    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)  # номер страницы подставляется в ссылках пагинации отдельно
    return paginator, page_obj, params.urlencode()


@login_required
@permission_required(perm='schauto.view_venue', raise_exception=True)
def index(request):
    """Стартовая страница: что уже готово для планирования, а чего не хватает"""
    venues = list(Venue.objects.filter(is_active=True))
    known_pairs = set(Route.objects.values_list('from_venue_id', 'to_venue_id'))
    pairs_total = len(venues) * (len(venues) - 1)
    pairs_missing = sum(1 for a, b in permutations(venues, 2) if (a.id, b.id) not in known_pairs)

    workers = Staff.objects.filter(dism_status='Работает')
    outbound = workers.filter(staff_type='Выездной')
    retouchers = workers.filter(staff_type='Ретушер')
    today = timezone.localdate()
    live_orders = PhotoOrder.objects.exclude(status=PhotoOrder.STATUS_GONE).filter(date__gte=today)
    unmatched_names, unmatched_places = _unmatched()
    stats = {
        'orders_open': live_orders.filter(status=PhotoOrder.STATUS_OPEN).count(),
        'orders_needs_fix': live_orders.filter(status=PhotoOrder.STATUS_NEEDS_FIX).count(),
        'unmatched_names': len(unmatched_names),
        'unmatched_places': len(unmatched_places),
        'outbound_no_limit': outbound.filter(max_orders_per_day__isnull=True).count(),
        'venues_count': len(venues),
        'venues_no_store': sum(1 for v in venues if v.store_id is None),
        'venues_no_address': sum(1 for v in venues if not v.address),
        'pairs_total': pairs_total,
        'pairs_missing': pairs_missing,
        'outbound_count': outbound.count(),
        'outbound_no_skill': outbound.filter(skill_score__isnull=True).count(),
        'retouchers_count': retouchers.count(),
        'retouchers_no_skill': retouchers.filter(skill_score__isnull=True).count(),
    }

    # что мешает точному распределению: ссылка есть только на разделы, доступные пользователю
    staff_url = f"{reverse('staff')}?dism_status=Работает" if request.user.has_perm('tph_system.view_staff') else ''
    mapping_url = reverse('schauto:mapping') if request.user.has_perm('schauto.import_orders') else ''
    orders_url = (f"{reverse('schauto:orders')}?status={PhotoOrder.STATUS_NEEDS_FIX}&date_from={dt_format(today)}"
                  if request.user.has_perm('schauto.view_photoorder') else '')
    attention = []
    for value, label, hint, url in (
            (stats['outbound_no_skill'], 'Выездные без оценки навыка', 'в расчёте не участвуют', staff_url),
            (stats['outbound_no_limit'], 'Выездные без лимита заказов в день', 'в расчёте не участвуют', staff_url),
            (stats['venues_no_address'], 'Центры без адреса', 'адрес нужен для карт и маршрутов', reverse('schauto:venues')),
            (f"{pairs_missing} из {pairs_total}" if pairs_missing else 0, 'Пары центров без маршрута',
             'время в пути возьмётся по умолчанию', reverse('schauto:routes')),
            (f"{stats['unmatched_names']} / {stats['unmatched_places']}" if stats['unmatched_names'] or stats['unmatched_places'] else 0,
             'Не сопоставлено имён / адресов выездов', 'занятость этих людей и центры не учитываются', mapping_url),
            (stats['orders_needs_fix'], 'Заказы на ручную правку', 'в расчёт не входят', orders_url)):
        if value:
            attention.append({'label': label, 'value': value, 'hint': hint, 'url': url})
    return render(request, 'schauto/index.html', {
        **stats,
        'title': 'Планирование выездных',
        'attention': attention,
        'pairs_text': f'{pairs_missing} из {pairs_total}',
        'venues_note': f"без фототочки в ERP: {stats['venues_no_store']}" if stats['venues_no_store'] else '',
        'retouchers_note': f"без оценки навыков: {stats['retouchers_no_skill']}" if stats['retouchers_no_skill'] else '',
    })


@login_required
@permission_required(perm='schauto.view_venue', raise_exception=True)
def venues(request):
    if not request.GET:
        return redirect('{}?is_active=1'.format(request.path))

    current_filter_params = request.GET.urlencode()
    v_filter = VenueFilter(request.GET, queryset=Venue.objects.select_related('store'))

    error = ''
    if request.method == 'POST':
        if not request.user.has_perm('schauto.add_venue'):
            raise PermissionDenied('У вас нет прав на добавление центров')
        form_p = VenueForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('{}?{}'.format(reverse('schauto:venues'), current_filter_params))
        error = 'Ошибка в заполнении формы'
        form = form_p
    else:
        form = VenueForm()

    paginator, page_obj, base_qs = _paginate(request, v_filter.qs)
    return render(request, 'schauto/venues.html', {
        'title': 'Центры', 'form': form, 'error': error, 'v_filter': v_filter,
        'page_obj': page_obj, 'paginator': paginator, 'base_qs': base_qs, 'count': paginator.count,
        'current_filter_params': current_filter_params,
    })


class VenueUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Venue
    form_class = VenueForm
    template_name = 'schauto/form_update.html'
    permission_required = 'schauto.change_venue'
    permission_denied_message = 'У вас нет прав на редактирование центров'

    def get_success_url(self):
        return reverse('schauto:venues') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.request.GET.urlencode()
        context.update({
            'title': 'Центры - редактирование', 'card_title': 'Изменение данных центра',
            'cancel_url': reverse('schauto:venues') + '?' + qs,
            'delete_url': reverse('schauto:venue_delete', args=[self.object.pk]) + '?' + qs,
        })
        return context


class VenueDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Venue
    template_name = 'schauto/confirm_delete.html'
    permission_required = 'schauto.delete_venue'
    permission_denied_message = 'У вас нет прав на удаление центров'

    def get_success_url(self):
        return reverse('schauto:venues') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        routes_count = Route.objects.filter(from_venue=self.object).count() + \
            Route.objects.filter(to_venue=self.object).count()
        context.update({
            'title': 'Центры - удаление', 'card_title': 'Удаление центра',
            'question': f'Подтверждаете удаление центра «{self.object}»? '
                        f'Вместе с ним будут удалены его маршруты: {routes_count}.',
            'cancel_url': reverse('schauto:venue_update', args=[self.object.pk]) + '?' + self.request.GET.urlencode(),
        })
        return context


@login_required
@permission_required(perm='schauto.view_route', raise_exception=True)
def routes(request):
    current_filter_params = request.GET.urlencode()
    r_filter = RouteFilter(request.GET, queryset=Route.objects.select_related('from_venue', 'to_venue'))

    error = ''
    if request.method == 'POST':
        if not request.user.has_perm('schauto.add_route'):
            raise PermissionDenied('У вас нет прав на добавление маршрутов')
        form_p = RouteCreateForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('{}?{}'.format(reverse('schauto:routes'), current_filter_params))
        error = 'Ошибка в заполнении формы'
        form = form_p
    else:
        form = RouteCreateForm()

    paginator, page_obj, base_qs = _paginate(request, r_filter.qs)
    return render(request, 'schauto/routes.html', {
        'title': 'Маршруты', 'form': form, 'error': error, 'r_filter': r_filter, 'import_form': RoutesImportForm(),
        'page_obj': page_obj, 'paginator': paginator, 'base_qs': base_qs, 'count': paginator.count,
        'current_filter_params': current_filter_params,
    })


class RouteUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Route
    form_class = RouteForm
    template_name = 'schauto/form_update.html'
    permission_required = 'schauto.change_route'
    permission_denied_message = 'У вас нет прав на редактирование маршрутов'

    def get_success_url(self):
        return reverse('schauto:routes') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.request.GET.urlencode()
        context.update({
            'title': 'Маршруты - редактирование', 'card_title': 'Изменение маршрута',
            'cancel_url': reverse('schauto:routes') + '?' + qs,
            'delete_url': reverse('schauto:route_delete', args=[self.object.pk]) + '?' + qs,
        })
        return context


class RouteDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Route
    template_name = 'schauto/confirm_delete.html'
    permission_required = 'schauto.delete_route'
    permission_denied_message = 'У вас нет прав на удаление маршрутов'

    def get_success_url(self):
        return reverse('schauto:routes') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': 'Маршруты - удаление', 'card_title': 'Удаление маршрута',
            'question': f'Подтверждаете удаление маршрута «{self.object}»?',
            'cancel_url': reverse('schauto:route_update', args=[self.object.pk]) + '?' + self.request.GET.urlencode(),
        })
        return context


@login_required
@permission_required(perm='schauto.view_route', raise_exception=True)
def routes_export(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="routes_{timezone.localdate():%Y%m%d}.csv"'
    response.write('﻿' + export_routes_csv())  # BOM, чтобы Excel открыл в UTF-8
    return response


@login_required
@permission_required(perm='schauto.add_route', raise_exception=True)
@require_http_methods(['POST'])
def routes_import(request):
    form = RoutesImportForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Выберите CSV-файл для загрузки')
        return redirect('schauto:routes')
    try:
        res = import_routes_csv(form.cleaned_data['file'].read(), form.cleaned_data['mirror'])
    except RoutesImportError as e:
        shown = e.errors[:MAX_ERRORS_SHOWN]
        more = f' (и ещё {len(e.errors) - len(shown)})' if len(e.errors) > len(shown) else ''
        messages.error(request, 'Файл не загружен, ошибки: ' + '; '.join(shown) + more)
        ImplEvents.objects.create(
            event_type='Schauto_Routes_Import', status='Бизнес ошибка', solved='Нет',
            event_message=f'Загрузка маршрутов из CSV отклонена. Ошибок: {len(e.errors)}. ' + '; '.join(shown))
        return redirect('schauto:routes')
    msg = (f'Создано маршрутов: {res["created"]}, обновлено: {res["updated"]}, '
           f'обратных создано: {res["mirrored"]}, пропущено пустых: {res["skipped"]}')
    messages.success(request, msg)
    ImplEvents.objects.create(event_type='Schauto_Routes_Import', status='Успешно', solved='Да',
                              event_message='Загрузка маршрутов из CSV. ' + msg)
    return redirect('schauto:routes')


# --- заказы из Google-таблиц ---------------------------------------------------------------------------------------

@login_required
@permission_required(perm='schauto.view_photoorder', raise_exception=True)
def orders(request):
    if not request.GET:
        return redirect('{}?date_from={}'.format(request.path, dt_format(timezone.localdate())))

    current_filter_params = request.GET.urlencode()
    queryset = PhotoOrder.objects.select_related('venue', 'photographer', 'retoucher').prefetch_related('photographers')
    if not request.GET.get('status'):
        queryset = queryset.exclude(status=PhotoOrder.STATUS_GONE)
    o_filter = PhotoOrderFilter(request.GET, queryset=queryset)

    paginator, page_obj, base_qs = _paginate(request, o_filter.qs)
    last_seen = PhotoOrder.objects.order_by('-last_seen_at').values_list('last_seen_at', flat=True).first()
    return render(request, 'schauto/orders.html', {
        'title': 'Заказы выездных', 'o_filter': o_filter, 'import_form': OrdersImportForm(),
        'page_obj': page_obj, 'paginator': paginator, 'base_qs': base_qs, 'count': paginator.count,
        'current_filter_params': current_filter_params, 'last_import': last_seen,
        'brands_configured': [b for b in BRANDS if settings.SCHAUTO_SHEET_IDS.get(b)],
    })


@login_required
@permission_required(perm='schauto.import_orders', raise_exception=True)
@require_http_methods(['POST'])
def orders_import(request):
    form = OrdersImportForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Проверьте параметры загрузки: ' + '; '.join(
            e for errs in form.errors.values() for e in errs))
        return redirect('schauto:orders')
    brands = (form.cleaned_data['brand'],) if form.cleaned_data['brand'] else BRANDS
    report = run_import(brands, form.cleaned_data['date_from'], form.cleaned_data['date_to'])

    (messages.warning if (report.errors or report.failed_tabs) else messages.success)(request, report.summary())
    unmatched_names, unmatched_places = _unmatched()
    if unmatched_names or unmatched_places:
        messages.info(request, f'Не сопоставлено имён: {len(unmatched_names)}, адресов выездов: {len(unmatched_places)} - '
                               f'откройте «Сопоставления».')
    no_time = sum(tab.no_time for tab in report.tabs)
    if no_time:
        messages.info(request, f'Заказов без времени в таблицах (пропущены, пока время не заполнено): {no_time}')
    return redirect('{}?date_from={}'.format(reverse('schauto:orders'), dt_format(report.date_from)))


# --- сопоставление имён и адресов ----------------------------------------------------------------------------------

def _unmatched():
    """Имена и адреса из таблиц, которым не нашлось соответствия: ({norm: (пример, число заказов)}, то же для адресов).
    В ячейке «Фотограф» бывает несколько людей («Роман + Лиза Гужвенко») - считаем и сопоставляем каждого отдельно."""
    live = PhotoOrder.objects.exclude(status=PhotoOrder.STATUS_GONE)
    names: dict[str, list] = {}

    def add(name: str):
        entry = names.setdefault(norm_person(name), [name, 0])
        entry[1] += 1

    resolver = Resolver()
    for raw in live.filter(photographer__isnull=True).exclude(photographer_raw='').values_list('photographer_raw', flat=True):
        for name in raw.split(PEOPLE_SEPARATOR):
            if name and resolver.person(name)[0] == PERSON_UNMATCHED:
                add(name)
    for raw in live.filter(retoucher__isnull=True).exclude(retoucher_raw='').values_list('retoucher_raw', flat=True):
        add(raw)
    places: dict[str, list] = {}
    for raw in live.filter(venue__isnull=True).exclude(place_raw='').values_list('place_raw', flat=True):
        entry = places.setdefault(norm_place(raw), [raw, 0])
        entry[1] += 1
    return names, places


@login_required
@permission_required(perm='schauto.import_orders', raise_exception=True)
def mapping(request):
    names, places = _unmatched()
    names = sorted(((key, raw, cnt) for key, (raw, cnt) in names.items()), key=lambda x: -x[2])
    places = sorted(((key, raw, cnt) for key, (raw, cnt) in places.items()), key=lambda x: -x[2])
    return render(request, 'schauto/mapping.html', {
        'title': 'Сопоставления',
        'names': names[:MAPPING_ROWS_SHOWN], 'names_total': len(names),
        'places': places[:MAPPING_ROWS_SHOWN], 'places_total': len(places),
        'staff_list': Staff.objects.filter(dism_status='Работает').order_by('name', 'f_name'),
        'venues': Venue.objects.filter(is_active=True),
        'person_aliases': StaffAlias.objects.select_related('staff')[:MAPPING_ROWS_SHOWN],
        'person_aliases_total': StaffAlias.objects.count(),
        'place_aliases': VenueAlias.objects.select_related('venue')[:MAPPING_ROWS_SHOWN],
        'place_aliases_total': VenueAlias.objects.count(),
    })


@login_required
@permission_required(perm='schauto.import_orders', raise_exception=True)
@require_http_methods(['POST'])
def mapping_person(request):
    form = PersonAliasForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Имя не сохранено: ' + '; '.join(e for errs in form.errors.values() for e in errs))
        return redirect('schauto:mapping')
    staff = None if form.cleaned_data['ignore'] else form.cleaned_data['staff']
    alias, _ = StaffAlias.objects.update_or_create(alias=norm_person(form.cleaned_data['alias']),
                                                   defaults={'staff': staff})
    changed = apply_mappings()
    ImplEvents.objects.create(event_type='Schauto_Mapping', status='Успешно', solved='Да',
                              event_message=f'Сопоставление имени: {alias}. Обновлено заказов: {changed}')
    messages.success(request, f'Сохранено: {alias}. Обновлено заказов: {changed}')
    return redirect('schauto:mapping')


@login_required
@permission_required(perm='schauto.import_orders', raise_exception=True)
@require_http_methods(['POST'])
def mapping_place(request):
    form = PlaceAliasForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Адрес не сохранён: ' + '; '.join(e for errs in form.errors.values() for e in errs))
        return redirect('schauto:mapping')
    venue = form.cleaned_data['venue']
    if venue is None:
        name = form.cleaned_data['new_venue'].strip()
        if Venue.objects.filter(name__iexact=name).exists():
            messages.error(request, f'Центр «{name}» уже есть - выберите его в списке')
            return redirect('schauto:mapping')
        venue = Venue.objects.create(name=name, brand='OT')
    alias, _ = VenueAlias.objects.update_or_create(fragment=form.cleaned_data['fragment'], defaults={'venue': venue})
    changed = apply_mappings()
    ImplEvents.objects.create(event_type='Schauto_Mapping', status='Успешно', solved='Да',
                              event_message=f'Сопоставление адреса: {alias}. Обновлено заказов: {changed}')
    messages.success(request, f'Сохранено: {alias}. Обновлено заказов: {changed}')
    return redirect('schauto:mapping')


# --- распределение заказов -----------------------------------------------------------------------------------------

PLAN_DEFAULT_DAYS = 14  # период по умолчанию в форме расчёта


@login_required
@permission_required(perm='schauto.view_planrun', raise_exception=True)
def plan(request):
    """Расчёты распределения: форма нового расчёта и список прежних"""
    error = ''
    if request.method == 'POST':
        if not request.user.has_perm('schauto.run_planning'):
            raise PermissionDenied('У вас нет прав на расчёт распределения')
        form = PlanRunForm(request.POST)
        if form.is_valid():
            try:
                run = run_plan(request.user, form.cleaned_data['date_from'], form.cleaned_data['date_to'])
            except Exception as e:  # расчёт - бизнес-операция: любая неудача попадает в журнал, а не в 500
                ImplEvents.objects.create(event_type='Schauto_Plan', status='Системная ошибка', solved='Нет',
                                          event_message=f'Расчёт распределения не выполнен: {e!r}')
                messages.error(request, 'Расчёт не выполнен из-за ошибки, подробности в журнале «Ошибки в работе системы»')
            else:
                return redirect('schauto:plan_detail', pk=run.pk)
        else:
            error = '; '.join(e for errs in form.errors.values() for e in errs)
    else:
        today = timezone.localdate()
        form = PlanRunForm(initial={'date_from': dt_format(today),
                                    'date_to': dt_format(today + timedelta(days=PLAN_DEFAULT_DAYS - 1))})

    paginator, page_obj, base_qs = _paginate(request, PlanRun.objects.select_related('created_by'))
    return render(request, 'schauto/plan.html', {
        'title': 'Распределение выездных', 'form': form, 'error': error,
        'page_obj': page_obj, 'paginator': paginator, 'base_qs': base_qs, 'count': paginator.count,
    })


@login_required
@permission_required(perm='schauto.view_planrun', raise_exception=True)
def plan_detail(request, pk):
    run = get_object_or_404(PlanRun, pk=pk)
    all_items = list(run.assignments.select_related('order__venue', 'staff', 'auto_staff'))
    can_edit = run.editable and request.user.has_perm('schauto.run_planning')

    # проверка по текущим данным (график выходов, заказы): показывается у каждой строки, пока расчёт можно править
    check = validate_plan(run) if run.editable else None
    for a in all_items:
        a.errors = check.row_errors.get(a.pk, []) if check else []
        a.warns = check.row_warnings.get(a.pk, []) if check else []
        a.softs = check.row_soft.get(a.pk, []) if check else []                  # можно подтвердить вручную, ещё не подтверждено
        a.confirmed_problems = check.row_confirmed.get(a.pk, []) if check else []   # подтверждено вручную

    assigned = [a for a in all_items if a.staff_id is not None]
    unassigned = [a for a in all_items if a.staff_id is None]

    load: dict[int, dict] = {}
    for a in assigned:
        row = load.setdefault(a.staff_id, {'staff': a.staff, 'orders': set(), 'parts': 0, 'minutes': 0})
        row['orders'].add(a.order_id)
        row['parts'] += 1
        row['minutes'] += a.end_min - a.start_min
    load_rows = sorted(({**r, 'orders': len(r['orders']), 'hours': round(r['minutes'] / 60, 1)} for r in load.values()),
                       key=lambda r: (-r['orders'], str(r['staff'])))

    staff_id = request.GET.get('staff', '')
    shown = [a for a in assigned if str(a.staff_id) == staff_id] if staff_id else assigned
    params = request.GET.copy()
    params.pop('page', None)
    paginator = Paginator(shown, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'schauto/plan_detail.html', {
        'title': 'Распределение выездных', 'run': run, 'unassigned': unassigned, 'load_rows': load_rows,
        'page_obj': page_obj, 'paginator': paginator, 'base_qs': params.urlencode(), 'count': len(shown),
        'staff_filter': staff_id, 'staff_options': [(r['staff'].pk, str(r['staff'])) for r in load_rows],
        'fixed_rows': [{**f, 'date': date.fromisoformat(f['date'])} for f in run.fixed],
        'check': check, 'can_edit': can_edit, 'staff_choices': list(allowed_staff()) if can_edit else [],
        'can_rollback': request.user.has_perm('schauto.run_planning') and run.rollbackable,
        'can_delete': request.user.has_perm('schauto.run_planning') and run.deletable,
        'problem_rows': sum(1 for a in all_items if a.errors or a.softs),
        'shortfalls': sorted(p.shortfall for p in check.unconfirmed.values()) if check else [],
    })


def _report_apply(request, result):
    """Итог проверки/применения - уведомлениями пользователю"""
    if result.ok:
        messages.success(request, result.message)
    else:
        messages.error(request, result.message)
    for text in result.errors[:5]:
        messages.error(request, text)
    if result.validation and result.stage == 'sheets_check':
        pks = [pk for pk, errs in result.validation.row_errors.items() if any(e.startswith('Google-таблица') for e in errs)]
        for a in Assignment.objects.filter(pk__in=pks).select_related('order__venue')[:8]:
            err = next(e for e in result.validation.row_errors[a.pk] if e.startswith('Google-таблица'))
            messages.error(request, f'{a.date:%d.%m.%Y} {a.time_display} {a.order.venue}: {err}')
    for text in result.notes[:5]:
        messages.warning(request, text)


@login_required
@permission_required(perm='schauto.run_planning', raise_exception=True)
@require_http_methods(['POST'])
def plan_action(request, pk):
    """Сохранить правки исполнителей / проверить / применить распределение"""
    run = get_object_or_404(PlanRun, pk=pk)
    back = reverse('schauto:plan_detail', args=[run.pk])
    query = {k: request.POST[k] for k in ('page', 'staff') if request.POST.get(k, '').isdigit()}
    if query:
        back += '?' + '&'.join(f'{k}={v}' for k, v in query.items())
    action = request.POST.get('action', 'save')
    if action == 'rollback':
        try:
            _report_apply(request, rollback_plan(run, request.user))
        except Exception as e:  # бизнес-операция: сбой попадает в журнал, а не в 500
            ImplEvents.objects.create(event_type='Schauto_Plan_Rollback', status='Системная ошибка', solved='Нет',
                                      event_message=f'Распределение №{run.pk}: откат не выполнен: {e!r}'[:900])
            messages.error(request, 'Откат не выполнен из-за ошибки, подробности в журнале «Ошибки в работе системы»')
        return redirect(back)
    if action == 'delete':
        try:
            messages.success(request, delete_plan(run, request.user))
        except PlanNotDeletable as e:
            messages.error(request, str(e))
            return redirect(back)
        except Exception as e:  # бизнес-операция: сбой попадает в журнал, а не в 500
            ImplEvents.objects.create(event_type='Schauto_Plan_Delete', status='Системная ошибка', solved='Нет',
                                      event_message=f'Распределение №{run.pk}: удаление не выполнено: {e!r}'[:900])
            messages.error(request, 'Удаление не выполнено из-за ошибки, подробности в журнале «Ошибки в работе системы»')
            return redirect(back)
        return redirect('schauto:plan')
    if not run.editable:
        messages.error(request, 'Этот расчёт уже применён или применяется - править и применять его нельзя')
        return redirect(back)

    changes = {int(key[6:]): (int(value) if value.isdigit() else None)
               for key, value in request.POST.items() if key.startswith('staff_') and key[6:].isdigit()}
    shown, ticked = request.POST.getlist('shown'), request.POST.getlist('confirm')
    upto = int(request.POST['upto']) if action == 'confirm_upto' and request.POST.get('upto', '').isdigit() else None
    try:
        changed = save_edits(run, changes) if changes else 0
        if changed:
            messages.info(request, f'Изменено исполнителей: {changed}')
        done = ConfirmResult()
        if action == 'confirm_upto' and upto is None:
            messages.error(request, 'Укажите число минут для массового подтверждения')
        elif shown or ticked or upto is not None:      # после правок исполнителей: подписи проблем зависят от них
            done = save_confirmations(run, request.user, shown=shown, ticked=ticked, upto=upto)
            if done.confirmed:
                messages.info(request, f'Подтверждено вручную проблем: {done.confirmed}')
            if done.revoked:
                messages.info(request, f'Снято подтверждений: {done.revoked}')
            if action == 'confirm_upto' and not done.confirmed:
                messages.info(request, f'Нет неподтверждённых проблем, где не хватает не больше {upto} мин')
        if action in ('check', 'apply'):
            _report_apply(request, apply_plan(run, request.user, only_check=(action == 'check')))
        elif changed or done.confirmed or done.revoked:
            messages.success(request, 'Изменения сохранены. Перед применением нажмите «Проверить» или «Применить распределение».')
        elif not (action == 'confirm_upto'):
            messages.info(request, 'Изменений нет')
    except Exception as e:  # бизнес-операция: сбой попадает в журнал, а не в 500
        ImplEvents.objects.create(event_type='Schauto_Plan_Apply', status='Системная ошибка', solved='Нет',
                                  event_message=f'Распределение №{run.pk}: операция «{action}» не выполнена: {e!r}'[:900])
        messages.error(request, 'Операция не выполнена из-за ошибки, подробности в журнале «Ошибки в работе системы»')
    return redirect(back)
