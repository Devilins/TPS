import django_filters
from django_filters import CharFilter

from .models import *


class ConsumablesStoreFilter(django_filters.FilterSet):
    consumable = CharFilter(field_name='consumable', lookup_expr='icontains')  # icontains означает "содержит"

    class Meta:
        model = ConsumablesStore
        fields = ['store', 'consumable']


class StaffFilter(django_filters.FilterSet):
    f_name = CharFilter(field_name='f_name', lookup_expr='icontains')
    name = CharFilter(field_name='name', lookup_expr='icontains')
    o_name = CharFilter(field_name='o_name', lookup_expr='icontains')

    class Meta:
        model = Staff
        fields = ['f_name', 'name', 'o_name', 'date_empl', 'date_dism']


class TechFilter(django_filters.FilterSet):
    name = CharFilter(field_name='name', lookup_expr='icontains')
    serial_num = CharFilter(field_name='serial_num', lookup_expr='icontains')

    class Meta:
        model = Tech
        fields = ['store', 'name', 'serial_num']


class SalesFilter(django_filters.FilterSet):
    class Meta:
        model = Sales
        fields = ['store', 'date', 'staff', 'photographer', 'sale_type', 'sum']


class CashWithdrawnFilter(django_filters.FilterSet):
    class Meta:
        model = CashWithdrawn
        fields = ['store', 'staff', 'date', 'withdrawn']


class SettingsFilter(django_filters.FilterSet):
    param = CharFilter(field_name='param', lookup_expr='icontains')
    param_f_name = CharFilter(field_name='param_f_name', lookup_expr='icontains')

    class Meta:
        model = Settings
        fields = ['param', 'param_f_name']


class SalaryFilter(django_filters.FilterSet):
    salary_sum = CharFilter(field_name='salary_sum', lookup_expr='icontains')

    class Meta:
        model = Salary
        fields = ['store', 'staff', 'date', 'salary_sum']
