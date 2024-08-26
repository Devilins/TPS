import datetime
import re

from django.core.exceptions import ValidationError
from django.forms import ModelForm, TextInput, DateInput, NumberInput, Select

from .models import *


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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['st_username'].empty_label = "Выберите Логин"

    class Meta:
        model = Staff
        fields = ['f_name', 'name', 'o_name', 'date_empl', 'date_dism', 'st_username']

        labels = {
            'f_name': 'Фамилия',
            'name': 'Имя',
            'o_name': 'Отчество',
            'date_empl': 'Дата найма',
            'date_dism': 'Дата увольнения',
            'st_username': 'Логин'
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
            }),
            "st_username": Select(attrs={
                'class': 'form-select',
                'placeholder': 'Логин'
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


class ScheduleForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].empty_label = "Выберите сотрудника"
        self.fields['store'].empty_label = "Выберите точку"

    class Meta:
        model = Schedule
        fields = ['staff', 'store', 'position', 'date']

        labels = {
            'staff': 'Сотрудник',
            'store': 'Точка',
            'position': 'Должность в смене',
            'date': 'Дата смены'
        }

        widgets = {
            "staff": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Сотрудник',
                'label': 'Сотрудник'
            }),
            "store": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Точка',
                'label': 'Точка'
            }),
            "position": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Должность в смене'
            }),
            "date": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата смены'
            })
        }


class SalesForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].empty_label = "Выберите сотрудника"
        self.fields['store'].empty_label = "Выберите точку"
        self.fields['payment_type'].empty_label = "Тип оплаты"

    class Meta:
        model = Sales
        fields = ['store', 'date', 'staff', 'photographer', 'sale_type', 'photo_count',
                  'payment_type', 'sum', 'cl_email', 'cl_phone', 'comment']

        labels = {
            'store': 'Точка',
            'date': 'Дата смены',
            'staff': 'Администратор',
            'photographer': 'Фотограф',
            'sale_type': 'Что продали',
            'payment_type': 'Тип оплаты',
            'sum': 'Сумма',
            'photo_count': 'Количество фотографий',
            'cl_email': 'Email клиента',
            'cl_phone': 'Телефон клиента',
            'comment': 'Комментарий'
        }

        widgets = {
            "store": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Точка',
                'label': 'Точка'
            }),
            "date": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата продажи'
            }),
            "staff": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Администратор',
                'label': 'Администратор'
            }),
            "photographer": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Фотограф',
                'label': 'Фотограф'
            }),
            "sale_type": Select(attrs={
                'class': 'form-select',
                'placeholder': 'Что продали'
            }),
            "payment_type": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Тип оплаты',
                'label': 'Тип оплаты'
            }),
            "sum": NumberInput(attrs={
                'class': 'form-control',
            }),
            "photo_count": NumberInput(attrs={
                'class': 'form-control',
            }),
            "cl_email": TextInput(attrs={
                'class': 'form-control',
                'type': 'email',
                'placeholder': 'mail@ya.ru'
            }),
            "cl_phone": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Цифрами 89...'
            }),
            "comment": TextInput(attrs={
                'class': 'form-control',
            })
        }

    def clean_date(self):
        f_date = self.cleaned_data["date"]
        if f_date > datetime.date.today():
            raise ValidationError('Продажа не может быть в будущем')
        return f_date

    def clean_cl_email(self):
        cl_email = self.cleaned_data["cl_email"]
        if not re.match(r"[^@]+@[^@]+\.[^@]+", cl_email):
            raise ValidationError('Неверный формат Email')
        return cl_email

    def clean_cl_phone(self):
        cl_phone = self.cleaned_data["cl_phone"]
        if len(cl_phone) != 11:
            raise ValidationError('Неверный формат телефона (кол-во цифр должно быть 11)')
        return cl_phone

    def clean(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        photographer = cleaned_data.get("photographer")
        date = cleaned_data.get("date")
        store = cleaned_data.get("store")

        if not Schedule.objects.filter(staff=staff, date=date, store=store).exists():
            raise ValidationError('Администратор не работает на выбранной точке в указанную дату')

        if not Schedule.objects.filter(staff=photographer, date=date, store=store).exists():
            raise ValidationError('Фотограф не работает на выбранной точке в указанную дату')


class RefsAndTipsForm(ModelForm):
    class Meta:
        model = RefsAndTips
        fields = ['tip', 'refs']

        labels = {
            'tip': 'Информация',
            'refs': 'Ссылка'
        }

        widgets = {
            "tip": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Информация'
            }),
            "refs": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ссылка'
            })
        }


class CashWithdrawnForm(ModelForm):
    class Meta:
        model = CashWithdrawn
        fields = ['store', 'staff', 'date', 'withdrawn']

        labels = {
            'store': 'Точка',
            'staff': 'Сотрудник',
            'date': 'Дата',
            'withdrawn': 'Забрали наличными'
        }

        widgets = {
            "store": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Точка',
                'label': 'Точка'
            }),
            "staff": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Сотрудник',
                'label': 'Сотрудник'
            }),
            "date": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата'
            }),
            "withdrawn": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Сколько забрали наличными'
            })
        }
