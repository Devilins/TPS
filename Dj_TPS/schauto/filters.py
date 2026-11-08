import django_filters
from django.forms import Select, TextInput

from tph_system.forms import FengyuanChenDatePickerInput

from .models import PhotoOrder, Route, Venue


class VenueFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(
        field_name='name', lookup_expr='icontains',
        widget=TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Название центра'}))
    brand = django_filters.ChoiceFilter(
        choices=Venue.BRAND_CHOICES, empty_label="Пусто",
        widget=Select(attrs={'class': 'form-select form-select-sm', 'aria-label': 'Бренд'}))
    is_active = django_filters.ChoiceFilter(
        choices=(('1', 'Участвуют'), ('0', 'Не участвуют')), empty_label="Пусто", method='filter_is_active',
        widget=Select(attrs={'class': 'form-select form-select-sm', 'aria-label': 'Участие в планировании'}))

    def filter_is_active(self, queryset, name, value):
        return queryset.filter(is_active=(value == '1'))

    class Meta:
        model = Venue
        fields = ['name', 'brand', 'is_active']


class RouteFilter(django_filters.FilterSet):
    from_venue = django_filters.ModelChoiceFilter(
        queryset=Venue.objects.all(), empty_label="Пусто",
        widget=Select(attrs={'class': 'form-select form-select-sm', 'aria-label': 'Откуда'}))
    to_venue = django_filters.ModelChoiceFilter(
        queryset=Venue.objects.all(), empty_label="Пусто",
        widget=Select(attrs={'class': 'form-select form-select-sm', 'aria-label': 'Куда'}))

    class Meta:
        model = Route
        fields = ['from_venue', 'to_venue']


class PhotoOrderFilter(django_filters.FilterSet):
    venue = django_filters.ModelChoiceFilter(
        queryset=Venue.objects.all(), empty_label="Пусто",
        widget=Select(attrs={'class': 'form-select form-select-sm', 'aria-label': 'Центр'}))
    brand = django_filters.ChoiceFilter(
        choices=PhotoOrder.SOURCE_BRANDS, empty_label="Пусто",
        widget=Select(attrs={'class': 'form-select form-select-sm', 'aria-label': 'Таблица'}))
    status = django_filters.ChoiceFilter(
        choices=PhotoOrder.STATUS_CHOICES, empty_label="Кроме пропавших",
        widget=Select(attrs={'class': 'form-select form-select-sm', 'aria-label': 'Статус'}))
    date_from = django_filters.DateFilter(
        label="Даты с", field_name='date', lookup_expr='gte',
        widget=FengyuanChenDatePickerInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Даты с'}))
    date_by = django_filters.DateFilter(
        label="Даты по", field_name='date', lookup_expr='lte',
        widget=FengyuanChenDatePickerInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Даты по'}))

    class Meta:
        model = PhotoOrder
        fields = ['venue', 'brand', 'status', 'date_from', 'date_by']
