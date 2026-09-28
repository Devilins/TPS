import django_filters
from django.forms import Select

from tph_system.forms import FengyuanChenDatePickerInput
from tph_system.models import Store

from .models import ReportUpload


class ReportUploadFilter(django_filters.FilterSet):
    location = django_filters.ModelChoiceFilter(
        queryset=Store.objects.filter(store_status="Действующая"),
        empty_label="Пусто",
        widget=Select(attrs={
            "class": "form-select form-select-sm",
            "aria-label": "Точка",
            "label": "Точка",
        })
    )
    report_date = django_filters.DateFilter(widget=FengyuanChenDatePickerInput(attrs={
        "class": "form-control form-control-sm",
        "placeholder": "Дата отчёта",
    }))
    status = django_filters.ChoiceFilter(
        field_name="status",
        choices=ReportUpload.STATUS_CHOICES,
        empty_label="Пусто",
        widget=Select(attrs={
            "class": "form-select form-select-sm",
            "aria-label": "Статус",
            "label": "Статус",
        })
    )

    class Meta:
        model = ReportUpload
        fields = ["location", "report_date", "status"]
