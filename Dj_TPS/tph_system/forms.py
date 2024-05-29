from .models import *
from django.forms import ModelForm, TextInput, DateInput, NumberInput, ModelChoiceField, Select


class FengyuanChenDatePickerInput(DateInput):
    template_name = 'widgets/fengyuanchen_datepicker.html'


class StoreForm(ModelForm):
    class Meta:
        model = Store
        fields = ['name', 'short_name']

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
        fields = ['f_name', 'name', 'o_name', 'date_empl']

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
            })
        }


class ConsStoreForm(ModelForm):

    class Meta:
        model = ConsumablesStore
        fields = ['consumable', 'store', 'count', 'change_data']

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
