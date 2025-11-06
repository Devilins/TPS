from datetime import timedelta

import django_filters
from django_filters import CharFilter, ChoiceFilter
from django.forms import Select, NumberInput, TextInput

from .forms import FengyuanChenDatePickerInput
from .funcs import dt_format
from .models import *


class ConsumablesStoreFilter(django_filters.FilterSet):
    consumable = CharFilter(
        field_name='consumable',
        lookup_expr='icontains',
        widget=TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Расходник'
        })
    )
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Точка',
            'label': 'Точка'
        })
    )

    class Meta:
        model = ConsumablesStore
        fields = ['store', 'consumable']


class StaffFilter(django_filters.FilterSet):
    f_name = CharFilter(
        field_name='f_name',
        lookup_expr='icontains',
        widget=TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Фамилия'
        })
    )
    name = CharFilter(
        field_name='name',
        lookup_expr='icontains',
        widget=TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Имя'
        })
    )
    o_name = CharFilter(
        field_name='o_name',
        lookup_expr='icontains',
        widget=TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Отчество'
        })
    )
    date_empl = django_filters.DateFilter(
        field_name='date_empl',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Дата найма'
        })
    )
    date_dism = django_filters.DateFilter(
        field_name='date_dism',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Дата увольнения'
        })
    )
    dism_status = django_filters.ChoiceFilter(
        field_name='dism_status',
        choices=Staff.SLCT_DISM_STATUS,
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Статус',
            'label': 'Статус'
        }))

    class Meta:
        model = Staff
        fields = ['f_name', 'name', 'o_name', 'date_empl', 'date_dism', 'dism_status']


class TechFilter(django_filters.FilterSet):
    name = CharFilter(field_name='name', lookup_expr='icontains',
                      widget=TextInput(attrs={
                          'class': 'form-control form-control-sm',
                          'placeholder': 'Название техники'
                      })
                      )
    serial_num = CharFilter(field_name='serial_num', lookup_expr='icontains',
                            widget=NumberInput(attrs={
                                'class': 'form-control form-control-sm',
                                'placeholder': 'Серийный номер'
                            })
                            )
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.exclude(store_status="Закрытая"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Точка',
            'label': 'Точка'
        })
    )

    class Meta:
        model = Tech
        fields = ['store', 'name', 'serial_num']


class SalesFilter(django_filters.FilterSet):
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Администратор',
            'label': 'Администратор'
        })
    )
    photographer = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Фотограф',
            'label': 'Фотограф'
        })
    )
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Точка',
            'label': 'Точка'
        })
    )
    date_from = django_filters.DateFilter(
        label="Даты с",
        field_name='date',
        lookup_expr='gte',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Даты с'
        })
    )
    date_by = django_filters.DateFilter(
        label="Даты по",
        field_name='date',
        lookup_expr='lte',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Даты по'
        })
    )
    sale_type = django_filters.ChoiceFilter(
        field_name='sale_type',
        choices=Sales.SLCT_ST,
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Что продали',
            'label': 'Что продали'
        })
    )
    payment_type = django_filters.ChoiceFilter(
        field_name='payment_type',
        choices=Sales.SLCT_PAYMENT,
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Тип оплаты',
            'label': 'Тип оплаты'
        })
    )
    sum = django_filters.NumberFilter(
        lookup_expr='icontains',
        widget=NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Сумма'
        })
    )

    class Meta:
        model = Sales
        fields = ['store', 'date', 'staff', 'photographer', 'sale_type', 'payment_type', 'sum']


class CashWithdrawnFilter(django_filters.FilterSet):
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'id': "floatingStaff",
            'aria-label': 'Сотрудник',
            'label': 'Сотрудник'
        })
    )
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Точка',
            'label': 'Точка'
        })
    )
    date_from = django_filters.DateFilter(
        label="Даты с",
        field_name='date',
        lookup_expr='gte',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Даты с'
        })
    )
    date_by = django_filters.DateFilter(
        label="Даты по",
        field_name='date',
        lookup_expr='lte',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Даты по'
        })
    )
    week_beg_rec = django_filters.DateFilter(
        label="Первый день недели ЗП",
        field_name='week_beg_rec',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Первый день недели ЗП'
        })
    )
    withdrawn = django_filters.NumberFilter(
        lookup_expr='icontains',
        widget=NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Сумма'
        })
    )

    class Meta:
        model = CashWithdrawn
        fields = ['store', 'staff', 'date', 'withdrawn', 'week_beg_rec']


class SettingsFilter(django_filters.FilterSet):
    param = CharFilter(
        field_name='param',
        lookup_expr='icontains',
        widget=TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Параметр'
        })
    )
    param_f_name = CharFilter(
        field_name='param_f_name',
        lookup_expr='icontains',
        widget=TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Описание'
        })
    )

    class Meta:
        model = Settings
        fields = ['param', 'param_f_name']


class SalaryFilter(django_filters.FilterSet):
    salary_sum = CharFilter(
        field_name='salary_sum',
        lookup_expr='icontains',
        widget=NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Зарплата'
        })
    )
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Сотрудник',
            'label': 'Сотрудник'
        })
    )
    store = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Точка',
            'label': 'Точка'
        })
    )
    date_from = django_filters.DateFilter(
        label="Даты с",
        field_name='date',
        lookup_expr='gte',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Даты с'
        })
    )
    date_by = django_filters.DateFilter(
        label="Даты по",
        field_name='date',
        lookup_expr='lte',
        widget=FengyuanChenDatePickerInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Даты по'
        })
    )

    class Meta:
        model = Salary
        fields = ['store', 'staff', 'date', 'salary_sum']


class SalaryWeeklyFilter(django_filters.FilterSet):
    week_begin = django_filters.DateFilter(widget=FengyuanChenDatePickerInput(attrs={
        'class': 'form-control form-control-sm',
        'id': "floatingWB",
        'placeholder': 'Дата начала недели'
    }))
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'id': "floatingStaff",
            'aria-label': 'Сотрудник',
            'label': 'Сотрудник'
        })
    )
    paid_out = django_filters.ChoiceFilter(
        field_name='paid_out',
        choices=SalaryWeekly.SLCT_PAID,
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'id': "floatingPO",
            'aria-label': 'Выплачено',
            'label': 'Выплачено'
        }))

    class Meta:
        model = SalaryWeekly
        fields = ['staff', 'week_begin', 'paid_out']


class ImplEventsFilter(django_filters.FilterSet):
    event_message = CharFilter(field_name='event_message', lookup_expr='icontains')

    class Meta:
        model = ImplEvents
        fields = ['event_message']


class FinStatsMonthFilter(django_filters.FilterSet):
    date = django_filters.DateFilter(widget=FengyuanChenDatePickerInput(attrs={
        'class': 'form-control form-control-sm',
        'placeholder': 'Отчетный месяц'
    }))

    class Meta:
        model = FinStatsMonth
        fields = ['date']


class FinStatsStaffFilter(django_filters.FilterSet):
    staff = django_filters.ModelChoiceFilter(
        queryset=Staff.objects.filter(dism_status="Работает"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Сотрудник',
            'label': 'Сотрудник'
        })
    )
    date = django_filters.DateFilter(widget=FengyuanChenDatePickerInput(attrs={
        'class': 'form-control form-control-sm',
        'placeholder': 'Отчетный месяц'
    }))

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
        queryset=Store.objects.filter(store_status="Действующая"),
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Точка',
            'label': 'Точка'
        })
    )
    date = django_filters.DateFilter(widget=FengyuanChenDatePickerInput(attrs={
        'class': 'form-control form-control-sm',
        'placeholder': 'Дата'
    }))
    check_status = django_filters.ChoiceFilter(
        field_name='check_status',
        choices=CheckReports.SLCT_CHECK_STATUS,
        empty_label="Пусто",
        widget=Select(attrs={
            'class': 'form-select form-select-sm',
            'aria-label': 'Статус проверки',
            'label': 'Статус проверки'
        }))

    class Meta:
        model = CheckReports
        fields = ['store', 'date', 'check_status']
