import decimal
import math
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django import forms
from django.urls import reverse_lazy
from django.db.transaction import atomic
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.viewsets import ModelViewSet
from django.views.generic import UpdateView, DeleteView, TemplateView, CreateView
from django.core.paginator import Paginator

from tph_system.models import *
from tph_system.serializers import StaffSerializer
from tph_system.forms import StoreForm, StaffForm, ConsStoreForm, TechForm, ScheduleForm, SalesForm, CashWithdrawnForm, \
    RefsAndTipsForm, SettingsForm, SalaryForm, PositionSelectFormSet, TimeSelectForm, SalaryWeeklyForm, ImplEventsForm
from .filters import *
from .funcs import *

# Для календаря
from schedule.views import CalendarByPeriodsView
from schedule.periods import Month


class StaffViewSet(LoginRequiredMixin, ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer


class StaffUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Staff
    form_class = StaffForm
    template_name = 'tph_system/staff/staff_update.html'
    success_url = '/staff/'
    extra_context = {
        'title': 'Сотрудники - редактирование'
    }
    permission_required = 'tph_system.change_staff'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с сотрудниками'


class StaffDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Staff
    success_url = '/staff/'
    template_name = 'tph_system/staff/staff_delete.html'
    extra_context = {
        'title': 'Сотрудники - удаление'
    }
    permission_required = 'tph_system.delete_staff'
    permission_denied_message = 'У вас нет прав на удаление сотрудников'


class StoreUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Store
    form_class = StoreForm
    template_name = 'tph_system/stores/store_update.html'
    success_url = '/store/'
    extra_context = {
        'title': 'Точки - редактирование'
    }
    permission_required = 'tph_system.change_store'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с точками'


class StoreDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Store
    success_url = '/store/'
    template_name = 'tph_system/stores/store_delete.html'
    extra_context = {
        'title': 'Точки - удаление'
    }
    permission_required = 'tph_system.delete_store'
    permission_denied_message = 'У вас нет прав на удаление точек'


class ConStoreUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = ConsumablesStore
    form_class = ConsStoreForm
    template_name = 'tph_system/consumables_store/conStore_update.html'
    success_url = '/consumables/'
    extra_context = {
        'title': 'Расходники - редактирование'
    }
    permission_required = 'tph_system.change_consumablesstore'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с расходниками'


class ConStoreDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = ConsumablesStore
    success_url = '/consumables/'
    template_name = 'tph_system/consumables_store/conStore_delete.html'
    extra_context = {
        'title': 'Расходники - удаление'
    }
    permission_required = 'tph_system.delete_consumablesstore'
    permission_denied_message = 'У вас нет прав на удаление расходников'


class TechUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Tech
    form_class = TechForm
    template_name = 'tph_system/tech/tech_update.html'
    success_url = '/tech/'
    extra_context = {
        'title': 'Техника - редактирование',
        'card_title': 'Изменение техники',
        'url_cancel': 'tech',
        'url_delete': 'tech_delete'
    }
    permission_required = 'tph_system.change_tech'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с фототехникой'


class TechDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Tech
    success_url = '/tech/'
    template_name = 'tph_system/tech/tech_delete.html'
    extra_context = {
        'title': 'Техника - удаление',
        'card_title': 'Удаление техники',
        'url_cancel': 'tech_update'
    }
    permission_required = 'tph_system.delete_tech'
    permission_denied_message = 'У вас нет прав на удаление техники'


class SalesUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Sales
    form_class = SalesForm
    template_name = 'tph_system/sales/sales_update.html'
    success_url = '/sales/'
    extra_context = {
        'title': 'Продажи - редактирование',
        'card_title': 'Изменение продажи',
        'url_cancel': 'sales',
        'url_delete': 'sales_delete'
    }
    permission_required = 'tph_system.change_sales'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с продажами'

    @atomic
    def form_valid(self, form):
        # Фиксируем текущее количество фото
        photo_c_old = self.get_object().photo_count

        # Сохраняем экземпляр продажи
        self.object = form.save()

        # Данные из формы
        store = form.cleaned_data['store']
        sale_type = form.cleaned_data['sale_type']
        photo_count = form.cleaned_data['photo_count']

        try:
            # Корректировка кол-ва расходников consumable.count в зависимости от разницы photo_count - photo_c_old
            if sale_type == 'Печать 15x20':
                consumable = ConsumablesStore.objects.get(cons_short='Печать A4', store=store)
                prev_count = consumable.count
                consumable.count += int(decimal.Decimal((photo_c_old - photo_count) / 2).quantize(  # округление
                    decimal.Decimal('1'),
                    rounding=decimal.ROUND_HALF_UP
                ))
            else:
                consumable = ConsumablesStore.objects.get(cons_short=sale_type, store=store)
                prev_count = consumable.count
                consumable.count += photo_c_old - photo_count
            consumable.save()
            # Логируем изменение расходников
            ImplEvents.objects.create(
                event_type=f"ConsStore_Upd_{sale_type}",
                event_message=f"Изменение количества расходников на {store.name} из-за корректировки продажи. "
                              f"{consumable.consumable} было {prev_count} => стало {consumable.count}",
                status='Успешно'
            )
        except ConsumablesStore.DoesNotExist:
            ImplEvents.objects.create(
                event_type=f"ConsStore_Upd_Failed",
                event_message=f"Ошибка при изменении количества расходников на {store.name}. Расходник с "
                              f"функциональным именем {sale_type} не найден. После корректировки имени надо изменить "
                              f"количество этого расходника на точке. Хотели изменить {sale_type} с {photo_c_old} "
                              f"(Кол-во фото в продаже было) на {photo_count} (Кол-во фото в продаже стало).",
                status='Системная ошибка',
                solved='Нет'
            )

        return super().form_valid(form)


class SalesDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Sales
    success_url = '/sales/'
    template_name = 'tph_system/sales/sales_delete.html'
    extra_context = {
        'title': 'Продажи - удаление',
        'card_title': 'Удаление продажи',
        'url_cancel': 'sales'
    }
    permission_required = 'tph_system.delete_sales'
    permission_denied_message = 'У вас нет прав на удаление продаж'

    def form_valid(self, form):
        # Данные из объекта БД
        store = self.get_object().store
        sale_type = self.get_object().sale_type
        photo_count = self.get_object().photo_count

        try:
            # Корректировка кол-ва расходников при удалении продажи
            if sale_type == 'Печать 15x20':
                consumable = ConsumablesStore.objects.get(cons_short='Печать A4', store=store)
                prev_count = consumable.count
                consumable.count += math.ceil(photo_count / 2)
            else:
                consumable = ConsumablesStore.objects.get(cons_short=sale_type, store=store)
                prev_count = consumable.count
                consumable.count += photo_count
            consumable.save()
            # Логируем изменение расходников
            ImplEvents.objects.create(
                event_type=f"ConsStore_Del_{sale_type}",
                event_message=f"Изменение количества расходников на {store.name} из-за удаления продажи. "
                              f"{consumable.consumable} было {prev_count} => стало {consumable.count}",
                status='Успешно'
            )
        except ConsumablesStore.DoesNotExist:
            ImplEvents.objects.create(
                event_type=f"ConsStore_Del_Failed",
                event_message=f"Ошибка при изменении количества расходников на {store.name}. Расходник с "
                              f"функциональным именем {sale_type} не найден. После корректировки имени надо изменить "
                              f"количество этого расходника на точке. Была удалена продажа с расходником {sale_type} "
                              f"в количестве {photo_count}",
                status='Системная ошибка',
                solved='Нет'
            )

        success_url = self.get_success_url()
        self.object.delete()
        return HttpResponseRedirect(success_url)


class SalesCreateView(PermissionRequiredMixin, LoginRequiredMixin, CreateView):
    model = Sales
    form_class = SalesForm
    template_name = 'tph_system/sales/sale_add.html'
    success_url = '/sales/'
    extra_context = {
        'title': 'Новая продажа',
        'card_title': 'Добавление новой продажи',
        'url_cancel': 'sales'
    }
    permission_required = 'tph_system.add_sales'
    permission_denied_message = 'У вас нет прав на добавление новой продажи'

    def get_initial(self):
        initial = super().get_initial()
        auth_user = self.request.user

        try:
            store_staff_working_obj = Store.objects.get(
                name=Schedule.objects.get(date=datetime.now(),
                                          staff_id=Staff.objects.get(st_username=auth_user)).store)
        except ObjectDoesNotExist:
            store_staff_working_obj = None

        admin = ''
        photog = ''
        today_sch = Schedule.objects.filter(date=datetime.now(), store=store_staff_working_obj)
        for sch in today_sch:
            if sch.position == 'Администратор':
                admin = sch.staff
            elif sch.position == 'Фотограф':
                photog = sch.staff
            elif sch.position == 'Универсальный фотограф':
                admin = Staff.objects.get(st_username=auth_user)
                photog = Staff.objects.get(st_username=auth_user)

        initial.update({
            'store': store_staff_working_obj,
            'date': datetime.now(),
            'staff': admin,
            'photographer': photog
        })
        return initial

    @atomic
    def form_valid(self, form):
        # Сохраняем экземпляр продажи
        self.object = form.save()

        # Данные из формы
        store = form.cleaned_data['store']
        sale_type = form.cleaned_data['sale_type']
        photo_count = form.cleaned_data['photo_count']

        try:
            if sale_type == 'Печать 15x20':
                consumable = ConsumablesStore.objects.get(cons_short='Печать A4', store=store)
                prev_count = consumable.count
                consumable.count -= math.ceil(photo_count / 2)
            else:
                consumable = ConsumablesStore.objects.get(cons_short=sale_type, store=store)
                prev_count = consumable.count
                consumable.count -= photo_count
            consumable.save()
            # Логируем изменение расходников
            ImplEvents.objects.create(
                event_type=f"ConsStore_Crt_{sale_type}",
                event_message=f"Изменение количества расходников на {store.name} из-за создания новой продажи. "
                              f"{consumable.consumable} было {prev_count} => стало {consumable.count}",
                status='Успешно'
            )
        except ConsumablesStore.DoesNotExist:
            ImplEvents.objects.create(
                event_type=f"ConsStore_Crt_Failed",
                event_message=f"Ошибка при изменении количества расходников на {store.name}. Расходник с "
                              f"функциональным именем {sale_type} не найден. После корректировки имени надо изменить "
                              f"количество этого расходника на точке. Было продано {sale_type} в количестве "
                              f"{photo_count}",
                status='Системная ошибка',
                solved='Нет'
            )

        return super().form_valid(form)


class CashWithdrawnUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = CashWithdrawn
    form_class = CashWithdrawnForm
    template_name = 'tph_system/cash_withdrawn/c_w_update.html'
    success_url = '/cash_withdrawn/'
    extra_context = {
        'title': 'Зарплата наличными - редактирование',
        'card_title': 'Редактирование данных',
        'url_cancel': 'cash_withdrawn',
        'url_delete': 'c_w_delete'
    }
    permission_required = 'tph_system.change_cashwithdrawn'
    permission_denied_message = 'У вас нет прав на редактирование истории выдачи наличных'


class CashWithdrawnDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = CashWithdrawn
    success_url = '/cash_withdrawn/'
    template_name = 'tph_system/cash_withdrawn/c_w_delete.html'
    extra_context = {
        'title': 'Зарплата наличными - удаление',
        'card_title': 'Удаление данных',
        'url_cancel': 'c_w_update'
    }
    permission_required = 'tph_system.delete_cashwithdrawn'
    permission_denied_message = 'У вас нет прав на удаление истории выдачи наличных'


class RefsAndTipsUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = RefsAndTips
    form_class = RefsAndTipsForm
    template_name = 'tph_system/main_page/tips_update.html'
    success_url = '/main_page/'
    extra_context = {
        'title': 'Примеры - редактирование',
        'card_title': 'Редактирование примеров'
    }
    permission_required = 'tph_system.change_refsandtips'
    permission_denied_message = 'У вас нет прав на редактирование примеров'


class RefsAndTipsDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = RefsAndTips
    success_url = '/main_page/'
    template_name = 'tph_system/main_page/tips_delete.html'
    extra_context = {
        'title': 'Примеры - удаление',
        'card_title': 'Удаление примеров'
    }
    permission_required = 'tph_system.delete_refsandtips'
    permission_denied_message = 'У вас нет прав на удаление примеров'


class SettingsUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Settings
    form_class = SettingsForm
    template_name = 'tph_system/settings/set_update.html'
    success_url = '/settings/'
    extra_context = {
        'title': 'Настройки - редактирование',
        'card_title': 'Редактирование параметра'
    }
    permission_required = 'tph_system.change_settings'
    permission_denied_message = 'У вас нет прав на редактирование параметров'


class SettingsDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Settings
    success_url = '/settings/'
    template_name = 'tph_system/settings/set_delete.html'
    extra_context = {
        'title': 'Настройки - удаление',
        'card_title': 'Удаление параметра'
    }
    permission_required = 'tph_system.delete_settings'
    permission_denied_message = 'У вас нет прав на удаление параметра'


class SalaryUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Salary
    form_class = SalaryForm
    template_name = 'tph_system/salary/salary_update.html'
    success_url = '/salary/'
    extra_context = {
        'title': 'Зарплаты - редактирование',
        'card_title': 'Редактирование записи с зарплатой'
    }
    permission_required = 'tph_system.change_salary'
    permission_denied_message = 'У вас нет прав на редактирование зарплат'


class SalaryDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Salary
    success_url = '/salary/'
    template_name = 'tph_system/salary/salary_delete.html'
    extra_context = {
        'title': 'Зарплаты - удаление',
        'card_title': 'Удаление записи с зарплатой'
    }
    permission_required = 'tph_system.delete_salary'
    permission_denied_message = 'У вас нет прав на удаление зарплат'


class SalaryWeeklyUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = SalaryWeekly
    form_class = SalaryWeeklyForm
    template_name = 'tph_system/salary_weekly/salary_w_upd.html'
    success_url = '/salary_weekly/'
    extra_context = {
        'title': 'Зарплаты по неделям - редактирование',
        'card_title': 'Редактирование записи с зарплатой по неделям'
    }
    permission_required = 'tph_system.change_salaryweekly'
    permission_denied_message = 'У вас нет прав на редактирование зарплат по неделям'


class SalaryWeeklyDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = SalaryWeekly
    success_url = '/salary_weekly/'
    template_name = 'tph_system/salary_weekly/salary_w_del.html'
    extra_context = {
        'title': 'Зарплаты по неделям - удаление',
        'card_title': 'Удаление записи с зарплатой по неделям'
    }
    permission_required = 'tph_system.delete_salaryweekly'
    permission_denied_message = 'У вас нет прав на удаление зарплат по неделям'


class ImplEventsUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = ImplEvents
    form_class = ImplEventsForm
    template_name = 'tph_system/salary/sal_events_edit.html'
    success_url = '/salary/events/'
    extra_context = {
        'title': 'Ошибки в подсчете зарплат - редактирование',
        'card_title': 'Редактирование событий'
    }
    permission_required = 'tph_system.change_implevents'
    permission_denied_message = 'У вас нет прав на редактирование событий'


# ---------------------------Классы календаря----------------------------------
class CalendarView(LoginRequiredMixin, CalendarByPeriodsView):
    template_name = 'tph_system/calendar/calendar.html'
    period = Month

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['events'] = CalendarEvent.objects.all()
        context['event_types'] = CalendarEvent.EVENT_TYPES
        context['event_colors'] = CalendarEvent.EVENT_COLORS
        return context


class EventCreateView(LoginRequiredMixin, CreateView):
    model = CalendarEvent
    template_name = 'tph_system/calendar/event_form.html'
    success_url = reverse_lazy('calendar')

    def get_form_class(self):
        from django import forms

        class EventForm(forms.ModelForm):
            class Meta:
                model = CalendarEvent
                fields = ['event_type', 'title', 'start_date', 'end_date', 'description']

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields['start_date'].widget = forms.DateInput(attrs={'type': 'date'})
                self.fields['end_date'].widget = forms.DateInput(attrs={'type': 'date'})

        return EventForm

    def form_valid(self, form):
        if form.instance.event_type == 'vacation':
            form.instance.employee = self.request.user
        return super().form_valid(form)


class VacationCreateView(EventCreateView):
    template_name = 'tph_system/calendar/vacation_form.html'

    def get_form_class(self):
        form_class = super().get_form_class()
        form_class._meta.fields = ['start_date', 'end_date', 'description']
        return form_class

    def form_valid(self, form):
        form.instance.event_type = 'vacation'
        return super().form_valid(form)
# --------------------------------Конец--------------------------------


@login_required
def index(request):
    return redirect('main_page', permanent=True)


@login_required
@permission_required(perm='tph_system.view_store', raise_exception=True)
def store(request):
    stores = Store.objects.all()

    error = ''
    if request.method == 'POST':
        form_p = StoreForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('store')
        else:
            error = 'Ошибка в заполнении формы'

    form = StoreForm()

    return render(request, 'tph_system/stores/store.html', {
        'title': 'Точки',
        'stores': stores,
        'form': form,
        'error': error
    })


@login_required
@permission_required(perm='tph_system.view_staff', raise_exception=True)
def staff(request):
    staffs = Staff.objects.all()

    s_filter = StaffFilter(request.GET, queryset=staffs)
    staffs = s_filter.qs

    error = ''
    if request.method == 'POST':
        form_p = StaffForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('staff')
        else:
            error = 'Ошибка в заполнении формы'

    form = StaffForm()

    # Пагинатор
    paginator = Paginator(staffs, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/staff/staff.html', {
        'title': 'Сотрудники',
        'form': form,
        'error': error,
        's_filter': s_filter,
        'page_obj': page_obj,
        'paginator': paginator
    })


@login_required
@permission_required(perm='tph_system.view_consumablesstore', raise_exception=True)
def cons_store(request):
    stores = Store.objects.all()
    auth_user = User.objects.get(id=request.user.id)

    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(date=datetime.now(),
                                      staff_id=Staff.objects.get(st_username=auth_user)).store)
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    # Сотрудник видит расходники той точки, на которой работает по графику, если нет права на просмотр всех расходников
    if auth_user.has_perm('tph_system.consumables_view_all_stores'):
        con_store = ConsumablesStore.objects.all()
    else:
        con_store = ConsumablesStore.objects.filter(store=store_staff_working_obj)

    #Фильтр
    cs_filter = ConsumablesStoreFilter(request.GET, queryset=con_store)
    con_store = cs_filter.qs

    if request.method == 'POST':
        form = ConsStoreForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('cons_store')
    else:
        form = ConsStoreForm(initial={'store': store_staff_working_obj})

    # Пагинатор
    paginator = Paginator(con_store, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/consumables_store/сonsumablesStore.html', {
        'title': 'Расходники',
        'form': form,
        'stores': stores,
        'cs_filter': cs_filter,
        'page_obj': page_obj,
        'paginator': paginator
    })


@login_required
@permission_required(perm='tph_system.view_tech', raise_exception=True)
def tech_mtd(request):
    auth_user = User.objects.get(id=request.user.id)

    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(date=datetime.now(),
                                      staff_id=Staff.objects.get(st_username=auth_user)).store)
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    # Сотрудник видит расходники той точки, на которой работает по графику, если нет права на просмотр всех расходников
    if auth_user.has_perm('tph_system.tech_view_all_stores'):
        tech = Tech.objects.all()
    else:
        tech = Tech.objects.filter(store=store_staff_working_obj)

    # Фильтр
    t_filter = TechFilter(request.GET, queryset=tech)
    tech = t_filter.qs

    if request.method == 'POST':
        form = TechForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('tech')
    else:
        form = TechForm(initial={'store': store_staff_working_obj})

    # Пагинатор
    paginator = Paginator(tech, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/tech/tech.html', {
        'title': 'Техника',
        'form': form,
        't_filter': t_filter,
        'page_obj': page_obj,
        'paginator': paginator
    })


@login_required
@permission_required(perm='tph_system.view_schedule', raise_exception=True)
def schedule_mtd(request):
    # Получаем дату начала недели из GET-параметра или используем текущую дату
    start_date = request.GET.get('start_date')
    if start_date:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    else:
        # Если дата не указана, берем понедельник текущей недели
        start_date = datetime.now().date() - timedelta(days=datetime.now().weekday())

    # Вычисляем конец недели (воскресенье)
    end_date = start_date + timedelta(days=6)

    staffs = Staff.objects.all()
    stores = Store.objects.all()
    schedules = Schedule.objects.filter(date__range=[start_date, end_date])

    # Если запрос AJAX, возвращаем данные в формате JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        schedule_data = []
        for stf in staffs:
            staff_schedules = schedules.filter(staff=stf)
            week_data = []
            for i in range(7):
                date = start_date + timedelta(days=i)
                schedule = staff_schedules.filter(date=date).first()
                week_data.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'store': schedule.store.short_name if schedule else ''
                })
            schedule_data.append({
                'staff_id': stf.id,
                'staff_f_name': stf.f_name,
                'staff_name': stf.name,
                'schedule': week_data
            })
        return JsonResponse({'schedule_data': schedule_data, 'start_date': start_date.strftime('%Y-%m-%d')})

    return render(request, 'tph_system/schedule/schedule.html', {
        'title': 'График сотрудников',
        'staffs': staffs,
        'schedule': schedules,
        'stores': stores,
        'start_date': start_date
    })


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def update_schedule(request):
    # Получаем данные из POST-запроса
    staff_id = request.POST.get('staff_id')
    date = request.POST.get('date')
    sel_store = request.POST.get('store')

    try:
        # Получаем сотрудника по ID
        employee = get_object_or_404(Staff, id=staff_id)

        if sel_store == '' or sel_store is None:
            # Если выбрано пустое значение, удаляем запись из расписания
            Schedule.objects.filter(staff=employee, date=date).delete()
            action = 'Удалено'
        else:
            # Обновляем или создаем запись в расписании
            f_store = get_object_or_404(Store, short_name=sel_store)

            schedule, created = Schedule.objects.update_or_create(
                staff=employee,
                date=date,
                defaults={'store': f_store}
            )
            action = 'Добавлено' if created else 'Обновлено'

        # Возвращаем успешный ответ с информацией о выполненном действии
        return JsonResponse({'status': 'success', 'action': action})

    except Exception as e:
        # Логируем ошибку
        ImplEvents.objects.create(
            event_type=f"Schedule_Upd_Failed",
            event_message=f"Ошибка при обновлении графика с сотрудниками. Сообщение: {str(e)}",
            status='Системная ошибка',
            solved='Нет'
        )
        # Возвращаем сообщение об ошибке
        return JsonResponse({'status': 'error', 'message': str(e)})


@login_required
@permission_required(perm='tph_system.add_sales', raise_exception=True)
def m_position_select(request):
    auth_user = User.objects.get(id=request.user.id)
    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(date=datetime.now(),
                                      staff_id=Staff.objects.get(st_username=auth_user)).store)
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    today_sch = Schedule.objects.filter(date=datetime.now(), store=store_staff_working_obj)

    if request.method == 'POST':
        formset = PositionSelectFormSet(request.POST, queryset=today_sch)
        if formset.is_valid():
            formset.save()
            return redirect('sales')
    else:
        formset = PositionSelectFormSet(queryset=today_sch)

    return render(request, 'tph_system/sales/position_select.html', {
        'formset': formset,
        'store': store_staff_working_obj,
        'date': datetime.now().date()
    })


@login_required
@permission_required(perm='tph_system.view_sales', raise_exception=True)
def sales(request):
    auth_user = User.objects.get(id=request.user.id)

    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(date=datetime.now(),
                                      staff_id=Staff.objects.get(st_username=auth_user)).store)
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    #Сотрудник видит только сегодняшние продажи точки, на которой работает по графику, если нет права на просмотр всех продаж
    if auth_user.has_perm('tph_system.user_sales_view_all'):
        sales_all = Sales.objects.all()
    else:
        sales_all = Sales.objects.filter(store=store_staff_working_obj, date=datetime.now())

    flag = 0
    today_staff = Schedule.objects.filter(date=datetime.now(), staff_id=Staff.objects.get(st_username=auth_user))
    positions = [i.position for i in today_staff]
    if 'Роль не указана' in positions:
        flag = 1

    #Фильтр
    sale_filter = SalesFilter(request.GET, queryset=sales_all)
    sales_all = sale_filter.qs

    error = ''
    if request.method == 'POST':
        form_p = SalesForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('sales')
        else:
            error = 'Ошибка в заполнении формы'

    form = SalesForm(initial={
        'store': store_staff_working_obj,
        'date': datetime.now(),
        'staff': Staff.objects.get(st_username=auth_user)
    })

    # Пагинатор
    paginator = Paginator(sales_all, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/sales/sales.html', {
        'title': 'Продажи',
        'form': form,
        'error': error,
        'sale_filter': sale_filter,
        'flag': flag,
        'page_obj': page_obj,
        'paginator': paginator
    })


@login_required
@permission_required(perm='tph_system.view_main_page', raise_exception=True)
def main_page(request):
    sch = Schedule.objects.filter(date=datetime.now()).prefetch_related('staff', 'store').order_by('store')
    now_date = datetime.now().strftime('%d.%m.%Y')
    sales_today = Sales.objects.filter(date=datetime.now())
    con_store = ConsumablesStore.objects.filter(count__lt=30)
    sys_errors_count = ImplEvents.objects.filter(status='Системная ошибка', solved='Нет').count()
    err_events_count = ImplEvents.objects.filter(status='Бизнес ошибка', solved='Нет').count()

    dic = {}

    for st in Store.objects.all():
        sales_sum = sales_today.filter(store=st).aggregate(Sum('sum'))['sum__sum']
        if sales_sum is not None:
            dic[st.name] = sales_sum

    tips = RefsAndTips.objects.all()

    error = ''
    if request.method == 'POST':
        form_p = RefsAndTipsForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('main_page')
        else:
            error = 'Ошибка в заполнении формы'

    form = RefsAndTipsForm()

    return render(request, 'tph_system/main_page/main_page.html', {
        'title': 'Главная страница',
        'sch': sch,
        'now_date': now_date,
        'dic': dic,
        'con_store': con_store,
        'tips': tips,
        'error': error,
        'form': form,
        'sys_errors_count': sys_errors_count,
        'err_events_count': err_events_count
    })


@login_required
@permission_required(perm='tph_system.view_cashwithdrawn', raise_exception=True)
def cash_withdrawn(request):
    auth_user = User.objects.get(id=request.user.id)

    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(
                date=datetime.now(),
                staff_id=Staff.objects.get(st_username=auth_user)
            ).store
        )
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    # Сотрудник видит только свои списания на точке, на которой работает по графику,
    # если нет права на просмотр всех списаний зарплаты
    if auth_user.has_perm('tph_system.view_all_cashwithdrawn'):
        cash = CashWithdrawn.objects.all()
    else:
        cash = CashWithdrawn.objects.filter(
            store=store_staff_working_obj,
            staff_id=Staff.objects.get(st_username=auth_user)
        )

    # Фильтр
    c_filter = CashWithdrawnFilter(request.GET, queryset=cash)
    cash = c_filter.qs

    if request.method == 'POST':
        form = CashWithdrawnForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('cash_withdrawn')
    else:
        form = CashWithdrawnForm(initial={
            'store': store_staff_working_obj,
            'date': datetime.now(),
            'staff': Staff.objects.get(st_username=auth_user)
        })

    # Пагинатор
    paginator = Paginator(cash, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/cash_withdrawn/cash_withdrawn.html', {
        'title': 'Зарплата наличными',
        'form': form,
        'c_filter': c_filter,
        'page_obj': page_obj,
        'paginator': paginator
    })


@login_required
@permission_required(perm='tph_system.view_settings', raise_exception=True)
def settings(request):
    stng = Settings.objects.all()

    # Фильтр
    s_filter = SettingsFilter(request.GET, queryset=stng)
    stng = s_filter.qs

    error = ''
    if request.method == 'POST':
        form = SettingsForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('settings')
        else:
            error = 'Ошибка в заполнении формы'
    else:
        form = SettingsForm()

    # Пагинатор
    paginator = Paginator(stng, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/settings/settings.html', {
        'title': 'Настройки',
        'form': form,
        'error': error,
        's_filter': s_filter,
        'page_obj': page_obj,
        'paginator': paginator
    })


@login_required
@permission_required(perm='tph_system.view_salaryweekly', raise_exception=True)
def salary_weekly(request):
    slr = SalaryWeekly.objects.all()
    err_events_count = ImplEvents.objects.filter(status='Бизнес ошибка', solved='Нет').count()

    # Фильтр
    sw_filter = SalaryWeeklyFilter(request.GET, queryset=slr)
    slr = sw_filter.qs

    # Пагинатор
    paginator = Paginator(slr, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/salary_weekly/salary_weekly.html', {
        'title': 'Зарплата по неделям',
        'sw_filter': sw_filter,
        'err_events_count': err_events_count,
        'page_obj': page_obj,
        'paginator': paginator
    })


@login_required
@permission_required(perm='tph_system.calculate_salary', raise_exception=True)
def salary_calculation(request):
    if request.method == 'POST':
        form = TimeSelectForm(request.POST)
        if form.is_valid():
            beg = form.cleaned_data['beg_date']
            end = form.cleaned_data['end_date']
            sal_calc(beg, end)
            sal_weekly_update(beg, end)
            return redirect('salary_weekly')
    else:
        form = TimeSelectForm()

    return render(request, 'tph_system/salary/salary_calc.html', {
        'title': 'Расчет зарплаты',
        'form': form
    })


@login_required
@permission_required(perm='tph_system.view_salary', raise_exception=True)
def salary_details(request):
    slr = Salary.objects.all()

    # Фильтр
    s_filter = SalaryFilter(request.GET, queryset=slr)
    slr = s_filter.qs

    if request.method == 'POST':
        form = SalaryForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('salary')
    else:
        form = SalaryForm()

    # Пагинатор
    paginator = Paginator(slr, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/salary/salary.html', {
        'title': 'Зарплата по дням',
        'form': form,
        's_filter': s_filter,
        'page_obj': page_obj,
        'paginator': paginator
    })


@login_required
@permission_required(perm='tph_system.view_implevents', raise_exception=True)
def sal_err_events(request):
    err_events = ImplEvents.objects.filter(status='Бизнес ошибка', solved='Нет')

    # Фильтр
    err_filter = ImplEventsFilter(request.GET, queryset=err_events)
    err_events = err_filter.qs

    return render(request, 'tph_system/salary/sal_events.html', {
        'title': 'Ошибки в подсчете зарплат',
        'err_events': err_events,
        'err_filter': err_filter
    })
