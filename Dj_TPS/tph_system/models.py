from datetime import datetime

from django.db import models
from django.contrib.auth.models import User
from django.template.defaultfilters import truncatechars
from schedule.models import Event, Calendar
from django.utils.translation import gettext_lazy as _


class Staff(models.Model):
    f_name = models.CharField(max_length=30, verbose_name=u"Фамилия")
    name = models.CharField(max_length=30, verbose_name=u"Имя")
    o_name = models.CharField(max_length=30, blank=True, verbose_name=u"Отчество")
    date_empl = models.DateField(verbose_name=u"Дата найма")
    date_dism = models.DateField(null=True, blank=True, verbose_name=u"Дата увольнения")
    st_username = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True,
                                    verbose_name=u"Учетная запись")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено", related_name='staff_user_edited')

    class Meta:
        verbose_name = 'Сотрудники'
        verbose_name_plural = 'Сотрудники'
        ordering = ['name', 'f_name']

    def __str__(self):
        return f'{self.name} {self.f_name}'


class Store(models.Model):
    name = models.CharField(max_length=30, verbose_name=u"Название")
    short_name = models.CharField(max_length=20, verbose_name=u"Функциональное название (не изменять)")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Точки'
        verbose_name_plural = 'Точки'
        ordering = ['name']

    def __str__(self):
        return self.name


class Schedule(models.Model):
    SLCT_POSITION = (
        ('Роль не указана', 'Роль не указана'),
        ('Администратор', 'Администратор'),
        ('Фотограф', 'Фотограф'),
        ('Универсальный фотограф', 'Универсальный фотограф')
    )
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, verbose_name=u"Сотрудник")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, verbose_name=u"Точка")
    position = models.CharField(max_length=40, default='Роль не указана', choices=SLCT_POSITION, verbose_name=u"Роль")
    date = models.DateField(verbose_name=u"Дата")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'График сотрудников'
        verbose_name_plural = 'График сотрудников'
        ordering = ['-date', 'store']

    def __str__(self):
        return f'{self.date} - {self.staff} - {self.store} - {self.position}'


class ConsumablesStore(models.Model):
    consumable = models.CharField(max_length=60, verbose_name=u"Расходник")
    cons_short = models.CharField(max_length=40, default='', blank=True,
                                  verbose_name=u"Функциональное наименование (не изменять)")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, default="Точка", verbose_name=u"Точка")
    count = models.IntegerField(verbose_name=u"Количество на точке")
    change_data = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Расходники на точке'
        verbose_name_plural = 'Расходники на точке'
        ordering = ['store', 'consumable']

    def __str__(self):
        return f'{self.store} - {self.consumable}'


class Sales(models.Model):
    # селектор для payment_type
    SLCT_PAYMENT = (
        ('Наличные', 'Наличные'),
        ('Карта', 'Карта'),
        ('Оплата по QR коду', 'Оплата по QR коду'),
        ('Перевод по номеру телефона', 'Перевод по номеру телефона'),
        ('Предоплаченный заказ', 'Предоплаченный заказ')
    )
    # селектор для sale_type
    SLCT_ST = (
        ('Email (фото)', 'Email (фото)'),
        ('Email (все)', 'Email (все)'),
        ('Вин. магн.', 'Вин. магн.'),
        ('Ср. магн.', 'Ср. магн.'),
        ('Бол. магн.', 'Бол. магн.'),
        ('Печать 10x15', 'Печать 10x15'),
        ('Печать 15x20', 'Печать 15x20'),
        ('Печать A4', 'Печать A4'),
        ('Заказной фотосет', 'Заказной фотосет'),
        ('Заказ выездной', 'Заказ выездной')
    )

    store = models.ForeignKey(Store, on_delete=models.PROTECT, verbose_name=u"Точка")
    date = models.DateField(verbose_name=u"Дата")
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, verbose_name=u"Администратор")
    photographer = models.ForeignKey(Staff, on_delete=models.PROTECT, related_name='sale_photographer', default='',
                                     verbose_name=u"Фотограф")
    sale_type = models.CharField(max_length=40, default='', choices=SLCT_ST, verbose_name=u"Тип продажи")
    photo_count = models.IntegerField(verbose_name=u"Кол-во фотографий")
    payment_type = models.CharField(max_length=40, default='', choices=SLCT_PAYMENT, verbose_name=u"Способ оплаты")
    sum = models.IntegerField(verbose_name=u"Сумма")
    cl_email = models.CharField(max_length=40, blank=True, verbose_name=u"Email клиента")
    cl_phone = models.CharField(max_length=12, blank=True, verbose_name=u"Телефон клиента")
    comment = models.TextField(null=True, blank=True, verbose_name=u"Комментарий")
    date_created = models.DateTimeField(auto_now_add=True, editable=False, blank=True, verbose_name=u"Дата создания")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Продажи'
        verbose_name_plural = 'Продажи'
        ordering = ['-date_created', 'store']
    #    permissions = (("view_all_users_sales", "Видимость продаж всех пользователей"),)
    #    permissions = (("view_all_store_sales", "Видимость продаж на все точки"),)

    def __str__(self):
        return f'{self.date} - {self.store} - {self.staff}'


class ConsumablesSales(models.Model):  # -----------Не используется------------
    sale = models.ForeignKey(Sales, on_delete=models.PROTECT)
    consumable = models.CharField(max_length=60)
    count = models.IntegerField()
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True)
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT)

    class Meta:
        verbose_name = 'Потраченные расходники за продажу'
        verbose_name_plural = 'Потраченные расходники за продажу'
        ordering = ['sale']

    def __str__(self):
        return f'{self.sale} - {self.consumable}'


class Salary(models.Model):
    store = models.ForeignKey(Store, on_delete=models.PROTECT, verbose_name=u"Точка")
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, verbose_name=u"Сотрудник")
    date = models.DateField(verbose_name=u"Дата")
    salary_sum = models.DecimalField(max_digits=8, decimal_places=2, verbose_name=u"Зарплата за день")
    cash_box = models.IntegerField(default=0, verbose_name=u"Касса за день")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Зарплаты'
        verbose_name_plural = 'Зарплаты'
        ordering = ['-date', 'staff']

    def __str__(self):
        return f'{self.date} - {self.staff}'


class SalaryWeekly(models.Model):
    # селектор для paid_out
    SLCT_PAID = (
        ('Да', 'Да'),
        ('Нет', 'Нет')
    )
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, verbose_name=u"Сотрудник")
    week_begin = models.DateField(verbose_name=u"Начало периода")
    week_end = models.DateField(verbose_name=u"Конец периода")
    cash_box_week = models.IntegerField(default=0, verbose_name=u"Касса за неделю")
    salary_sum = models.DecimalField(max_digits=8, decimal_places=2, verbose_name=u"Зарплата за неделю")
    cash_withdrawn = models.IntegerField(verbose_name=u"Забрали наличными за неделю")
    to_pay = models.DecimalField(max_digits=8, decimal_places=2, verbose_name=u"Осталось выплатить")
    paid_out = models.CharField(max_length=10, default='Нет', choices=SLCT_PAID, verbose_name=u"Выплачено")
    date_updated = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Зарплаты за неделю'
        verbose_name_plural = 'Зарплаты за неделю'
        ordering = ['-week_begin', 'staff']

    def __str__(self):
        return f'{self.week_begin} - {self.week_end}: {self.staff}'


class CashWithdrawn(models.Model):
    store = models.ForeignKey(Store, on_delete=models.PROTECT, verbose_name=u"Точка")
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, verbose_name=u"Сотрудник")
    date = models.DateField(verbose_name=u"Дата")
    withdrawn = models.IntegerField(verbose_name=u"Сколько забрали наличными")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Выдача зарплаты наличкой'
        verbose_name_plural = 'Выдача зарплаты наличкой'
        ordering = ['-date', 'store']

    def __str__(self):
        return f'{self.date} - {self.staff} - {self.withdrawn}'


class Tech(models.Model):
    store = models.ForeignKey(Store, on_delete=models.PROTECT, verbose_name=u"Точка")
    name = models.CharField(max_length=50, verbose_name=u"Название")
    serial_num = models.CharField(max_length=30, blank=True, verbose_name=u"Серийный номер")
    count = models.IntegerField(default=1, verbose_name=u"Количество на точке")
    date_buy = models.DateField(verbose_name=u"Дата покупки")
    warranty_date = models.DateField(null=True, blank=True, verbose_name=u"Дата окончания гарантии")
    date_change = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Фототехника'
        verbose_name_plural = 'Фототехника'
        ordering = ['store', 'name']

    def __str__(self):
        return f'{self.name} - {self.serial_num}'


class RefsAndTips(models.Model):
    tip = models.TextField(verbose_name=u"Информация")
    refs = models.CharField(max_length=200, verbose_name=u"Ссылки")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Инфо и ссылки'
        verbose_name_plural = 'Инфо и ссылки'
        ordering = ['-id']

    def __str__(self):
        return f'{self.tip}'


class Settings(models.Model):
    param_f_name = models.TextField(verbose_name=u"Описание")
    param = models.CharField(max_length=50, verbose_name=u"Параметр")
    value = models.CharField(max_length=30, verbose_name=u"Значение")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Настройки'
        verbose_name_plural = 'Настройки'
        ordering = ['param']

    def __str__(self):
        return f'{self.param}'


class ImplEvents(models.Model):
    SLCT_STATUS = (
        ('Системная ошибка', 'Системная ошибка'),
        ('Бизнес ошибка', 'Бизнес ошибка'),
        ('Успешно', 'Успешно'),
        ('Удаление записи', 'Удаление записи')
    )
    SLCT_SOLVED = (
        ('Да', 'Да'),
        ('Нет', 'Нет')
    )
    event_type = models.CharField(max_length=50, verbose_name=u"Тип события")
    event_message = models.TextField(verbose_name=u"Текст события")
    status = models.CharField(max_length=50, choices=SLCT_STATUS, verbose_name=u"Статус")
    solved = models.CharField(max_length=10, null=True, choices=SLCT_SOLVED, verbose_name=u"Решено")
    date_created = models.DateTimeField(auto_now_add=True, editable=False, blank=True, verbose_name=u"Дата создания")
    date_updated = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Системные события'
        verbose_name_plural = 'Системные события'
        ordering = ['-id', 'event_type']

    def __str__(self):
        return f'{self.date_created} - {self.event_type} : {self.status} => {self.solved}'

    @property
    def short_event_message(self):
        return truncatechars(self.event_message, 180)


class FinStatsMonth(models.Model):
    date = models.DateField(verbose_name=u"Отчетный месяц")
    revenue = models.IntegerField(verbose_name=u"Выручка (Кассы)")
    salaries = models.DecimalField(max_digits=9, decimal_places=2, verbose_name=u"Зарплаты")
    expenses = models.IntegerField(default=0, verbose_name=u"Расходы")
    profit = models.DecimalField(max_digits=9, decimal_places=2, verbose_name=u"Прибыль")
    date_updated = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Финансы - компания'
        verbose_name_plural = 'Финансы - компания'
        ordering = ['date']

    def __str__(self):
        return f'{self.date}'

    def save(self, *args, **kwargs):
        self.profit = self.revenue - self.salaries - self.expenses
        super().save(*args, **kwargs)


class FinStatsStaff(models.Model):
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, verbose_name=u"Сотрудник")
    date = models.DateField(verbose_name=u"Отчетный месяц")
    cash_box = models.IntegerField(verbose_name=u"Касса")
    salary = models.DecimalField(max_digits=9, decimal_places=2, verbose_name=u"Зарплата")
    date_updated = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name=u"Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT,
                                    verbose_name=u"Кем было изменено")

    class Meta:
        verbose_name = 'Финансы - сотрудники'
        verbose_name_plural = 'Финансы - сотрудники'
        ordering = ['date', 'staff']

    def __str__(self):
        return f'{self.date} - {self.staff}'


# --------------------------------------Календарь отпусков не используемый--------------------------------
class CalendarEvent(models.Model):
    EVENT_TYPES = [
        ('vacation', 'Отпуск'),
        ('holiday', 'Праздничный день'),
        ('school_break', 'Школьные каникулы'),
    ]

    EVENT_COLORS = {
        'vacation': '#FF9999',  # Красноватый для отпусков
        'holiday': '#99FF99',  # Зеленоватый для праздников
        'school_break': '#9999FF',  # Синеватый для каникул
    }

    title = models.CharField(_('Название'), max_length=200)
    event_type = models.CharField(_('Тип события'), max_length=20, choices=EVENT_TYPES)
    start_date = models.DateField(_('Дата начала'))
    end_date = models.DateField(_('Дата окончания'))
    description = models.TextField(_('Описание'), blank=True)
    employee = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('Сотрудник'),
        help_text=_('Заполняется только для отпусков')
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE)

    class Meta:
        verbose_name = _('Календарь событий')
        verbose_name_plural = _('Календарь событий')

    def save(self, *args, **kwargs):
        if not self.pk:  # Если объект создается впервые
            calendar = Calendar.objects.get(slug='company-calendar')

            # Формируем заголовок события
            if self.event_type == 'vacation':
                title = f'Отпуск: {self.employee.get_full_name()}'    # Есть вопросы к методу
            else:
                title = self.title

            # Создаем событие в календаре
            event = Event(
                start=self.start_date,
                end=self.end_date,
                title=title,
                description=self.description,
                calendar=calendar,
                color_event=self.EVENT_COLORS[self.event_type],
                creator=self.employee if self.employee else None
            )
            event.save()
            self.event = event
        super().save(*args, **kwargs)
