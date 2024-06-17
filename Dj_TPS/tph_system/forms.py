import datetime

from django.core.exceptions import ValidationError

from .models import *
from django.forms import ModelForm, TextInput, DateInput, NumberInput, ModelChoiceField, Select


class FengyuanChenDatePickerInput(DateInput):
    template_name = 'widgets/fengyuanchen_datepicker.html'


class StoreForm(ModelForm):
    class Meta:
        model = Store
        fields = ['name', 'short_name']

        labels = {
            'name': 'Полное наименование',
            'short_name': 'Сокращение'
        }

        widgets = {
            "name": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Полное наименование'
            }),
            "short_name": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Сокращение'
            })
        }


class StaffForm(ModelForm):
    class Meta:
        model = Staff
        fields = ['f_name', 'name', 'o_name', 'date_empl', 'date_dism']

        labels = {
            'f_name': 'Фамилия',
            'name': 'Имя',
            'o_name': 'Отчество',
            'date_empl': 'Дата найма',
            'date_dism': 'Дата увольнения'
        }

        widgets = {
            "f_name": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Фамилия'
            }),
            "name": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Имя'
            }),
            "o_name": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Отчество'
            }),
            "date_empl": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата найма'
            }),
            "date_dism": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата увольнения'
            })
        }


class ConsStoreForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['store'].empty_label = "Выберите точку"

    class Meta:
        model = ConsumablesStore
        fields = ['consumable', 'store', 'count', 'change_data']

        labels = {
            'consumable': 'Расходник',
            'store': 'Точка',
            'count': 'Количество',
            'change_data': 'Дата изменения данных'
        }

        widgets = {
            "consumable": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Расходник'
            }),
            "store": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Точка'
            }),
            "count": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Количество'
            }),
            "change_data": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата изменения данных'
            })
        }


class TechForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['store'].empty_label = "Выберите точку"

    class Meta:
        model = Tech
        fields = ['store', 'name', 'serial_num', 'count', 'date_buy', 'warranty_date']

        labels = {
            'store': 'Точка',
            'name': 'Название техники',
            'serial_num': 'Серийный номер',
            'count': 'Количество',
            'date_buy': 'Дата покупки',
            'warranty_date': 'Дата окончания гарантии'
        }

        widgets = {
            "store": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Точка',
                'label': 'Точка'
            }),
            "name": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Название техники'
            }),
            "serial_num": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Серийный номер'
            }),
            "count": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Количество'
            }),
            "date_buy": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата покупки'
            }),
            "warranty_date": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата окончания гарантии'
            })
        }

    def clean_date_buy(self):
        date_buy = self.cleaned_data["date_buy"]
        if date_buy > datetime.date.today():
            raise ValidationError('Дата не может быть в будущем')
        return date_buy
