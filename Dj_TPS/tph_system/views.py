from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.viewsets import ModelViewSet
from django.views.generic import UpdateView, DeleteView, TemplateView

from tph_system.models import *
from tph_system.serializers import StaffSerializer
from tph_system.forms import StoreForm, StaffForm, ConsStoreForm, TechForm, ScheduleForm
from .filters import *


class StaffViewSet(LoginRequiredMixin, ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer


class StaffUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Staff
    form_class = StaffForm
    template_name = 'tph_system/staff_update.html'
    success_url = '/staff/'
    extra_context = {
        'title': 'Сотрудники - редактирование'
    }
    permission_required = 'tph_system.change_staff'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с сотрудниками'


class StaffDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Staff
    success_url = '/staff/'
    template_name = 'tph_system/staff_delete.html'
    extra_context = {
        'title': 'Сотрудники - удаление'
    }
    permission_required = 'tph_system.delete_staff'
    permission_denied_message = 'У вас нет прав на удаление сотрудников'


class StoreUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Store
    form_class = StoreForm
    template_name = 'tph_system/store_update.html'
    success_url = '/store/'
    extra_context = {
        'title': 'Точки - редактирование'
    }
    permission_required = 'tph_system.change_store'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с точками'


class StoreDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Store
    success_url = '/store/'
    template_name = 'tph_system/store_delete.html'
    extra_context = {
        'title': 'Точки - удаление'
    }
    permission_required = 'tph_system.delete_store'
    permission_denied_message = 'У вас нет прав на удаление точек'


class ConStoreUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = ConsumablesStore
    form_class = ConsStoreForm
    template_name = 'tph_system/conStore_update.html'
    success_url = '/consumables/'
    extra_context = {
        'title': 'Расходники - редактирование'
    }
    permission_required = 'tph_system.change_consumablesstore'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с расходниками'


class ConStoreDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = ConsumablesStore
    success_url = '/consumables/'
    template_name = 'tph_system/conStore_delete.html'
    extra_context = {
        'title': 'Расходники - удаление'
    }
    permission_required = 'tph_system.delete_consumablesstore'
    permission_denied_message = 'У вас нет прав на удаление расходников'


class TechUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Tech
    form_class = TechForm
    template_name = 'tph_system/tech_update.html'
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
    template_name = 'tph_system/tech_delete.html'
    extra_context = {
        'title': 'Техника - удаление',
        'card_title': 'Удаление техники',
        'url_cancel': 'tech'
    }
    permission_required = 'tph_system.delete_tech'
    permission_denied_message = 'У вас нет прав на удаление техники'


class MainPage(PermissionRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'tph_system/main_page.html'
    extra_context = {
        'title': 'Главная страница',
    }
    permission_required = 'tph_system.view_main_page'
    permission_denied_message = 'У вас нет прав на просмотр главной страницы'


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

    return render(request, 'tph_system/store.html', {
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

    return render(request, 'tph_system/staff.html', {
        'title': 'Сотрудники',
        'staffs': staffs,
        'form': form,
        'error': error,
        's_filter': s_filter
    })


@login_required
@permission_required(perm='tph_system.view_consumablesstore', raise_exception=True)
def cons_store(request):
    con_store = ConsumablesStore.objects.all()
    stores = Store.objects.all()

    cs_filter = ConsumablesStoreFilter(request.GET, queryset=con_store)
    con_store = cs_filter.qs

    error = ''
    if request.method == 'POST':
        form_p = ConsStoreForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('cons_store')
        else:
            error = 'Ошибка в заполнении формы'

    form = ConsStoreForm()

    return render(request, 'tph_system/сonsumablesStore.html', {
        'title': 'Расходники',
        'con_store': con_store,
        'form': form,
        'error': error,
        'stores': stores,
        'cs_filter': cs_filter
    })


@login_required
@permission_required(perm='tph_system.view_tech', raise_exception=True)
def tech_mtd(request):
    tech = Tech.objects.all()

    t_filter = TechFilter(request.GET, queryset=tech)
    tech = t_filter.qs

    if request.method == 'POST':
        form = TechForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('tech')
    else:
        form = TechForm()

    return render(request, 'tph_system/tech.html', {
        'title': 'Техника',
        'tech': tech,
        'form': form,
        't_filter': t_filter
    })


@login_required
def schedule_mtd(request):

    #Форма ввода графика в модельном окне
    if request.method == 'POST':
        form = ScheduleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('schedule')
    else:
        form = ScheduleForm()

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

    return render(request, 'tph_system/schedule.html', {
        'title': 'График сотрудников',
        'staffs': staffs,
        'schedule': schedules,
        'form': form,
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
