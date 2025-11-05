from datetime import timedelta

import django_filters
from django_filters import CharFilter, ChoiceFilter
from django.forms import Select, NumberInput

from .forms import FengyuanChenDatePickerInput
from .funcs import dt_format
from .models import *


class ConsumablesStoreFilter(django_filters.FilterSet):
    consumable = CharFilter(field_name='consumable', lookup_expr='icontains')  # icontains означает "содержит"
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая")
    )

    class Meta:
        model = ConsumablesStore
        fields = ['store', 'consumable']


class StaffFilter(django_filters.FilterSet):
    f_name = CharFilter(field_name='f_name', lookup_expr='icontains')
    name = CharFilter(field_name='name', lookup_expr='icontains')
    o_name = CharFilter(field_name='o_name', lookup_expr='icontains')

    class Meta:
        model = Staff
        fields = ['f_name', 'name', 'o_name', 'date_empl', 'date_dism', 'dism_status']


class TechFilter(django_filters.FilterSet):
    name = CharFilter(field_name='name', lookup_expr='icontains')
    serial_num = CharFilter(field_name='serial_num', lookup_expr='icontains')
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.exclude(store_status="Закрытая")
    )

    class Meta:
        model = Tech
        fields = ['store', 'name', 'serial_num']


class SalesFilter(django_filters.FilterSet):
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает")
    )
    photographer = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает")
    )
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая")
    )
    date_from = django_filters.DateFilter(
        label="Даты с",
        field_name='date',
        lookup_expr='gte',
        widget=FengyuanChenDatePickerInput
    )
    date_by = django_filters.DateFilter(
        label="Даты по",
        field_name='date',
        lookup_expr='lte',
        widget=FengyuanChenDatePickerInput
    )

    class Meta:
        model = Sales
        fields = ['store', 'date', 'staff', 'photographer', 'sale_type', 'payment_type', 'sum']


class CashWithdrawnFilter(django_filters.FilterSet):
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает")
    )
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая")
    )
    date_from = django_filters.DateFilter(
        label="Даты с",
        field_name='date',
        lookup_expr='gte',
        widget=FengyuanChenDatePickerInput
    )
    date_by = django_filters.DateFilter(
        label="Даты по",
        field_name='date',
        lookup_expr='lte',
        widget=FengyuanChenDatePickerInput
    )
    week_beg_rec = django_filters.DateFilter(
        label="Первый день недели ЗП:",
        field_name='week_beg_rec',
        widget=FengyuanChenDatePickerInput
    )

    class Meta:
        model = CashWithdrawn
        fields = ['store', 'staff', 'date', 'withdrawn', 'week_beg_rec']


class SettingsFilter(django_filters.FilterSet):
    param = CharFilter(field_name='param', lookup_expr='icontains')
    param_f_name = CharFilter(field_name='param_f_name', lookup_expr='icontains')

    class Meta:
        model = Settings
        fields = ['param', 'param_f_name']


class SalaryFilter(django_filters.FilterSet):
    salary_sum = CharFilter(field_name='salary_sum', lookup_expr='icontains')
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает")
    )
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая")
    )
    date_from = django_filters.DateFilter(
        label="Даты с",
        field_name='date',
        lookup_expr='gte',
        widget=FengyuanChenDatePickerInput  # (attrs={'class': 'form-control form-control-sm'})
    )
    date_by = django_filters.DateFilter(
        label="Даты по",
        field_name='date',
        lookup_expr='lte',
        widget=FengyuanChenDatePickerInput
    )

    class Meta:
        model = Salary
        fields = ['store', 'staff', 'date', 'salary_sum']


class SalaryWeeklyFilter(django_filters.FilterSet):
    week_begin = django_filters.DateFilter(widget=FengyuanChenDatePickerInput)
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает")
    )

    class Meta:
        model = SalaryWeekly
        fields = ['staff', 'week_begin', 'paid_out']


class ImplEventsFilter(django_filters.FilterSet):
    event_message = CharFilter(field_name='event_message', lookup_expr='icontains')

    class Meta:
        model = ImplEvents
        fields = ['event_message']


class FinStatsMonthFilter(django_filters.FilterSet):
    date = django_filters.DateFilter(widget=FengyuanChenDatePickerInput)

    class Meta:
        model = FinStatsMonth
        fields = ['date']


class FinStatsStaffFilter(django_filters.FilterSet):
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает")
    )

    class Meta:
        model = FinStatsStaff
        fields = ['staff', 'date']


class MainPageFilter(django_filters.FilterSet):
    selected_date = django_filters.DateFilter(
        label="Выберите дату",
        widget=FengyuanChenDatePickerInput(attrs={
                'class': 'form-control'
            }),
        initial=datetime.today()
    )

    class Meta:
        model = Schedule
        fields = []


class ReportsFilter(django_filters.FilterSet):
    selected_date = django_filters.DateFilter(
        label="Дата",
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control'
        }),
        initial=datetime.today()
    )
    selected_store = django_filters.ModelChoiceFilter(
        label="Точка",
        widget=Select(attrs={
            'class': 'form-select',
            'aria-label': 'Точка',
            'label': 'Точка'
        }),
        initial=Store.objects.filter(store_status="Действующая").first(),
        queryset=Store.objects.filter(store_status="Действующая")
    )

    class Meta:
        model = Schedule
        fields = ['store']


class CheckReportsFilter(django_filters.FilterSet):
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая")
    )
    date = django_filters.DateFilter(widget=FengyuanChenDatePickerInput)

    class Meta:
        model = CheckReports
        fields = ['store', 'date', 'check_status']
