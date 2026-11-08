from django import forms
from django.forms import CheckboxInput, ModelForm, NumberInput, Select, TextInput

from tph_system.forms import FengyuanChenDatePickerInput
from tph_system.models import Staff

from .models import Route, Venue
from .parsers import norm_place
from .planning import MAX_SPAN_DAYS


class VenueForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['store'].empty_label = "Нет фототочки"

    class Meta:
        model = Venue
        fields = ['name', 'brand', 'address', 'difficulty', 'store', 'sheet_tab_name', 'is_active']
        widgets = {
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Название центра'}),
            'brand': Select(attrs={'class': 'form-select'}),
            'address': TextInput(attrs={'class': 'form-control', 'placeholder': 'м. Беговая, Хорошёвское ш., 16, ТЦ «На Беговой»'}),
            'difficulty': NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 10}),
            'store': Select(attrs={'class': 'form-select'}),
            'sheet_tab_name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Название листа в таблице бренда'}),
            'is_active': CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class RouteForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['from_venue'].empty_label = "Выберите центр"
        self.fields['to_venue'].empty_label = "Выберите центр"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('from_venue') and cleaned.get('from_venue') == cleaned.get('to_venue'):
            raise forms.ValidationError("Центры отправления и назначения совпадают")
        return cleaned

    class Meta:
        model = Route
        fields = ['from_venue', 'to_venue', 'description', 'duration_min']
        widgets = {
            'from_venue': Select(attrs={'class': 'form-select'}),
            'to_venue': Select(attrs={'class': 'form-select'}),
            'description': TextInput(attrs={'class': 'form-control',
                                            'placeholder': 'Например: метро, пересадка на МЦК'}),
            'duration_min': NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 600}),
        }


class RouteCreateForm(RouteForm):
    create_reverse = forms.BooleanField(
        required=False, initial=True, label="Создать такой же маршрут в обратную сторону",
        widget=CheckboxInput(attrs={'class': 'form-check-input'}))

    def save(self, commit=True):
        route = super().save(commit=commit)
        if commit and self.cleaned_data.get('create_reverse'):
            # Обратный маршрут не перезатирает уже существующий вариант
            Route.objects.get_or_create(
                from_venue=route.to_venue, to_venue=route.from_venue, description=route.description,
                defaults={'duration_min': route.duration_min})
        return route


class RoutesImportForm(forms.Form):
    file = forms.FileField(label="CSV-файл", widget=forms.ClearableFileInput(
        attrs={'class': 'form-control form-control-sm', 'accept': '.csv'}))
    mirror = forms.BooleanField(
        required=False, initial=True, label="Создавать обратные маршруты, если их нет в файле",
        widget=CheckboxInput(attrs={'class': 'form-check-input'}))


class OrdersImportForm(forms.Form):
    BRAND_CHOICES = (('', 'Обе таблицы'), ('LL', 'Laserland'), ('JJ', 'Joki Joya'))
    brand = forms.ChoiceField(choices=BRAND_CHOICES, required=False, label="Таблица",
                              widget=Select(attrs={'class': 'form-select form-select-sm'}))
    date_from = forms.DateField(required=False, label="Заказы с", input_formats=['%d.%m.%Y'],
                                widget=FengyuanChenDatePickerInput(attrs={'class': 'form-control form-control-sm',
                                                                          'placeholder': 'Заказы с'}))
    date_to = forms.DateField(required=False, label="Заказы по", input_formats=['%d.%m.%Y'],
                              widget=FengyuanChenDatePickerInput(attrs={'class': 'form-control form-control-sm',
                                                                        'placeholder': 'Заказы по'}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('date_from') and cleaned.get('date_to') and cleaned['date_from'] > cleaned['date_to']:
            raise forms.ValidationError("Дата «с» позже даты «по»")
        return cleaned


class PersonAliasForm(forms.Form):
    """Сопоставление имени из таблицы с сотрудником (или пометка "игнорировать")"""
    alias = forms.CharField(max_length=60, widget=forms.HiddenInput)
    staff = forms.ModelChoiceField(queryset=Staff.objects.filter(dism_status="Работает"), required=False)
    ignore = forms.BooleanField(required=False)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('ignore') and not cleaned.get('staff'):
            raise forms.ValidationError("Выберите сотрудника или отметьте «Игнорировать»")
        return cleaned


class PlaceAliasForm(forms.Form):
    """Сопоставление фрагмента адреса из листа "ВЫЕЗДЫ" с центром (существующим или новым)"""
    key = forms.CharField(max_length=200, widget=forms.HiddenInput)  # нормализованный адрес целиком
    fragment = forms.CharField(max_length=100)
    venue = forms.ModelChoiceField(queryset=Venue.objects.all(), required=False)
    new_venue = forms.CharField(max_length=60, required=False)

    def clean(self):
        cleaned = super().clean()
        key, fragment = cleaned.get('key', ''), norm_place(cleaned.get('fragment', ''))
        if not fragment:
            raise forms.ValidationError("Фрагмент адреса пустой")
        if f' {fragment} ' not in f' {key} ':
            raise forms.ValidationError("Фрагмент должен встречаться в адресе из таблицы")
        if bool(cleaned.get('venue')) == bool(cleaned.get('new_venue', '').strip()):
            raise forms.ValidationError("Выберите существующий центр ИЛИ введите название нового")
        cleaned['fragment'] = fragment
        return cleaned


class PlanRunForm(forms.Form):
    """Период, за который рассчитывается распределение"""
    date_from = forms.DateField(label="Заказы с", input_formats=['%d.%m.%Y'],
                                widget=FengyuanChenDatePickerInput(attrs={'class': 'form-control form-control-sm',
                                                                          'placeholder': 'Заказы с'}))
    date_to = forms.DateField(label="Заказы по", input_formats=['%d.%m.%Y'],
                              widget=FengyuanChenDatePickerInput(attrs={'class': 'form-control form-control-sm',
                                                                        'placeholder': 'Заказы по'}))

    def clean(self):
        cleaned = super().clean()
        date_from, date_to = cleaned.get('date_from'), cleaned.get('date_to')
        if date_from and date_to:
            if date_from > date_to:
                raise forms.ValidationError("Дата «с» позже даты «по»")
            if (date_to - date_from).days + 1 > MAX_SPAN_DAYS:
                raise forms.ValidationError(f"Период не длиннее {MAX_SPAN_DAYS} дней")
        return cleaned
