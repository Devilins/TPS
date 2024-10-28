import datetime
import math
import re

from django.core.exceptions import ValidationError
from django.forms import ModelForm, TextInput, DateInput, NumberInput, Select, Textarea, Form, modelformset_factory, \
    BaseForm
from django import forms

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
        fields = ['store', 'consumable', 'cons_short', 'count']

        labels = {
            'consumable': 'Расходник',
            'cons_short': 'Короткое имя',
            'store': 'Точка',
            'count': 'Количество'
        }

        widgets = {
            "consumable": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Расходник'
            }),
            "cons_short": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Короткое имя'
            }),
            "store": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Точка'
            }),
            "count": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Количество'
            })
        }

    def clean_count(self):
        count = self.cleaned_data.get('count')
        if count < 0:
            raise ValidationError("Количество не может быть отрицательным.")
        return count


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
        self.fields['photographer'].empty_label = "Выберите сотрудника"
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
            'photo_count': 'Кол-во фото / часов съемки',
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
                'placeholder': 'Укажите дату'
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
            "comment": Textarea(attrs={
                'class': 'form-control',
                'rows': '1'
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

    def clean_sum(self):
        sum = self.cleaned_data["sum"]
        if sum <= 0:
            raise ValidationError('Сумма должна быть положительной')
        return sum

    def clean_photo_count(self):
        count = self.cleaned_data["photo_count"]
        if count <= 0:
            raise ValidationError('Кол-во фото должно быть положительным')
        return count

    def clean(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        photographer = cleaned_data.get("photographer")
        date = cleaned_data.get("date")
        store = cleaned_data.get("store")
        photo_count = cleaned_data.get("photo_count")
        sale_type = cleaned_data.get("sale_type")

        if not Schedule.objects.filter(staff=staff, date=date, store=store).exists():
            raise ValidationError('Администратор не работает на выбранной точке в указанную дату')

        if not Schedule.objects.filter(staff=photographer, date=date, store=store).exists():
            raise ValidationError('Фотограф не работает на выбранной точке в указанную дату')

        try:
            if sale_type == 'Печать 15x20':
                cons_type = 'Печать A4'
                p_count = math.ceil(photo_count / 2)
            else:
                cons_type = sale_type
                p_count = photo_count

            cons = ConsumablesStore.objects.get(cons_short=cons_type, store=store)
            if p_count > cons.count:
                raise ValidationError(
                    f"Расходников не хватит, чтобы продать {photo_count} фотографий. На точке {cons.count} расходников для {sale_type}")
        except ConsumablesStore.DoesNotExist:
            pass


class RefsAndTipsForm(ModelForm):
    class Meta:
        model = RefsAndTips
        fields = ['tip', 'refs']

        labels = {
            'tip': 'Информация',
            'refs': 'Ссылка'
        }

        widgets = {
            "tip": Textarea(attrs={
                'class': 'form-control',
                'rows': '3',
                'placeholder': 'Информация'
            }),
            "refs": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ссылка'
            })
        }


class CashWithdrawnForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].empty_label = "Выберите сотрудника"
        self.fields['store'].empty_label = "Выберите точку"

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

    def clean_store(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        store = cleaned_data.get("store")
        date = cleaned_data.get("date")

        if not Schedule.objects.filter(staff=staff, date=date, store=store).exists():
            raise ValidationError('Сотрудник не работает на выбранной точке в указанную дату')

    def clean_withdrawn(self):
        withdrawn = self.cleaned_data["withdrawn"]
        if withdrawn <= 0:
            raise ValidationError('Сумма должна быть положительной')
        return withdrawn


class SettingsForm(ModelForm):
    class Meta:
        model = Settings
        fields = ['param', 'value', 'param_f_name']

        labels = {
            'param': 'Параметр',
            'value': 'Значение',
            'param_f_name': 'Описание'
        }

        widgets = {
            "param": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Параметр'
            }),
            "value": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Значение'
            }),
            "param_f_name": Textarea(attrs={
                'class': 'form-control',
                'rows': '3',
                'placeholder': 'Описание'
            })
        }


class SalaryForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].empty_label = "Выберите сотрудника"
        self.fields['store'].empty_label = "Выберите точку"

    class Meta:
        model = Salary
        fields = ['store', 'staff', 'date', 'salary_sum']

        labels = {
            'store': 'Точка',
            'staff': 'Сотрудник',
            'date': 'Дата',
            'salary_sum': 'Зарплата'
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
            "salary_sum": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Зарплата'
            })
        }

    def clean_store(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        store = cleaned_data.get("store")
        date = cleaned_data.get("date")

        if not Schedule.objects.filter(staff=staff, date=date, store=store).exists():
            raise ValidationError('Сотрудник не работает на выбранной точке в указанную дату')

    def clean_salary_sum(self):
        salary = self.cleaned_data["salary_sum"]
        if salary <= 0:
            raise ValidationError('Сумма зарплаты должна быть положительной')
        return salary


class PositionSelectForm(ModelForm):
    class Meta:
        model = Schedule
        fields = ['position']

        labels = {
            'position': 'Роль'
        }

        widgets = {
            "position": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Роль',
                'label': 'Роль'
            })
        }


PositionSelectFormSet = modelformset_factory(
    Schedule,
    form=PositionSelectForm,
    extra=0
)


class TimeSelectForm(Form):
    beg_date = forms.DateField(widget=FengyuanChenDatePickerInput(attrs={
        'class': 'form-control',
        'placeholder': 'Дата начала'
    }),
        label='Дата начала')
    end_date = forms.DateField(widget=FengyuanChenDatePickerInput(attrs={
        'class': 'form-control',
        'placeholder': 'Дата окончания'
    }),
        label='Дата окончания')

    def clean_end_date(self):
        end_date = self.cleaned_data["end_date"]
        if end_date > datetime.date.today():
            raise ValidationError('Дата окончания не может быть в будущем')
        return end_date

    def clean_beg_date(self):
        beg_date = self.cleaned_data["beg_date"]
        if beg_date < datetime.date(2024, 1, 1):
            raise ValidationError('Дата начала не может быть раньше 2024 года')
        return beg_date

    def clean(self):
        cleaned_data = super().clean()
        beg_date = cleaned_data.get("beg_date")
        end_date = cleaned_data.get("end_date")
        if end_date is not None:
            if beg_date > end_date:
                raise ValidationError('Начало периода не может быть больше окончания')
