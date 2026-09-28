from django import forms

from tph_system.forms import FengyuanChenDatePickerInput
from tph_system.models import Store

from .models import ReportUpload


class ReportUploadForm(forms.ModelForm):
    class Meta:
        model = ReportUpload
        fields = ["location", "report_date", "photo"]
        widgets = {
            "location": forms.Select(attrs={"class": "form-select"}),
            "report_date": FengyuanChenDatePickerInput(attrs={
                "class": "form-control", "placeholder": "Дата отчёта",
            }),
            "photo": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }
        labels = {
            "location": "Точка",
            "report_date": "Дата отчёта",
            "photo": "Фото бланка",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # закрытые/технические точки (в т.ч. Бигвол) — вне сверки отчётов
        self.fields["location"].queryset = Store.objects.filter(store_status="Действующая")

    def clean_photo(self):
        photo = self.cleaned_data["photo"]
        if photo.size > 15 * 1024 * 1024:
            raise forms.ValidationError("Файл больше 15МБ — скорее всего, это не то фото.")
        return photo
