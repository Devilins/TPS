import django_filters
from django_filters import CharFilter

from .models import *


class ConsumablesStoreFilter(django_filters.FilterSet):
    consumable = CharFilter(field_name='consumable', lookup_expr='icontains')  # icontains означает "содержит"


    class Meta:
        model = ConsumablesStore
        fields = ['store', 'consumable']
