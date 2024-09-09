from django.db import models
from django.contrib.auth.models import User
from django.core import validators


class Staff(models.Model):
    f_name = models.CharField(max_length=30)
    name = models.CharField(max_length=30)
    o_name = models.CharField(max_length=30, blank=True)
    date_empl = models.DateField()
    date_dism = models.DateField(null=True, blank=True)
    st_username = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        verbose_name = 'Сотрудники'
        verbose_name_plural = 'Сотрудники'
        ordering = ['name', 'f_name']

    def __str__(self):
        return f'{self.name} {self.f_name}'


class Store(models.Model):
    name = models.CharField(max_length=30)
    short_name = models.CharField(max_length=20)

    class Meta:
        verbose_name = 'Точки'
        verbose_name_plural = 'Точки'
        ordering = ['name']

    def __str__(self):
        return self.name


class Schedule(models.Model):
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT)
    store = models.ForeignKey(Store, on_delete=models.PROTECT)
    position = models.CharField(max_length=40, default='Должность в смене')
    date = models.DateField()

    class Meta:
        verbose_name = 'График сотрудников'
        verbose_name_plural = 'График сотрудников'
        ordering = ['-date', 'store']

    def __str__(self):
        return f'{self.date} - {self.staff} - {self.store}'


class ConsumablesStore(models.Model):
    consumable = models.CharField(max_length=60)
    cons_short = models.CharField(max_length=40, default='', blank=True)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, default="Точка")
    count = models.IntegerField()
    change_data = models.DateField()

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
    )

    store = models.ForeignKey(Store, on_delete=models.PROTECT)
    date = models.DateField()
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT)
    photographer = models.ForeignKey(Staff, on_delete=models.PROTECT, related_name='sale_photographer', default='')
    sale_type = models.CharField(max_length=40, default='', choices=SLCT_ST)
    photo_count = models.IntegerField()
    payment_type = models.CharField(max_length=40, default='', choices=SLCT_PAYMENT)
    sum = models.IntegerField()
    cl_email = models.CharField(max_length=40, blank=True)
    cl_phone = models.CharField(max_length=12, blank=True)
    comment = models.TextField(null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True, editable=False, blank=True)

    class Meta:
        verbose_name = 'Продажи'
        verbose_name_plural = 'Продажи'
        ordering = ['-date_created', 'store']
    #    permissions = (("view_all_users_sales", "Видимость продаж всех пользователей"),)
    #    permissions = (("view_all_store_sales", "Видимость продаж на все точки"),)

    def __str__(self):
        return f'{self.date} - {self.store} - {self.staff}'


class ConsumablesSales(models.Model):
    sale = models.ForeignKey(Sales, on_delete=models.PROTECT)
    consumable = models.CharField(max_length=60)
    count = models.IntegerField()

    class Meta:
        verbose_name = 'Потраченные расходники за продажу'
        verbose_name_plural = 'Потраченные расходники за продажу'
        ordering = ['sale']

    def __str__(self):
        return f'{self.sale} - {self.consumable}'


class Salary(models.Model):
    store = models.ForeignKey(Store, on_delete=models.PROTECT)
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT)
    date = models.DateField()
    salary_sum = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Зарплаты сотрудников'
        verbose_name_plural = 'Зарплаты сотрудников'
        ordering = ['date', 'store']

    def __str__(self):
        return f'{self.date} - {self.staff}'


class CashWithdrawn(models.Model):
    store = models.ForeignKey(Store, on_delete=models.PROTECT)
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT)
    date = models.DateField()
    withdrawn = models.IntegerField()

    class Meta:
        verbose_name = 'Выдача зарплаты наличкой'
        verbose_name_plural = 'Выдача зарплаты наличкой'
        ordering = ['date', 'store']

    def __str__(self):
        return f'{self.date} - {self.staff}'


class Tech(models.Model):
    store = models.ForeignKey(Store, on_delete=models.PROTECT)
    name = models.CharField(max_length=50)
    serial_num = models.CharField(max_length=30, blank=True)
    count = models.IntegerField(default=1)
    date_buy = models.DateField()
    warranty_date = models.DateField(null=True, blank=True)
    date_change = models.DateTimeField(auto_now=True, editable=False, blank=True)

    class Meta:
        verbose_name = 'Фототехника'
        verbose_name_plural = 'Фототехника'
        ordering = ['store', 'name']

    def __str__(self):
        return f'{self.name} - {self.serial_num}'


class RefsAndTips(models.Model):
    tip = models.TextField()
    refs = models.CharField(max_length=200)

    class Meta:
        verbose_name = 'Инфо и ссылки'
        verbose_name_plural = 'Инфо и ссылки'
        ordering = ['-id']

    def __str__(self):
        return f'{self.tip}'
