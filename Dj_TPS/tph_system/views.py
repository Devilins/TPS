import decimal
import math
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum, Count
from django.db.transaction import atomic
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.viewsets import ModelViewSet
from django.views.generic import UpdateView, DeleteView, TemplateView, CreateView

from tph_system.models import *
from tph_system.serializers import StaffSerializer
from tph_system.forms import StoreForm, StaffForm, ConsStoreForm, TechForm, ScheduleForm, SalesForm, CashWithdrawnForm, \
    RefsAndTipsForm, SettingsForm, SalaryForm, PositionSelectFormSet, TimeSelectForm, SalaryWeeklyForm
from .filters import *
from .funcs import *


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
                consumable.count += int(decimal.Decimal((photo_c_old - photo_count)/2).quantize(  # округление
                                        decimal.Decimal('1'),
                                        rounding=decimal.ROUND_HALF_UP
                                        ))
            else:
                consumable = ConsumablesStore.objects.get(cons_short=sale_type, store=store)
                consumable.count += photo_c_old - photo_count
            consumable.save()
        except ConsumablesStore.DoesNotExist:
            pass

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
                consumable.count += math.ceil(photo_count/2)
            else:
                consumable = ConsumablesStore.objects.get(cons_short=sale_type, store=store)
                consumable.count += photo_count
            consumable.save()
        except ConsumablesStore.DoesNotExist:
            pass

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
                consumable.count -= math.ceil(photo_count/2)
            else:
                consumable = ConsumablesStore.objects.get(cons_short=sale_type, store=store)
                consumable.count -= photo_count
            consumable.save()
        except ConsumablesStore.DoesNotExist:
            pass

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

    return render(request, 'tph_system/staff/staff.html', {
        'title': 'Сотрудники',
        'staffs': staffs,
        'form': form,
        'error': error,
        's_filter': s_filter
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

    return render(request, 'tph_system/consumables_store/сonsumablesStore.html', {
        'title': 'Расходники',
        'con_store': con_store,
        'form': form,
        'stores': stores,
        'cs_filter': cs_filter
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

    return render(request, 'tph_system/tech/tech.html', {
        'title': 'Техника',
        'tech': tech,
        'form': form,
        't_filter': t_filter
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
            action = 'deleted'
        else:
            # Обновляем или создаем запись в расписании
            f_store = get_object_or_404(Store, short_name=sel_store)

            schedule, created = Schedule.objects.update_or_create(
                staff=employee,
                date=date,
                defaults={'store': f_store}
            )
            action = 'created' if created else 'updated'

        # Возвращаем успешный ответ с информацией о выполненном действии
        return JsonResponse({'status': 'success', 'action': action})

    except Exception as e:
        # В случае ошибок возвращаем сообщение об ошибке
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
    if 'Должность в смене' in positions:
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

    return render(request, 'tph_system/sales/sales.html', {
        'title': 'Продажи',
        'sales_all': sales_all,
        'form': form,
        'error': error,
        'sale_filter': sale_filter,
        'flag': flag
    })


@login_required
@permission_required(perm='tph_system.view_main_page', raise_exception=True)
def main_page(request):
    sch = Schedule.objects.filter(date=datetime.now()).prefetch_related('staff', 'store').order_by('store')
    now_date = datetime.now().strftime('%d.%m.%Y')
    sales_today = Sales.objects.filter(date=datetime.now())
    con_store = ConsumablesStore.objects.filter(count__lt=30)

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
        'form': form
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

    return render(request, 'tph_system/cash_withdrawn/cash_withdrawn.html', {
        'title': 'Зарплата наличными',
        'cash': cash,
        'form': form,
        'c_filter': c_filter
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
        form_p = SettingsForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('settings')
        else:
            error = 'Ошибка в заполнении формы'

    form = SettingsForm()
    return render(request, 'tph_system/settings/settings.html', {
        'title': 'Настройки',
        'set': stng,
        'form': form,
        'error': error,
        's_filter': s_filter
    })


@login_required
@permission_required(perm='tph_system.view_salaryweekly', raise_exception=True)
def salary_weekly(request):
    slr = SalaryWeekly.objects.all()

    # Фильтр
    s_filter = SalaryWeeklyFilter(request.GET, queryset=slr)
    slr = s_filter.qs

    return render(request, 'tph_system/salary_weekly/salary_weekly.html', {
        'title': 'Зарплата по неделям',
        'slr': slr,
        's_filter': s_filter
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

    return render(request, 'tph_system/salary/salary.html', {
        'title': 'Зарплата по дням',
        'slr': slr,
        'form': form,
        's_filter': s_filter
    })