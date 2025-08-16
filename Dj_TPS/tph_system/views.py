from collections import defaultdict
from datetime import datetime, timedelta
import urllib.parse

from django.db.models import F
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models.functions import TruncDay, TruncWeek
from django.urls import reverse_lazy, reverse
from django.db.transaction import atomic
from django.http import JsonResponse, HttpResponseRedirect, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.views.generic import UpdateView, DeleteView, CreateView
from django.core.paginator import Paginator
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from tph_system.forms import StoreForm, StaffForm, ConsStoreForm, TechForm, SalesForm, CashWithdrawnForm, \
    RefsAndTipsForm, SettingsForm, SalaryForm, PositionSelectFormSet, TimeSelectForm, SalaryWeeklyForm, ImplEventsForm, \
    FinStatsMonthForm, TimeAndTypeSelectForm, CashStoreForm
from .filters import *
from .funcs import *

# API
from rest_framework import viewsets, status
from .serializers import MonitoringSerializer, TelegramUserSerializer, UserSerializer


# Для календаря
# from schedule.views import CalendarByPeriodsView
# from schedule.periods import Month


class MonitoringViewSet(viewsets.ModelViewSet):
    queryset = ImplEvents.objects.filter(event_type__icontains='Error', solved='Нет')
    serializer_class = MonitoringSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]


class TelegramUserViewSet(viewsets.ModelViewSet):
    queryset = TelegramUser.objects.all()
    serializer_class = TelegramUserSerializer
    lookup_field = 'telegram_id'

    def update(self, request, *args, **kwargs):
        instance = self.get_object_or_none()  # новый метод
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if not instance else status.HTTP_200_OK
        )

    def get_object_or_none(self):
        try:
            return self.get_object()  # Пытаемся найти существующую запись
        except Http404:
            return None  # Если не найдено - создадим новую


class SingleUserViewSet(viewsets.ViewSet):
    def retrieve(self, request, username=None):
        user = get_object_or_404(User, username=username)
        serializer = UserSerializer(user)
        return Response(serializer.data)


class StaffUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Staff
    form_class = StaffForm
    template_name = 'tph_system/staff/staff_update.html'
    permission_required = 'tph_system.change_staff'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с сотрудниками'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('staff') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Сотрудники - редактирование'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class StaffDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Staff
    template_name = 'tph_system/staff/staff_delete.html'
    permission_required = 'tph_system.delete_staff'
    permission_denied_message = 'У вас нет прав на удаление сотрудников'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('staff') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Сотрудники - удаление'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


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
    permission_required = 'tph_system.change_consumablesstore'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с расходниками'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('cons_store') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Расходники - редактирование'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context

    @atomic
    def form_valid(self, form):
        # Фиксируем текущие данные
        c_consumable_old = self.get_object().consumable
        c_cons_short_old = self.get_object().cons_short
        c_store_old = self.get_object().store
        c_count_old = self.get_object().count

        # Сохраняем экземпляр техники на точке
        self.object = form.save()

        # Данные из формы
        c_consumable = form.cleaned_data['consumable']
        c_cons_short = form.cleaned_data['cons_short']
        c_store = form.cleaned_data['store']
        c_count = form.cleaned_data['count']

        if c_consumable_old != c_consumable:
            cons_ch = f"Расходник {c_consumable_old} -> {c_consumable}. "
        else:
            cons_ch = ""

        if c_cons_short_old != c_cons_short:
            cons_short_ch = f"Короткое имя {c_cons_short_old} -> {c_cons_short}. "
        else:
            cons_short_ch = ""

        if c_store_old != c_store:
            store_ch = f"Точка {c_store_old} -> {c_store}. "
        else:
            store_ch = ""

        if c_count_old != c_count:
            cnt_ch = f"Количество на точке {c_count_old} -> {c_count}. "
        else:
            cnt_ch = ""

        if cons_ch != "" or cons_short_ch != "" or store_ch != "" or cnt_ch != "":
            # Логируем изменение техники
            ImplEvents.objects.create(
                event_type=f"Consumables_Update",
                event_message=f"{c_consumable} на {c_store.name}. {cons_ch}{cons_short_ch}{store_ch}{cnt_ch}",
                status='Успешно'
            )

        return super().form_valid(form)


class ConStoreDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = ConsumablesStore
    template_name = 'tph_system/consumables_store/conStore_delete.html'
    permission_required = 'tph_system.delete_consumablesstore'
    permission_denied_message = 'У вас нет прав на удаление расходников'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('cons_store') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Расходники - удаление'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class TechUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Tech
    form_class = TechForm
    template_name = 'tph_system/tech/tech_update.html'
    permission_required = 'tph_system.change_tech'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с фототехникой'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('tech') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Техника - редактирование'
        context['card_title'] = 'Изменение техники'
        context['url_cancel'] = 'tech'
        context['url_delete'] = 'tech_delete'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context

    @atomic
    def form_valid(self, form):
        # Фиксируем текущие данные
        t_count_old = self.get_object().count
        t_store_old = self.get_object().store
        t_serial_old = self.get_object().serial_num
        t_name_old = self.get_object().name
        t_date_buy_old = self.get_object().date_buy
        t_warr_old = self.get_object().warranty_date

        # Сохраняем экземпляр техники на точке
        self.object = form.save()

        # Данные из формы
        t_store = form.cleaned_data['store']
        t_name = form.cleaned_data['name']
        t_serial = form.cleaned_data['serial_num']
        t_count = form.cleaned_data['count']
        t_date_buy = form.cleaned_data['date_buy']
        t_warr = form.cleaned_data['warranty_date']

        if t_serial != '':
            ser = f" | {t_serial}"
        else:
            ser = ""

        if t_serial_old != t_serial:
            ser_ch = f"Серийный номер {t_serial_old} -> {t_serial}. "
        else:
            ser_ch = ""

        if t_store_old != t_store:
            store_ch = f"Точка {t_store_old} -> {t_store}. "
        else:
            store_ch = ""

        if t_count_old != t_count:
            cnt_ch = f"Количество {t_count_old} -> {t_count}. "
        else:
            cnt_ch = ""

        if t_name_old != t_name:
            name_ch = f"Наименование {t_name_old} -> {t_name}. "
        else:
            name_ch = ""

        if t_date_buy_old != t_date_buy:
            dt_buy_ch = f"Дата покупки {t_date_buy_old} -> {t_date_buy}. "
        else:
            dt_buy_ch = ""

        if t_warr_old != t_warr:
            warr_ch = f"Дата окончания гарантии {t_warr_old} -> {t_warr}. "
        else:
            warr_ch = ""

        # Логируем изменение техники
        ImplEvents.objects.create(
            event_type=f"Tech_Update",
            event_message=f"{t_name}{ser} на {t_store.name}. {name_ch}{ser_ch}{store_ch}{cnt_ch}{dt_buy_ch}{warr_ch}",
            status='Успешно'
        )

        return super().form_valid(form)


class TechDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Tech
    template_name = 'tph_system/tech/tech_delete.html'
    permission_required = 'tph_system.delete_tech'
    permission_denied_message = 'У вас нет прав на удаление техники'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('tech') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Техника - удаление'
        context['card_title'] = 'Удаление техники'
        context['url_cancel'] = 'tech_update'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class SalesUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Sales
    form_class = SalesForm
    template_name = 'tph_system/sales/sales_update.html'
    permission_required = 'tph_system.change_sales'
    permission_denied_message = 'У вас нет прав на редактирование таблицы с продажами'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('sales') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Продажи - редактирование'
        context['card_title'] = 'Изменение продажи'
        context['url_cancel'] = 'sales'
        context['url_delete'] = 'sales_delete'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context

    @atomic
    def form_valid(self, form):
        # Фиксируем текущее количество фото и суммы
        photo_c_old = self.get_object().photo_count
        sum_old = self.get_object().sum
        payment_type_old = self.get_object().payment_type

        # Сохраняем экземпляр продажи
        self.object = form.save()

        # Данные из формы
        store = form.cleaned_data['store']
        sale_type = form.cleaned_data['sale_type']
        photo_count = form.cleaned_data['photo_count']
        payment_type = form.cleaned_data['payment_type']
        sum = form.cleaned_data['sum']
        date_pay = form.cleaned_data['date']

        try:
            # Корректировка кол-ва магнитов consumable.count в зависимости от разницы photo_count - photo_c_old
            if sale_type in ('Вин. магн.', 'Ср. магн.', 'Бол. магн.'):
                # Корректировка для 'Печать 15x20'. Сохраним на память
                # if sale_type == 'Печать 15x20':
                #     consumable = ConsumablesStore.objects.get(cons_short='Печать A4', store=store)
                #     prev_count = consumable.count
                #     consumable.count += int(decimal.Decimal((photo_c_old - photo_count) / 2).quantize(  # округление
                #         decimal.Decimal('1'),
                #         rounding=decimal.ROUND_HALF_UP
                #     ))
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
        except ObjectDoesNotExist:
            ImplEvents.objects.create(
                event_type=f"ConsStore_Upd_Failed",
                event_message=f"Ошибка при изменении количества расходников на {store.name}. Расходник с "
                              f"функциональным именем {sale_type} не найден. После корректировки имени надо изменить "
                              f"количество этого расходника на точке. Хотели изменить {sale_type} с {photo_c_old} "
                              f"(Кол-во фото в продаже было) на {photo_count} (Кол-во фото в продаже стало).",
                status='Системная ошибка',
                solved='Нет'
            )

        # Уменьшаем нал на конец дня из-за изменения продажи за наличку
        if payment_type_old == 'Наличные' and payment_type == 'Наличные' and sum_old != sum:
            num_chars = CashStore.objects.filter(store=store, date=date_pay).update(cash_evn=F("cash_evn") + sum - sum_old)
            if num_chars == 1:
                # Логируем изменение наличных
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleUpdate",
                    event_message=f"Наличные на {store.name} за {date_pay} увеличены на {sum - sum_old} из-за "
                                  f"изменения продажи за наличные (новая сумма продажи {sum})",
                    status='Успешно'
                )
            else:
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleUpdate_Failed",
                    event_message=f"Ошибка при изменении наличных на {store.name} за {date_pay} при изменении новой продажи "
                                  f"за наличные. Отсутствует запись о наличных за начало дня!",
                    status='Бизнес ошибка',
                    solved='Нет'
                )
        elif payment_type_old != 'Наличные' and payment_type == 'Наличные':
            num_chars = CashStore.objects.filter(store=store, date=date_pay).update(cash_evn=F("cash_evn") + sum)
            if num_chars == 1:
                # Логируем изменение наличных
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleUpdate",
                    event_message=f"Наличные на {store.name} за {date_pay} увеличены на {sum} из-за "
                                  f"изменения способа оплаты продажи c {payment_type_old} на наличные.",
                    status='Успешно'
                )
            else:
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleUpdate_Failed",
                    event_message=f"Ошибка при изменении наличных на {store.name} за {date_pay} при изменении новой "
                                  f"продажи за наличные. Отсутствует запись о наличных за начало дня!",
                    status='Бизнес ошибка',
                    solved='Нет'
                )
        elif payment_type_old == 'Наличные' and payment_type != 'Наличные':
            num_chars = CashStore.objects.filter(store=store, date=date_pay).update(cash_evn=F("cash_evn") - sum_old)
            if num_chars == 1:
                # Логируем изменение наличных
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleUpdate",
                    event_message=f"Наличные на {store.name} за {date_pay} уменьшены на {sum_old} из-за "
                                  f"изменения способа оплаты продажи с наличных на {payment_type}.",
                    status='Успешно'
                )
            else:
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleUpdate_Failed",
                    event_message=f"Ошибка при изменении наличных на {store.name} за {date_pay} при изменении новой "
                                  f"продажи за наличные. Отсутствует запись о наличных за начало дня!",
                    status='Бизнес ошибка',
                    solved='Нет'
                )

        return super().form_valid(form)


class SalesDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Sales
    template_name = 'tph_system/sales/sales_delete.html'
    permission_required = 'tph_system.delete_sales'
    permission_denied_message = 'У вас нет прав на удаление продаж'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('sales') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Продажи - удаление'
        context['card_title'] = 'Удаление продажи'
        context['url_cancel'] = 'sales'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context

    def form_valid(self, form):
        # Данные из объекта БД
        store = self.get_object().store
        sale_type = self.get_object().sale_type
        photo_count = self.get_object().photo_count
        payment_type = self.get_object().payment_type
        sum = self.get_object().sum
        date_pay = self.get_object().date

        try:
            # Корректировка кол-ва магнитов при удалении продажи
            if sale_type in ('Вин. магн.', 'Ср. магн.', 'Бол. магн.'):
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
        except ObjectDoesNotExist:
            ImplEvents.objects.create(
                event_type=f"ConsStore_Del_Failed",
                event_message=f"Ошибка при изменении количества расходников на {store.name}. Расходник с "
                              f"функциональным именем {sale_type} не найден. После корректировки имени надо изменить "
                              f"количество этого расходника на точке. Была удалена продажа с расходником {sale_type} "
                              f"в количестве {photo_count}",
                status='Системная ошибка',
                solved='Нет'
            )

        # Уменьшаем нал на конец дня из-за удаления продажи за наличку
        if payment_type == 'Наличные':
            num_chars = CashStore.objects.filter(store=store, date=date_pay).update(cash_evn=F("cash_evn") - sum)
            if num_chars == 1:
                # Логируем изменение наличных
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleDelete",
                    event_message=f"Наличные на {store.name} за {date_pay} уменьшены на {sum} из-за удаления продажи за наличные",
                    status='Успешно'
                )
            else:
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleDelete_Failed",
                    event_message=f"Ошибка при изменении наличных на {store.name} за {date_pay} при создании новой продажи "
                                  f"за наличные. Отсутствует запись о наличных за начало дня!",
                    status='Бизнес ошибка',
                    solved='Нет'
                )

        success_url = self.get_success_url()
        self.object.delete()
        return HttpResponseRedirect(success_url)


class SalesCreateView(PermissionRequiredMixin, LoginRequiredMixin, CreateView):
    model = Sales
    form_class = SalesForm
    template_name = 'tph_system/sales/sale_add.html'
    permission_required = 'tph_system.add_sales'
    permission_denied_message = 'У вас нет прав на добавление новой продажи'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('sales') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        # Типы продаж и их стоимость за единицу
        stcst_var = Settings.objects.filter(param__icontains='stcst')

        context = super().get_context_data(**kwargs)
        context['title'] = 'Новая продажа'
        context['card_title'] = 'Добавление новой продажи'
        context['url_cancel'] = 'sales'
        context['current_filter_params'] = self.request.GET.urlencode()
        context['stcst_var'] = stcst_var
        return context

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
        payment_type = form.cleaned_data['payment_type']
        sum = form.cleaned_data['sum']
        date_pay = form.cleaned_data['date']

        # Меняем расходники только для магнитов
        try:
            if sale_type in ('Вин. магн.', 'Ср. магн.', 'Бол. магн.'):
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
        except ObjectDoesNotExist:
            ImplEvents.objects.create(
                event_type=f"ConsStore_Crt_Failed",
                event_message=f"Ошибка при изменении количества расходников на {store.name}. Расходник с "
                              f"функциональным именем {sale_type} не найден. После корректировки имени надо изменить "
                              f"количество этого расходника на точке. Было продано {sale_type} в количестве "
                              f"{photo_count}",
                status='Системная ошибка',
                solved='Нет'
            )

        # Увеличиваем нал на конец дня из-за продажи за наличку
        if payment_type == 'Наличные':
            num_chars = CashStore.objects.filter(store=store, date=date_pay).update(cash_evn=F("cash_evn") + sum)
            if num_chars == 1:
                # Логируем изменение наличных
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleCreate",
                    event_message=f"Наличные на {store.name} за {date_pay} увеличены на {sum} из-за новой продажи за наличные",
                    status='Успешно'
                )
            else:
                ImplEvents.objects.create(
                    event_type=f"UpdCash_SaleCreate_Failed",
                    event_message=f"Ошибка при изменении наличных на {store.name} за {date_pay} при создании новой продажи "
                                  f"за наличные. Отсутствует запись о наличных за начало дня!",
                    status='Бизнес ошибка',
                    solved='Нет'
                )

        return super().form_valid(form)


class CashWithdrawnCreateView(PermissionRequiredMixin, LoginRequiredMixin, CreateView):
    model = CashWithdrawn
    form_class = CashWithdrawnForm
    template_name = 'tph_system/cash_withdrawn/c_w_add.html'
    permission_required = 'tph_system.add_cashwithdrawn'
    permission_denied_message = 'У вас нет прав на добавление записи о выдаче зп наличными'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('cash_withdrawn') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        auth_staff = Staff.objects.get(st_username=self.request.user)

        try:
            store_staff_working_obj = Store.objects.get(
                name=Schedule.objects.get(date=datetime.now(),
                                          staff_id=auth_staff).store)
        except ObjectDoesNotExist:
            store_staff_working_obj = None

        cash_on_store = CashStore.objects.filter(date=datetime.now(), store=store_staff_working_obj)

        context = super().get_context_data(**kwargs)
        context['title'] = 'Выдача ЗП наличными'
        context['card_title'] = 'Забрать наличные'
        context['url_cancel'] = 'cash_withdrawn'
        context['current_filter_params'] = self.request.GET.urlencode()
        context['cash_on_store'] = cash_on_store
        return context

    def get_initial(self):
        initial = super().get_initial()
        auth_staff = Staff.objects.get(st_username=self.request.user)

        try:
            store_staff_working_obj = Store.objects.get(
                name=Schedule.objects.get(date=datetime.now(),
                                          staff_id=auth_staff).store)
        except ObjectDoesNotExist:
            store_staff_working_obj = None

        initial.update({
            'store': store_staff_working_obj,
            'date': datetime.now(),
            'staff': auth_staff
        })
        return initial

    @atomic
    def form_valid(self, form):
        # Сохраняем экземпляр формы
        self.object = form.save()

        # Данные из формы
        withdrawn = form.cleaned_data["withdrawn"]
        store = form.cleaned_data["store"]
        date = form.cleaned_data["date"]
        staff = form.cleaned_data["staff"]

        # Уменьшаем кол-во нала на точке в этот день
        num_chars = CashStore.objects.filter(store=store, date=date).update(cash_evn=F("cash_evn") - withdrawn)
        if num_chars == 1:
            # Логируем изменение наличных
            ImplEvents.objects.create(
                event_type=f"UpdCash_WithdrawnCreate",
                event_message=f"Наличные на {store.name} за {date} уменьшены на {withdrawn} из-за "
                              f"создания записи о выдаче ЗП сотруднику {staff} за наличные ",
                status='Успешно'
            )
        else:
            ImplEvents.objects.create(
                event_type=f"UpdCash_WithdrawnCreate_Failed",
                event_message=f"Ошибка при изменении наличных на {store.name} за {date} при изменении записи о "
                              f"выдаче ЗП сотруднику {staff} за наличные. Отсутствует запись о наличных за начало дня!",
                status='Бизнес ошибка',
                solved='Нет'
            )

        return super().form_valid(form)


class CashWithdrawnUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = CashWithdrawn
    form_class = CashWithdrawnForm
    template_name = 'tph_system/cash_withdrawn/c_w_update.html'
    permission_required = 'tph_system.change_cashwithdrawn'
    permission_denied_message = 'У вас нет прав на редактирование истории выдачи наличных'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('cash_withdrawn') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Зарплата наличными - редактирование'
        context['card_title'] = 'Редактирование данных'
        context['url_cancel'] = 'cash_withdrawn'
        context['url_delete'] = 'c_w_delete'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context

    @atomic
    def form_valid(self, form):
        # Фиксируем текущее withdrawn
        withdrawn_old = self.get_object().withdrawn

        # Сохраняем экземпляр продажи
        self.object = form.save()

        # Данные из формы
        withdrawn = form.cleaned_data["withdrawn"]
        store = form.cleaned_data["store"]
        date = form.cleaned_data["date"]
        staff = form.cleaned_data["staff"]

        # Изменяем кол-во нала на точке в этот день
        num_chars = CashStore.objects.filter(store=store, date=date).update(cash_evn=F("cash_evn") + withdrawn_old - withdrawn)
        if num_chars == 1:
            # Логируем изменение наличных
            ImplEvents.objects.create(
                event_type=f"UpdCash_WithdrawnUpdate",
                event_message=f"Наличные на {store.name} за {date} изменены на {withdrawn_old - withdrawn} из-за "
                              f"изменения записи о выдаче ЗП сотруднику {staff} за наличные ",
                status='Успешно'
            )
        else:
            ImplEvents.objects.create(
                event_type=f"UpdCash_WithdrawnUpdate_Failed",
                event_message=f"Ошибка при изменении наличных на {store.name} за {date} при изменении записи о "
                              f"выдаче ЗП сотруднику {staff} за наличные. Отсутствует запись о наличных за начало дня!",
                status='Бизнес ошибка',
                solved='Нет'
            )

        return super().form_valid(form)


class CashWithdrawnDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = CashWithdrawn
    template_name = 'tph_system/cash_withdrawn/c_w_delete.html'
    permission_required = 'tph_system.delete_cashwithdrawn'
    permission_denied_message = 'У вас нет прав на удаление истории выдачи наличных'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('cash_withdrawn') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Зарплата наличными - удаление'
        context['card_title'] = 'Удаление данных'
        context['url_cancel'] = 'c_w_update'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context

    @atomic
    def form_valid(self, form):
        # Данные из объекта формы
        store = self.get_object().store
        date = self.get_object().date
        withdrawn = self.get_object().withdrawn
        staff = self.get_object().staff

        # Увеличиваем кол-во нала на точке в этот день
        num_chars = CashStore.objects.filter(store=store, date=date).update(cash_evn=F("cash_evn") + withdrawn)
        if num_chars == 1:
            # Логируем изменение наличных
            ImplEvents.objects.create(
                event_type=f"UpdCash_WithdrawnDelete",
                event_message=f"Наличные на {store.name} за {date} увеличены на {withdrawn} из-за "
                              f"удалении записи о выдаче ЗП сотруднику {staff} за наличные ",
                status='Успешно'
            )
        else:
            ImplEvents.objects.create(
                event_type=f"UpdCash_WithdrawnDelete_Failed",
                event_message=f"Ошибка при изменении наличных на {store.name} за {date} при изменении записи о "
                              f"выдаче ЗП сотруднику {staff} за наличные. Отсутствует запись о наличных за начало дня!",
                status='Бизнес ошибка',
                solved='Нет'
            )

        success_url = self.get_success_url()
        self.object.delete()
        return HttpResponseRedirect(success_url)


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
    permission_required = 'tph_system.change_settings'
    permission_denied_message = 'У вас нет прав на редактирование параметров'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('settings') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Настройки - редактирование'
        context['card_title'] = 'Редактирование параметра'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class SettingsDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Settings
    template_name = 'tph_system/settings/set_delete.html'
    permission_required = 'tph_system.delete_settings'
    permission_denied_message = 'У вас нет прав на удаление параметра'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('settings') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Настройки - удаление'
        context['card_title'] = 'Удаление параметра'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class SalaryUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = Salary
    form_class = SalaryForm
    template_name = 'tph_system/salary/salary_update.html'
    permission_required = 'tph_system.change_salary'
    permission_denied_message = 'У вас нет прав на редактирование зарплат'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('salary') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Зарплаты - редактирование'
        context['card_title'] = 'Редактирование записи с зарплатой'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class SalaryDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Salary
    template_name = 'tph_system/salary/salary_delete.html'
    permission_required = 'tph_system.delete_salary'
    permission_denied_message = 'У вас нет прав на удаление зарплат'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('salary') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Зарплаты - удаление'
        context['card_title'] = 'Удаление записи с зарплатой'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class SalaryWeeklyUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = SalaryWeekly
    form_class = SalaryWeeklyForm
    template_name = 'tph_system/salary_weekly/salary_w_upd.html'
    permission_required = 'tph_system.change_salaryweekly'
    permission_denied_message = 'У вас нет прав на редактирование зарплат по неделям'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('salary_weekly') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Зарплаты по неделям - редактирование'
        context['card_title'] = 'Редактирование записи с зарплатой по неделям'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class SalaryWeeklyDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = SalaryWeekly
    template_name = 'tph_system/salary_weekly/salary_w_del.html'
    permission_required = 'tph_system.delete_salaryweekly'
    permission_denied_message = 'У вас нет прав на удаление зарплат по неделям'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('salary_weekly') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Зарплаты по неделям - удаление'
        context['card_title'] = 'Удаление записи с зарплатой по неделям'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class ImplEventsUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = ImplEvents
    form_class = ImplEventsForm
    template_name = 'tph_system/salary/sal_events_edit.html'
    permission_required = 'tph_system.change_implevents'
    permission_denied_message = 'У вас нет прав на редактирование событий'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('sal_events') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Ошибки в подсчете зарплат - редактирование'
        context['card_title'] = 'Редактирование событий'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class FinStatsMonthUpdateView(PermissionRequiredMixin, LoginRequiredMixin, UpdateView):
    model = FinStatsMonth
    form_class = FinStatsMonthForm
    template_name = 'tph_system/fin_stats/fin_stats_update.html'
    permission_required = 'tph_system.change_finstatsmonth'
    permission_denied_message = 'У вас нет прав на редактирование расходов за месяц'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('fin_stats') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Финансы компании - редактирование'
        context['card_title'] = 'Редактирование расходов за'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


class FinStatsMonthDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = FinStatsMonth
    template_name = 'tph_system/fin_stats/fin_stats_delete.html'
    permission_required = 'tph_system.delete_finstatsmonth'
    permission_denied_message = 'У вас нет прав на удаление записи с финансами по компании'

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse('fin_stats') + '?' + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Финансы компании - удаление'
        context['card_title'] = 'Удаление записи с финансами по компании'
        context['current_filter_params'] = self.request.GET.urlencode()
        return context


# ---------------------------Классы календаря----------------------------------
# class CalendarView(LoginRequiredMixin, CalendarByPeriodsView):
#     template_name = 'tph_system/calendar/calendar.html'
#     period = Month
#
#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         context['events'] = CalendarEvent.objects.all()
#         context['event_types'] = CalendarEvent.EVENT_TYPES
#         context['event_colors'] = CalendarEvent.EVENT_COLORS
#         return context
#
#
# class EventCreateView(LoginRequiredMixin, CreateView):
#     model = CalendarEvent
#     template_name = 'tph_system/calendar/event_form.html'
#     success_url = reverse_lazy('calendar')
#
#     def get_form_class(self):
#         from django import forms
#
#         class EventForm(forms.ModelForm):
#             class Meta:
#                 model = CalendarEvent
#                 fields = ['event_type', 'title', 'start_date', 'end_date', 'description']
#
#             def __init__(self, *args, **kwargs):
#                 super().__init__(*args, **kwargs)
#                 self.fields['start_date'].widget = forms.DateInput(attrs={'type': 'date'})
#                 self.fields['end_date'].widget = forms.DateInput(attrs={'type': 'date'})
#
#         return EventForm
#
#     def form_valid(self, form):
#         if form.instance.event_type == 'vacation':
#             form.instance.employee = self.request.user
#         return super().form_valid(form)
#
#
# class VacationCreateView(EventCreateView):
#     template_name = 'tph_system/calendar/vacation_form.html'
#
#     def get_form_class(self):
#         form_class = super().get_form_class()
#         form_class._meta.fields = ['start_date', 'end_date', 'description']
#         return form_class
#
#     def form_valid(self, form):
#         form.instance.event_type = 'vacation'
#         return super().form_valid(form)
# --------------------------------Конец--------------------------------


@login_required
def index(request):
    return redirect('main_page', permanent=True)


@login_required
@permission_required(perm='tph_system.view_store', raise_exception=True)
def store(request):
    stores = Store.objects.exclude(store_status='Закрытая')

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
    # Если нет параметров в URL, редиректим с установленным фильтром
    if not request.GET:
        return redirect('{}?dism_status=Работает'.format(request.path))

    staffs = Staff.objects.all().select_related('st_username')

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    s_filter = StaffFilter(request.GET, queryset=staffs)
    staffs = s_filter.qs

    error = ''
    if request.method == 'POST':
        form_p = StaffForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            # Возвращаемся на страницу с сохранением фильтров (используется ПРЯМАЯ ССЫЛКА)
            return redirect(f'/staff/?{current_filter_params}')
        else:
            error = 'Ошибка в заполнении формы'

    form = StaffForm()

    # Пагинатор
    paginator = Paginator(staffs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/staff/staff.html', {
        'title': 'Сотрудники',
        'form': form,
        'error': error,
        's_filter': s_filter,
        'page_obj': page_obj,
        'paginator': paginator,
        'staff_count': paginator.count,
        'current_filter_params': current_filter_params
    })


@login_required
@permission_required(perm='tph_system.view_consumablesstore', raise_exception=True)
def cons_store(request):
    auth_user = User.objects.get(id=request.user.id)

    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(date=datetime.now(),
                                      staff_id=Staff.objects.get(st_username=auth_user)).store)
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    # Если нет параметров в URL, редиректим с установленным фильтром
    if not request.GET and store_staff_working_obj is not None:
        return redirect(('{}?store=' + str(store_staff_working_obj.id)).format(request.path))

    # Сотрудник видит расходники той точки, на которой работает по графику, если нет права на просмотр всех расходников
    if auth_user.has_perm('tph_system.consumables_view_all_stores'):
        con_store = ConsumablesStore.objects.all().select_related('store')
    else:
        con_store = ConsumablesStore.objects.filter(store=store_staff_working_obj).select_related('store')

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    #Фильтр
    cs_filter = ConsumablesStoreFilter(request.GET, queryset=con_store)
    con_store = cs_filter.qs

    if request.method == 'POST':
        form = ConsStoreForm(request.POST)
        if form.is_valid():
            form.save()
            # Возвращаемся на страницу с сохранением фильтров (используется ПРЯМАЯ ССЫЛКА)
            return redirect(f'/consumables/?{current_filter_params}')
    else:
        form = ConsStoreForm(initial={'store': store_staff_working_obj})

    # Пагинатор
    paginator = Paginator(con_store, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/consumables_store/сonsumablesStore.html', {
        'title': 'Расходники',
        'form': form,
        'cs_filter': cs_filter,
        'page_obj': page_obj,
        'paginator': paginator,
        'cons_count': paginator.count,
        'current_filter_params': current_filter_params
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

    # Если нет параметров в URL, редиректим с установленным фильтром
    if not request.GET and store_staff_working_obj is not None:
        return redirect(('{}?store=' + str(store_staff_working_obj.id)).format(request.path))

    # Сотрудник видит расходники той точки, на которой работает по графику, если нет права на просмотр всех расходников
    if auth_user.has_perm('tph_system.tech_view_all_stores'):
        tech = Tech.objects.all().select_related('store')
    else:
        tech = Tech.objects.filter(store=store_staff_working_obj).select_related('store')

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    # Фильтр
    t_filter = TechFilter(request.GET, queryset=tech)
    tech = t_filter.qs

    if request.method == 'POST':
        form = TechForm(request.POST)
        if form.is_valid():
            form.save()
            # Возвращаемся на страницу с сохранением фильтров (используется ПРЯМАЯ ССЫЛКА)
            return redirect(f'/tech/?{current_filter_params}')
    else:
        form = TechForm(initial={'store': store_staff_working_obj})

    # Пагинатор
    paginator = Paginator(tech, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/tech/tech.html', {
        'title': 'Техника',
        'form': form,
        't_filter': t_filter,
        'page_obj': page_obj,
        'paginator': paginator,
        'tech_count': paginator.count,
        'current_filter_params': current_filter_params
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

    staffs = Staff.objects.filter(dism_status="Работает").select_related('st_username')
    stores = Store.objects.filter(store_status="Действующая")
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
                    'store': schedule.store.short_name if schedule else '',
                    'work_time': schedule.work_time if schedule else '',  # Добавляем информацию о времени работы
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


@login_required
@permission_required(perm='tph_system.change_schedule', raise_exception=True)
@require_http_methods(["POST"])
def update_schedule(request):
    # Получаем данные из POST-запроса
    staff_id = request.POST.get('staff_id')
    date = request.POST.get('date')
    sel_store = request.POST.get('store')
    work_time = request.POST.get('work_time', '')  # Новое поле для времени работы

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
                defaults={
                    'store': f_store,
                    'work_time': work_time  # Добавляем время работы
                }
            )
            action = 'Добавлено' if created else 'Обновлено'

        # Возвращаем успешный ответ с информацией о выполненном действии
        return JsonResponse({'status': 'success', 'action': action, 'work_time': work_time})

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

    if auth_user.has_perm('tph_system.user_sales_view_all'):
        today_sch = Schedule.objects.filter(date=datetime.now())
    else:
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
@permission_required(perm='tph_system.add_sales', raise_exception=True)
def m_cash_add(request):
    auth_user = User.objects.get(id=request.user.id)
    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(date=datetime.now(),
                                      staff_id=Staff.objects.get(st_username=auth_user)).store)
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    if request.method == 'POST':
        form = CashStoreForm(request.POST)
        if form.is_valid():
            instance = form.save(commit=False)
            instance.cash_evn = form.cleaned_data['cash_mrn']
            instance.save()
            return redirect('sales')
    else:
        form = CashStoreForm(initial={
                                    'store': store_staff_working_obj,
                                    'date': datetime.now()
                                })

    return render(request, 'tph_system/sales/cash_add.html', {
        'card_title': 'Наличные на точке на начало дня',
        'url_cancel': 'sales',
        'form': form,
        'store': store_staff_working_obj,
        'date': datetime.now().date()
    })


@login_required
@permission_required(perm='tph_system.view_sales', raise_exception=True)
def sales(request):
    # Если нет параметров в URL, редиректим с установленным фильтром
    if not request.GET:
        return redirect(('{}?date_from=' + str(dt_format(datetime.now())) +
                         '&date_by=' + str(dt_format(datetime.now()))).format(request.path))

    auth_user = User.objects.get(id=request.user.id)
    auth_staff = Staff.objects.get(st_username=auth_user)
    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(date=datetime.now(),
                                      staff_id=auth_staff).store)
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    # Сотрудник видит только сегодняшние продажи точки, на которой работает по графику, если нет права на просмотр всех продаж
    if auth_user.has_perm('tph_system.user_sales_view_all'):
        sales_all = Sales.objects.all().select_related('store', 'staff', 'photographer', 'user_edited')
    else:
        sales_all = Sales.objects.filter(store=store_staff_working_obj, date=datetime.now()
                                         ).select_related('store', 'staff', 'photographer', 'user_edited')

    # Флаг для кнопки выбора роли на сегодня
    flag = 0
    today_staff = Schedule.objects.filter(date=datetime.now(), staff_id=auth_staff)
    positions = [i.position for i in today_staff]
    if 'Роль не указана' in positions:
        flag = 1

    # Флаг для кнопки наличных на начало дня
    flag_cash = 0
    cash_on_store = CashStore.objects.filter(date=datetime.now(), store=store_staff_working_obj)
    if not cash_on_store.exists() and store_staff_working_obj is not None:
        flag_cash = 1

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    #Фильтр
    sale_filter = SalesFilter(request.GET, queryset=sales_all)
    sales_all = sale_filter.qs

    # Итоги продаж
    cashbx_all = sales_all.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']
    cashbx_park = sales_all.filter(payment_type='Оплата через парк').aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']
    cashbx_card = sales_all.filter(payment_type='Карта').aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']
    cashbx_cash = sales_all.filter(payment_type='Наличные').aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']
    cashbx_qr_p = sales_all.filter(payment_type__in=['Оплата по QR коду', 'Перевод по номеру телефона']
                                   ).aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']
    cashbx_orders = sales_all.filter(payment_type='Предоплаченный заказ',
                                     sale_type__in=['Заказной фотосет', 'Заказ выездной']
                                     ).aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']

    if cashbx_all is None: cashbx_all = 0
    if cashbx_park is None: cashbx_park = 0
    if cashbx_card is None: cashbx_card = 0
    if cashbx_cash is None: cashbx_cash = 0
    if cashbx_qr_p is None: cashbx_qr_p = 0
    if cashbx_orders is None: cashbx_orders = 0

    # Сотрудники без ролей
    staff_without_role = len(Schedule.objects.filter(position='Роль не указана', date__lte=datetime.now()))

    error = ''
    if request.method == 'POST':
        form_p = SalesForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            # Возвращаемся на страницу с сохранением фильтров (используется ПРЯМАЯ ССЫЛКА)
            return redirect(f'/sales/?{current_filter_params}')
        else:
            error = 'Ошибка в заполнении формы'

    form = SalesForm(initial={
        'store': store_staff_working_obj,
        'date': datetime.now(),
        'staff': auth_staff
    })

    # Пагинатор
    paginator = Paginator(sales_all, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/sales/sales.html', {
        'title': 'Продажи',
        'form': form,
        'error': error,
        'sale_filter': sale_filter,
        'flag': flag,
        'flag_cash': flag_cash,
        'page_obj': page_obj,
        'paginator': paginator,
        'count_sales': paginator.count,
        'cashbx_all': cashbx_all,
        'cashbx_park': cashbx_park,
        'cashbx_card': cashbx_card,
        'cashbx_cash': cashbx_cash,
        'cashbx_qr_p': cashbx_qr_p,
        'cashbx_orders': cashbx_orders,
        'current_filter_params': current_filter_params,
        'staff_without_role': staff_without_role,
        'cash_on_store': cash_on_store
    })


@login_required
@permission_required(perm='tph_system.view_main_page', raise_exception=True)
def main_page(request):
    # Фильтр даты
    date_filter = MainPageFilter(
        request.GET or {'selected_date': datetime.today()},
        queryset=Schedule.objects.filter(date=datetime.today())
    )

    # Извлекаем валидную дату из фильтра
    selected_date = datetime.today()
    if date_filter.form.is_valid():
        selected_date = date_filter.form.cleaned_data.get('selected_date')

    sch = Schedule.objects.filter(date=selected_date).select_related('staff', 'store').order_by('store', 'staff')
    sys_errors_count = ImplEvents.objects.filter(status='Системная ошибка', solved='Нет').count()
    err_events_count = ImplEvents.objects.filter(status='Бизнес ошибка', solved='Нет').count()
    tech_upd_info = ImplEvents.objects.filter(event_type='Tech_Update', date_created__date=selected_date)
    wdr = CashWithdrawn.objects.filter(date=selected_date).select_related('staff', 'store').order_by('store', 'staff')

    # Заканчивающиеся расходники
    con_store = ConsumablesStore.objects.filter(count__lt=param_gets('cons_others')).select_related('store')
    con_store = con_store.union(
        ConsumablesStore.objects.filter(cons_short__in=['Бол. магн.', 'Вин. магн.', 'Ср. магн.'],
                                        count__lt=param_gets('cons_mgn')).select_related('store'))
    con_store = con_store.union(ConsumablesStore.objects.filter(cons_short__in=['Чеки', 'Листочки'],
                                                                count__lt=param_gets(
                                                                    'cons_check_lists')).select_related('store'))
    con_store = con_store.union(ConsumablesStore.objects.filter(cons_short='Визитки',
                                                                count__lt=param_gets('cons_cards')).select_related(
        'store'))
    con_store = con_store.order_by('store')

    # Кассы за день
    sls = list(
        Sales.objects.filter(date=selected_date).values('store').annotate(store_sum=Sum('sum')).order_by('store'))
    st = Store.objects.values('id', 'name')
    dic = {}
    for i in sls:
        dic[st.get(id=i['store'])['name']] = i['store_sum']

    cashbx_all = sum(dic.values())

    # Кол-во заказов за день
    zak = list(Sales.objects.filter(date=selected_date,
                                    sale_type__in=['Заказной фотосет', 'Заказ выездной']
                                    ).values('store', 'sale_type').annotate(zak_count=Count('sale_type')).order_by('store'))
    zak_cnt = defaultdict(list)
    for i in zak:
        sale_info = {
            'sale_type': i['sale_type'],
            'zak_count': i['zak_count']
        }
        zak_cnt[st.get(id=i['store'])['name']].append(sale_info)
    zak_cnt = dict(zak_cnt)

    zak_all = 0
    for s in zak_cnt.values():
        for k in s:
            zak_all += int(k['zak_count'])

    tips = RefsAndTips.objects.all()
    ll_tips = tips.filter(title='Лазерлэнд')
    bw_tips = tips.filter(title='Бигвол')

    # Сверка наличных с утра с прошлым вечером
    cash_yesterday = {}
    for store in Store.objects.filter(store_status="Действующая"):
        try:
            cash_yesterday[store.name] = CashStore.objects.filter(store=store, date__lte=selected_date)[1:2][0].cash_evn
        except IndexError:
            cash_yesterday[store.name] = -1

    check_cash = {}
    for csh in CashStore.objects.filter(date=selected_date):
        if csh.cash_mrn == cash_yesterday[csh.store.name]:
            check_cash[csh.store.name] = {
                'check': f'{csh.cash_evn} | Сверка ОК',
                'color': 1
            }
        elif cash_yesterday[csh.store.name] == -1:
            check_cash[csh.store.name] = {
                'check': f'{csh.cash_evn} | Нет данных для сверки',
                'color': 2
            }
        else:
            check_cash[csh.store.name] = {
                'check': f'{csh.cash_evn} | Расхождение ({cash_yesterday[csh.store.name]})',
                'color': 0
            }

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
        'now_date': selected_date,
        'dic': dic,
        'cashbx_all': cashbx_all,
        'con_store': con_store,
        'll_tips': ll_tips,
        'bw_tips': bw_tips,
        'error': error,
        'form': form,
        'sys_errors_count': sys_errors_count,
        'err_events_count': err_events_count,
        'tech_upd_info': tech_upd_info,
        'date_filter': date_filter,
        'wdr': wdr,
        'zak_cnt': zak_cnt,
        'zak_all': zak_all,
        'check_cash': check_cash
    })


@login_required
@permission_required(perm='tph_system.view_cashwithdrawn', raise_exception=True)
def cash_withdrawn(request):
    auth_user = User.objects.get(id=request.user.id)
    auth_staff = Staff.objects.get(st_username=auth_user)

    try:
        staff_sch = Schedule.objects.get(date=datetime.now(), staff_id=auth_staff)
        store_staff_working_obj = Store.objects.get(name=staff_sch.store)
    except ObjectDoesNotExist:
        staff_sch = None
        store_staff_working_obj = None

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    # Сотрудник видит только свои списания, если нет права на просмотр всех списаний зарплаты
    if auth_user.has_perm('tph_system.view_all_cashwithdrawn'):
        cash = CashWithdrawn.objects.all().select_related('store', 'staff')

        # Фильтр
        c_filter = CashWithdrawnFilter(request.GET, queryset=cash)
        cash = c_filter.qs
    else:
        cash = CashWithdrawn.objects.filter(
            staff_id=auth_staff
        ).select_related('store', 'staff')

        # Фильтр
        c_filter = CashWithdrawnFilter(request.GET, queryset=cash)
        cash = c_filter.qs

        # Если сотрудник админ - то видит списание налички всех работников в этот день на этой точке
        if staff_sch is not None and staff_sch.position in ('Администратор', 'Универсальный фотограф'):
            sch = Schedule.objects.filter(date=datetime.now(), store=store_staff_working_obj
                                          ).exclude(staff_id=auth_staff).values_list('staff', flat=True)
            cash = cash.union(CashWithdrawn.objects.filter(staff_id__in=[i for i in sch], date=datetime.now()
                                                           ).select_related('store', 'staff')).order_by('-date')

    # Флаг для кнопки наличных на начало дня
    flag_cash = 0
    cash_on_store = CashStore.objects.filter(date=datetime.now(), store=store_staff_working_obj)
    if not cash_on_store.exists() and store_staff_working_obj is not None:
        flag_cash = 1

    # Пагинатор
    paginator = Paginator(cash, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/cash_withdrawn/cash_withdrawn.html', {
        'title': 'Зарплата наличными',
        'c_filter': c_filter,
        'page_obj': page_obj,
        'paginator': paginator,
        'with_count': paginator.count,
        'current_filter_params': current_filter_params,
        'flag_cash': flag_cash
    })


@login_required
@permission_required(perm='tph_system.view_settings', raise_exception=True)
def settings(request):
    stng = Settings.objects.all()

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    # Фильтр
    s_filter = SettingsFilter(request.GET, queryset=stng)
    stng = s_filter.qs

    error = ''
    if request.method == 'POST':
        form = SettingsForm(request.POST)
        if form.is_valid():
            form.save()
            # Возвращаемся на страницу с сохранением фильтров (используется ПРЯМАЯ ССЫЛКА)
            return redirect(f'/settings/?{current_filter_params}')
            # return reverse('settings') + '?' + request.GET.urlencode()
        else:
            error = 'Ошибка в заполнении формы'
    else:
        form = SettingsForm()

    # Пагинатор
    paginator = Paginator(stng, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/settings/settings.html', {
        'title': 'Настройки',
        'form': form,
        'error': error,
        's_filter': s_filter,
        'page_obj': page_obj,
        'paginator': paginator,
        'set_count': paginator.count,
        'current_filter_params': current_filter_params
    })


@login_required
@permission_required(perm='tph_system.view_salaryweekly', raise_exception=True)
def salary_weekly(request):
    # Если нет параметров в URL, редиректим с установленным фильтром
    f_week_begin = datetime.now() - timedelta(datetime.weekday(datetime.now()))  # Вычисляем начало недели
    if not request.GET:
        return redirect(('{}?week_begin=' + str(dt_format(f_week_begin - timedelta(7)))).format(request.path))

    auth_user = User.objects.get(id=request.user.id)

    # Сотрудник видит только свою зарплату, если нет права на просмотр всех зарплат
    if auth_user.has_perm('tph_system.view_all_salary'):
        slr = SalaryWeekly.objects.all().select_related('staff')
    else:
        slr = SalaryWeekly.objects.filter(staff=Staff.objects.get(st_username=auth_user)
                                          ).select_related('staff')

    err_events_count = ImplEvents.objects.filter(status='Бизнес ошибка', solved='Нет').count()
    sys_errors_count = ImplEvents.objects.filter(status='Системная ошибка', solved='Нет').count()
    sal_withdrawn_err = CashWithdrawn.objects.filter(
        date__in=date_generator(datetime.today() - timedelta(days=21), datetime.today() + timedelta(days=1)),
        week_beg_rec=None
    ).count()

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    # Фильтр
    sw_filter = SalaryWeeklyFilter(request.GET, queryset=slr)
    slr = sw_filter.qs

    # Пагинатор
    paginator = Paginator(slr, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/salary_weekly/salary_weekly.html', {
        'title': 'Зарплата по неделям',
        'sw_filter': sw_filter,
        'err_events_count': err_events_count,
        'sys_errors_count': sys_errors_count,
        'sal_withdrawn_err': sal_withdrawn_err,
        'page_obj': page_obj,
        'paginator': paginator,
        'sal_week_count': paginator.count,
        'current_filter_params': current_filter_params
    })


@login_required
@permission_required(perm='tph_system.calculate_salary', raise_exception=True)
def salary_calculation(request):
    if request.method == 'POST':
        form = TimeAndTypeSelectForm(request.POST)
        if form.is_valid():
            beg = form.cleaned_data['beg_date']
            end = form.cleaned_data['end_date']
            calc_flag = form.cleaned_data['sal_calc_flag']
            weekly_flag = form.cleaned_data['sal_weekly_flag']
            if calc_flag is True: sal_calc(beg, end)
            if weekly_flag is True: sal_weekly_update(beg, end)
            return redirect('salary_weekly')
    else:
        form = TimeAndTypeSelectForm()

    return render(request, 'tph_system/salary/salary_calc.html', {
        'title': 'Расчет зарплаты',
        'form': form
    })


@login_required
@permission_required(perm='tph_system.view_salary', raise_exception=True)
def salary_details(request):
    # Если нет параметров в URL, редиректим с установленным фильтром
    if not request.GET:
        return redirect(('{}?date_from=' + str(dt_format(datetime.now() - timedelta(1))) +
                         '&date_by=' + str(dt_format(datetime.now()))).format(request.path))

    auth_user = User.objects.get(id=request.user.id)

    # Сотрудник видит только свою зарплату, если нет права на просмотр всех зарплат
    if auth_user.has_perm('tph_system.view_all_salary'):
        slr = Salary.objects.all().select_related('store', 'staff')
    else:
        slr = Salary.objects.filter(staff=Staff.objects.get(st_username=auth_user)
                                    ).select_related('store', 'staff')

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    # Фильтр
    s_filter = SalaryFilter(request.GET, queryset=slr)
    slr = s_filter.qs

    if request.method == 'POST':
        form = SalaryForm(request.POST)
        if form.is_valid():
            form.save()
            # Возвращаемся на страницу с сохранением фильтров (используется ПРЯМАЯ ССЫЛКА)
            return redirect(f'/salary/?{current_filter_params}')
    else:
        form = SalaryForm()

    # Пагинатор
    paginator = Paginator(slr, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'tph_system/salary/salary.html', {
        'title': 'Зарплата по дням',
        'form': form,
        's_filter': s_filter,
        'page_obj': page_obj,
        'paginator': paginator,
        'sal_count': paginator.count,
        'current_filter_params': current_filter_params
    })


@login_required
@permission_required(perm='tph_system.view_implevents', raise_exception=True)
def sal_err_events(request):
    err_events = ImplEvents.objects.filter(status__in=['Бизнес ошибка', 'Системная ошибка'], solved='Нет')

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    # Фильтр
    err_filter = ImplEventsFilter(request.GET, queryset=err_events)
    err_events = err_filter.qs

    return render(request, 'tph_system/salary/sal_events.html', {
        'title': 'Ошибки в работе системы',
        'err_events': err_events,
        'err_filter': err_filter,
        'current_filter_params': current_filter_params
    })


def get_default_dates():
    today = datetime.now().date()
    start_date = today.replace(day=1)  # Первый день текущего месяца
    end_date = today
    return start_date, end_date


@login_required
@permission_required(perm='tph_system.view_finstatsmonth', raise_exception=True)
def fin_stats(request):
    stats = FinStatsMonth.objects.all()
    stats_staff = FinStatsStaff.objects.all().select_related('staff')

    # Сохраняем текущие GET-параметры для возможности возврата
    current_filter_params = request.GET.urlencode()

    # Фильтр FinStatsMonth
    stats_filter = FinStatsMonthFilter(request.GET, queryset=stats)
    stats = stats_filter.qs

    # Фильтр FinStatsStaff
    stats_staff_filter = FinStatsStaffFilter(request.GET, queryset=stats_staff)
    stats_staff = stats_staff_filter.qs

    # Пагинатор stats_staff
    paginator_st = Paginator(stats_staff, 10)
    page_number_st = request.GET.get('page')
    page_obj_st = paginator_st.get_page(page_number_st)

    # Код для статистического графика по продажам #
    # ---------------------------------------------------------------------
    # Получение дат из GET-параметров или установка значений по умолчанию
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    except ValueError:
        start_date = None

    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        end_date = None

    # Установка значений по умолчанию при необходимости
    default_start, default_end = get_default_dates()
    start_date = start_date or default_start
    end_date = end_date or default_end

    # Корректировка дат (если end_date раньше start_date)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    # Фильтрация данных по выбранному периоду
    sales_in_period = Sales.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    )

    # Статистика по дням
    daily = (
        sales_in_period
        .annotate(day=TruncDay('date'))
        .values('day')
        .annotate(total=Sum('sum'))
        .order_by('day')
    )

    # Подготовка данных для дневного графика с цветами
    daily_labels = []
    daily_data = []
    daily_colors = []  # Список цветов для каждого столбца

    # Цветовые коды
    BLUE = 'rgba(54, 162, 235, 0.7)'
    ORANGE = 'rgba(255, 159, 64, 0.7)'
    RED = 'rgba(255, 99, 132, 0.7)'

    for entry in daily:
        day = entry['day']
        weekday = day.weekday()  # 0-понедельник, 6-воскресенье

        daily_labels.append(day.strftime("%Y-%m-%d"))
        daily_data.append(float(entry['total']))

        if weekday == 4:  # Пятница
            daily_colors.append(ORANGE)
        elif weekday >= 5:  # Суббота (5) и воскресенье (6)
            daily_colors.append(RED)
        else:
            daily_colors.append(BLUE)

    # Статистика по неделям
    weekly = (
        sales_in_period
        .annotate(week=TruncWeek('date'))
        .values('week')
        .annotate(total=Sum('sum'))
        .order_by('week')
    )

    # Подготовка данных для графиков
    weekly_labels = []
    weekly_data = []
    week_numbers = []  # Добавляем список номеров недель

    for entry in weekly:
        week_start = entry['week']
        week_num = week_start.isocalendar()[1]  # Получаем номер недели ISO
        year = week_start.year

        weekly_labels.append(week_start.strftime("%Y-%m-%d"))
        weekly_data.append(float(entry['total']))
        week_numbers.append(f"{year}-W{week_num:02d}")  # Формат "2023-W43"

    return render(request, 'tph_system/fin_stats/fin_stats.html', {
        'title': 'Финансы - кампания',
        'stats': stats,
        'paginator_st': paginator_st,
        'page_obj_st': page_obj_st,
        'stats_filter': stats_filter,
        'stats_staff_filter': stats_staff_filter,
        'current_filter_params': current_filter_params,
        'daily_labels': daily_labels,
        'daily_data': daily_data,
        'daily_colors': daily_colors,
        'weekly_labels': weekly_labels,
        'weekly_data': weekly_data,
        'week_numbers': week_numbers,
        'start_date': start_date,
        'end_date': end_date
    })


@login_required
@permission_required(perm='tph_system.calculate_finstatsmonth', raise_exception=True)
def fin_stats_calc_view(request):
    if request.method == 'POST':
        form = TimeSelectForm(request.POST)
        if form.is_valid():
            beg = form.cleaned_data['beg_date']
            end = form.cleaned_data['end_date']
            fin_stats_calc(beg, end)
            fin_stats_staff_calc(beg, end)
            return redirect('fin_stats')
    else:
        form = TimeSelectForm()

    return render(request, 'tph_system/fin_stats/fin_stats_calc.html', {
        'title': 'Расчет финансов',
        'form': form
    })


@login_required
@permission_required(perm='tph_system.reports_view', raise_exception=True)
def reports(request):
    auth_user = User.objects.get(id=request.user.id)
    auth_staff = Staff.objects.get(st_username=auth_user)
    try:
        store_staff_working_obj = Store.objects.get(
            name=Schedule.objects.get(date=datetime.now(),
                                      staff_id=auth_staff).store)
    except ObjectDoesNotExist:
        store_staff_working_obj = None

    # Значения по умолчанию
    selected_date = datetime.today()

    if auth_user.has_perm('tph_system.reports_boss_view'):
        selected_store = Store.objects.filter(store_status="Действующая").first()
    elif store_staff_working_obj is not None:
        selected_store = store_staff_working_obj
    else:
        return redirect('main_page')

    # Фильтр даты
    date_filter = ReportsFilter(
        request.GET or {'selected_date': selected_date, 'selected_store': selected_store},
        queryset=Schedule.objects.filter(date=selected_date, store=selected_store)
    )

    # Извлекаем валидную дату из фильтра
    if date_filter.form.is_valid():
        selected_date = date_filter.form.cleaned_data.get('selected_date')
        selected_store = date_filter.form.cleaned_data.get('selected_store')

    cfp_q = {'store': selected_store.id}
    current_filter_params = urllib.parse.urlencode(cfp_q)

    # Данные сотрудников и ролей
    staffs_data = Schedule.objects.filter(store=selected_store, date=selected_date).select_related('staff').order_by(
        'staff')
    # Техника
    tech_data = Tech.objects.filter(store=selected_store)
    tech_count = tech_data.count()
    tech_upd_info = ImplEvents.objects.filter(event_type='Tech_Update', date_created__date=selected_date,
                                              event_message__icontains=selected_store)
    # Расходники
    cons_data = ConsumablesStore.objects.filter(store=selected_store)
    cons_count = cons_data.count()
    cons_upd_info = ImplEvents.objects.filter(event_type='Consumables_Update', date_created__date=selected_date,
                                              event_message__icontains=selected_store)
    # Выччеты ЗП наличными
    wdr = CashWithdrawn.objects.filter(date=selected_date, store=selected_store).select_related('staff')
    # Касса
    sales_data = Sales.objects.filter(date=selected_date, store=selected_store).select_related('staff', 'photographer').order_by('date')
    summary = {'cashbx_all': sales_data.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'],
               'cashbx_park': sales_data.filter(payment_type='Оплата через парк').aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'],
               'cashbx_card': sales_data.filter(payment_type='Карта').aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'],
               'cashbx_cash': sales_data.filter(payment_type='Наличные').aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'],
               'cashbx_qr': sales_data.filter(payment_type='Оплата по QR коду').aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'],
               'cashbx_trans': sales_data.filter(payment_type='Перевод по номеру телефона').aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'],
               'cashbx_orders': sales_data.filter(payment_type='Предоплаченный заказ',
                                                 sale_type__in=['Заказной фотосет', 'Заказ выездной']
                                                 ).aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']
               }
    sales_count = sales_data.count()
    zak_count = sales_data.filter(payment_type='Предоплаченный заказ',
                                  sale_type__in=['Заказной фотосет', 'Заказ выездной']
                                  ).values('sale_type').annotate(zak_cnt=Count('sale_type'))

    if summary['cashbx_all'] is None: summary['cashbx_all'] = 0
    if summary['cashbx_park'] is None: summary['cashbx_park'] = 0
    if summary['cashbx_card'] is None: summary['cashbx_card'] = 0
    if summary['cashbx_cash'] is None: summary['cashbx_cash'] = 0
    if summary['cashbx_qr'] is None: summary['cashbx_qr'] = 0
    if summary['cashbx_trans'] is None: summary['cashbx_trans'] = 0
    if summary['cashbx_orders'] is None: summary['cashbx_orders'] = 0

    # Наличка на точке
    cash_s = CashStore.objects.filter(date=selected_date, store=selected_store)

    # Сверка наличных с утра с прошлым вечером
    cash_date = ''
    try:
        cash_yesterday = CashStore.objects.filter(store=selected_store, date__lte=selected_date)[1:2][0].cash_evn
        cash_date = CashStore.objects.filter(store=selected_store, date__lte=selected_date)[1:2][0].date.strftime("%d.%m")
    except IndexError:
        cash_yesterday = -1

    check_cash = ''
    td_color = -1
    for csh in cash_s:
        if csh.cash_mrn == cash_yesterday:
            check_cash = '-> Сверка ОК'
            td_color = 1
        elif cash_yesterday == -1:
            check_cash = '-> Нет данных для сверки'
            td_color = 2
        else:
            check_cash = f'-> Расхождение! Нал на вечер {cash_date} - {cash_yesterday}'
            td_color = 0

    # Личные кассы фотографов
    if staffs_data.filter(position__in=['Фотограф', 'Видеограф', 'Универсальный фотограф', 'Выездной фотограф']).count() > 1:
        cash_staffs = sales_data.values('photographer__name', 'photographer__f_name').annotate(cash_staff=Sum('sum'))
    else:
        cash_staffs = None

    return render(request, 'tph_system/fin_stats/reports.html', {
        'title': 'Сверка отчетов',
        'staffs_data': staffs_data,
        'date_filter': date_filter,
        'selected_date': selected_date,
        'selected_store': selected_store,
        'tech_data': tech_data,
        'tech_count': tech_count,
        'tech_upd_info': tech_upd_info,
        'cons_data': cons_data,
        'cons_count': cons_count,
        'cons_upd_info': cons_upd_info,
        'wdr': wdr,
        'sales_data': sales_data,
        'summary': summary,
        'sales_count': sales_count,
        'zak_count': zak_count,
        'cash_s': cash_s,
        'check_cash': check_cash,
        'td_color': td_color,
        'cash_staffs': cash_staffs,
        'current_filter_params': current_filter_params
    })


@login_required
def base_fx(request):
    return render(request, 'tph_system/base_my.html', {
        'title': 'Старый базовый шаблон'
    })
