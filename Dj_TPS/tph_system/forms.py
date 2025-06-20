from datetime import datetime
import math
import re

from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db.models import Sum
from django.forms import ModelForm, TextInput, DateInput, NumberInput, Select, Textarea, Form, modelformset_factory, \
    CheckboxInput
from django import forms

from .models import *


class FengyuanChenDatePickerInput(DateInput):
    template_name = 'widgets/fengyuanchen_datepicker.html'


class StoreForm(ModelForm):
    class Meta:
        model = Store
        fields = ['name', 'short_name', 'store_status']

        labels = {
            'name': 'Полное наименование',
            'short_name': 'Сокращение',
            'store_status': 'Статус'
        }

        widgets = {
            "name": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Полное наименование'
            }),
            "short_name": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Сокращение'
            }),
            "store_status": Select(attrs={
                'class': 'form-select',
                'placeholder': 'Статус'
            })
        }


class StaffForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['st_username'].empty_label = "Выберите Логин"
        self.fields['dism_status'].empty_label = "Выберите статус"

    class Meta:
        model = Staff
        fields = ['f_name', 'name', 'o_name', 'date_empl', 'date_dism', 'dism_status', 'st_username']

        labels = {
            'f_name': 'Фамилия',
            'name': 'Имя',
            'o_name': 'Отчество',
            'date_empl': 'Дата найма',
            'date_dism': 'Дата увольнения',
            'dism_status': 'Статус',
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
            "dism_status": Select(attrs={
                'class': 'form-select',
                'placeholder': 'Статус'
            }),
            "st_username": Select(attrs={
                'class': 'form-select',
                'placeholder': 'Логин'
            })
        }


class ConsStoreForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['store'].queryset = Store.objects.filter(store_status="Действующая")
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
        self.fields['store'].queryset = Store.objects.exclude(store_status="Закрытая")
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
        if date_buy > datetime.today().date():
            raise ValidationError('Дата не может быть в будущем')
        return date_buy


class ScheduleForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].empty_label = "Выберите сотрудника"
        self.fields['store'].queryset = Store.objects.filter(store_status="Действующая")
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
        self.fields['staff'].queryset = Staff.objects.filter(dism_status="Работает")
        self.fields['staff'].empty_label = "Выберите сотрудника"
        self.fields['photographer'].queryset = Staff.objects.filter(dism_status="Работает")
        self.fields['photographer'].empty_label = "Выберите сотрудника"
        self.fields['store'].queryset = Store.objects.filter(store_status="Действующая")
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
        if f_date > datetime.today().date():
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
        payment_type = cleaned_data.get("payment_type")

        if payment_type == 'Предоплаченный заказ' and photo_count > 8:
            raise ValidationError(
                f'Для заказного фотосета нужно указывать кол-во часов, а не кол-во фото. Вряд-ли вы снимали заказ {photo_count} часов.')

        if not Schedule.objects.filter(staff=staff, date=date, store=store).exists():
            raise ValidationError('Администратор не работает на выбранной точке в указанную дату')

        if not Schedule.objects.filter(staff=photographer, date=date, store=store).exists():
            raise ValidationError('Фотограф не работает на выбранной точке в указанную дату')

        try:
            if sale_type in ('Вин. магн.', 'Ср. магн.', 'Бол. магн.'):
                cons = ConsumablesStore.objects.get(cons_short=sale_type, store=store)
                if photo_count > cons.count:
                    raise ValidationError(
                        f"Расходников не хватит, чтобы продать {photo_count} фотографий. На точке {cons.count} расходников для {cons.consumable}")
        except ConsumablesStore.DoesNotExist:
            pass


class RefsAndTipsForm(ModelForm):
    class Meta:
        model = RefsAndTips
        fields = ['title', 'tip', 'refs']

        labels = {
            'title': 'Заголовок',
            'tip': 'Информация',
            'refs': 'Ссылка'
        }

        widgets = {
            "title": Select(attrs={
                'class': 'form-select',
                'placeholder': 'Заголовок'
            }),
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
        self.fields['staff'].queryset = Staff.objects.filter(dism_status="Работает")
        self.fields['staff'].empty_label = "Выберите сотрудника"
        self.fields['store'].queryset = Store.objects.filter(store_status="Действующая")
        self.fields['store'].empty_label = "Выберите точку"

    class Meta:
        model = CashWithdrawn
        fields = ['store', 'staff', 'date', 'withdrawn', 'week_beg_rec', 'comment']

        labels = {
            'store': 'Точка',
            'staff': 'Сотрудник',
            'date': 'Дата',
            'withdrawn': 'Забрали наличными',
            'week_beg_rec': 'Первый день недели, за которую забрали ЗП',
            'comment': 'Комментарий'
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
            }),
            "week_beg_rec": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Первый день недели, за которую забрали ЗП!'
            }),
            "comment": Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Комментарий',
                'rows': '2'
            })
        }

    def clean_withdrawn(self):
        withdrawn = self.cleaned_data["withdrawn"]
        store = self.cleaned_data["store"]
        date = self.cleaned_data["date"]

        if withdrawn <= 0:
            raise ValidationError('Сумма должна быть положительной')

        # Чтобы сравнивать всегда общую сумму нала (которая на точке и которую взяли как зп)
        # withdrawns_on_store = CashWithdrawn.objects.filter(date=date, store=store).aggregate(wdr_sum=Sum('withdrawn'))['wdr_sum']
        # if withdrawns_on_store is None:
        #     withdrawns_on_store = 0

        try:
            cash_on_store = CashStore.objects.get(date=date, store=store).cash_evn # + withdrawns_on_store
        except ObjectDoesNotExist:
            cash_on_store = 0

        if withdrawn > cash_on_store:
            raise ValidationError(f'Нельзя забрать наличных больше, чем есть на точке ({cash_on_store})')

        return withdrawn

    def clean_week_beg_rec(self):
        week_beg_rec = self.cleaned_data["week_beg_rec"]
        if week_beg_rec is not None and week_beg_rec.weekday() != 0:
            raise ValidationError('Укажите первый день недели, за которую забираете ЗП (понедельник)')
        return week_beg_rec

    def clean(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        store = cleaned_data.get("store")
        date = cleaned_data.get("date")

        if not Schedule.objects.filter(staff=staff, date=date, store=store).exists():
            raise ValidationError('Сотрудник не работает на выбранной точке в указанную дату')


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
        self.fields['staff'].queryset = Staff.objects.filter(dism_status="Работает")
        self.fields['staff'].empty_label = "Выберите сотрудника"
        self.fields['store'].queryset = Store.objects.filter(store_status="Действующая")
        self.fields['store'].empty_label = "Выберите точку"

    class Meta:
        model = Salary
        fields = ['store', 'staff', 'date', 'salary_sum', 'cash_box']

        labels = {
            'store': 'Точка',
            'staff': 'Сотрудник',
            'date': 'Дата',
            'salary_sum': 'Зарплата',
            'cash_box': 'Касса сотрудника'
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
            }),
            "cash_box": NumberInput(attrs={
                'class': 'form-control',
                'label': 'Касса сотрудника'
            })
        }

    def clean_salary_sum(self):
        salary = self.cleaned_data["salary_sum"]
        if salary < 0:
            raise ValidationError('Сумма зарплаты должна быть положительной')
        return salary

    def clean_cash_box(self):
        cash_box = self.cleaned_data["cash_box"]
        if cash_box < 0:
            raise ValidationError('Касса должна быть положительной')
        return cash_box

    def clean(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        store = cleaned_data.get("store")
        date = cleaned_data.get("date")
        print(staff, store, date)

        if not Schedule.objects.filter(staff=staff, date=date, store=store).exists():
            raise ValidationError('Сотрудник не работает на выбранной точке в указанную дату')


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


class CashStoreForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['store'].queryset = Store.objects.filter(store_status="Действующая")
        self.fields['store'].empty_label = "Выберите точку"

    class Meta:
        model = CashStore
        fields = ['store', 'date', 'cash_mrn']

        labels = {
            'store': 'Точка',
            'date': 'Дата',
            'cash_mrn': 'Наличные в начале дня'
        }

        widgets = {
            "store": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Точка',
                'label': 'Точка'
            }),
            "date": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Дата'
            }),
            "cash_mrn": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Наличные в начале дня'
            })
        }

    def clean_cash_mrn(self):
        cash = self.cleaned_data['cash_mrn']
        if cash < 0:
            raise ValidationError('Сумма наличных не может быть отрицательной!')
        return cash

    def clean_date(self):
        date = self.cleaned_data["date"]
        if date > datetime.today().date():
            raise ValidationError('Дата не может быть в будущем')
        return date


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
        if end_date > datetime.today().date():
            raise ValidationError('Дата окончания не может быть в будущем')
        return end_date

    def clean_beg_date(self):
        beg_date = self.cleaned_data["beg_date"]
        if beg_date < datetime(2024, 1, 1).date():
            raise ValidationError('Дата начала не может быть раньше 2024 года')
        return beg_date

    def clean(self):
        cleaned_data = super().clean()
        beg_date = cleaned_data.get("beg_date")
        end_date = cleaned_data.get("end_date")
        if end_date is not None:
            if beg_date > end_date:
                raise ValidationError('Начало периода не может быть больше окончания')


class TimeAndTypeSelectForm(Form):
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
    sal_calc_flag = forms.BooleanField(required=False, widget=CheckboxInput(attrs={
        'class': 'form-check-input',
        'role': 'switch',
        'placeholder': 'Считаем зарплату по дням'
    }),
                                       label='Считаем зарплату по дням')
    sal_weekly_flag = forms.BooleanField(required=False, widget=CheckboxInput(attrs={
        'class': 'form-check-input',
        'role': 'switch',
        'placeholder': 'Заполняем зарплаты понедельно на основе дневных зарплат'
    }),
                                         label='Заполняем зарплаты понедельно на основе дневных зарплат')

    def clean_end_date(self):
        end_date = self.cleaned_data["end_date"]
        if end_date > datetime.today().date():
            raise ValidationError('Дата окончания не может быть в будущем')
        return end_date

    def clean_beg_date(self):
        beg_date = self.cleaned_data["beg_date"]
        if beg_date < datetime(2024, 1, 1).date():
            raise ValidationError('Дата начала не может быть раньше 2024 года')
        return beg_date

    def clean(self):
        cleaned_data = super().clean()
        beg_date = cleaned_data.get("beg_date")
        end_date = cleaned_data.get("end_date")
        if end_date is not None:
            if beg_date > end_date:
                raise ValidationError('Начало периода не может быть больше окончания')


class SalaryWeeklyForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].queryset = Staff.objects.filter(dism_status="Работает")
        self.fields['staff'].empty_label = "Выберите сотрудника"

    class Meta:
        model = SalaryWeekly
        fields = ['staff', 'week_begin', 'week_end', 'salary_sum', 'cash_withdrawn', 'to_pay', 'paid_out']

        labels = {
            'staff': 'Сотрудник',
            'week_begin': 'Начало недели',
            'week_end': 'Конец недели',
            'salary_sum': 'Зарплата',
            'cash_withdrawn': 'Забрали наличными',
            'to_pay': 'Осталось выплатить',
            'paid_out': 'Выплачено'
        }

        widgets = {
            "staff": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Сотрудник',
                'label': 'Сотрудник'
            }),
            "week_begin": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Начало недели'
            }),
            "week_end": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Конец недели'
            }),
            "salary_sum": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Зарплата'
            }),
            "cash_withdrawn": NumberInput(attrs={
                'class': 'form-control',
                'label': 'Забрали наличными'
            }),
            "to_pay": NumberInput(attrs={
                'class': 'form-control',
                'label': 'Осталось выплатить'
            }),
            "paid_out": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Выплачено',
                'label': 'Выплачено'
            })
        }


class ImplEventsForm(ModelForm):
    class Meta:
        model = ImplEvents
        fields = ['event_type', 'event_message', 'status', 'solved']

        labels = {
            'event_type': 'Тип события',
            'event_message': 'Текст события',
            'status': 'Статус',
            'solved': 'Решено'
        }

        widgets = {
            "event_type": TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Тип события'
            }),
            "event_message": Textarea(attrs={
                'class': 'form-control',
                'rows': '3',
                'placeholder': 'Текст события'
            }),
            "status": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Статус',
                'label': 'Статус'
            }),
            "solved": Select(attrs={
                'class': 'form-select',
                'aria-label': 'Решено',
                'label': 'Решено'
            })
        }


class FinStatsMonthForm(ModelForm):
    class Meta:
        model = FinStatsMonth
        fields = ['expenses']

        labels = {
            'expenses': 'Расходы'
        }

        widgets = {
            "expenses": NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Расходы'
            })
        }

    def clean_expenses(self):
        expenses = self.cleaned_data["expenses"]
        if expenses < 0:
            raise ValidationError('Сумма должна быть положительной')
        return expenses


class FinStatsStaffForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].queryset = Staff.objects.filter(dism_status="Работает")
        self.fields['staff'].empty_label = "Выберите сотрудника"

    class Meta:
        model = FinStatsStaff
        fields = ['staff', 'date']

        labels = {
            'date': 'Отчетный месяц',
            'staff': 'Сотрудник'
        }

        widgets = {
            "date": FengyuanChenDatePickerInput(attrs={
                'class': 'form-control',
                'placeholder': 'Отчетный месяц'
            }),
            "staff": Select(attrs={
                'class': 'form-select',
                'placeholder': 'Сотрудник'
            })
        }
