from django.db import models


class Staff(models.Model):
    f_name = models.CharField(max_length=30)
    name = models.CharField(max_length=30)
    o_name = models.CharField(max_length=30, blank=True)
    date_empl = models.DateField()
    date_dism = models.DateField(null=True)

    class Meta:
        verbose_name = 'Сотрудники'
        verbose_name_plural = 'Сотрудники'

    def __str__(self):
        return f'{self.f_name} {self.name}'


class Store(models.Model):
    name = models.CharField(max_length=30)
    short_name = models.CharField(max_length=20)

    class Meta:
        verbose_name = 'Точки'
        verbose_name_plural = 'Точки'

    def __str__(self):
        return self.name


class Schedule(models.Model):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    position = models.CharField(max_length=40, default='Должность в смене')
    date = models.DateField()

    class Meta:
        verbose_name = 'График сотрудников'
        verbose_name_plural = 'График сотрудников'

    def __str__(self):
        return f'{self.date} - {self.staff} - {self.store}'


class ConsumablesStore(models.Model):
    consumable = models.CharField(max_length=60)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, default="Точка")
    count = models.IntegerField()
    change_data = models.DateField()

    class Meta:
        verbose_name = 'Расходники на точке'
        verbose_name_plural = 'Расходники на точке'

    def __str__(self):
        return f'{self.store} - {self.consumable}'


class Sales(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    date = models.DateTimeField()
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    sale_type = models.CharField(max_length=40, default='Тип продажи фото')
    payment_type = models.CharField(max_length=40, default='Способ оплаты')
    sum = models.IntegerField()
    photo_count = models.IntegerField()
    cl_email = models.CharField(max_length=40)
    cl_phone = models.CharField(max_length=12)

    class Meta:
        verbose_name = 'Продажи'
        verbose_name_plural = 'Продажи'

    def __str__(self):
        return f'{self.date} - {self.store} - {self.staff}'


class ConsumablesSales(models.Model):
    sale = models.ForeignKey(Sales, on_delete=models.CASCADE)
    consumable = models.CharField(max_length=60, default='Название расходника')
    count = models.IntegerField()

    class Meta:
        verbose_name = 'Потраченные расходники за продажу'
        verbose_name_plural = 'Потраченные расходники за продажу'

    def __str__(self):
        return f'{self.sale} - {self.consumable}'


class Salary(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    date = models.DateField()
    salary_sum = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Зарплаты сотрудников'
        verbose_name_plural = 'Зарплаты сотрудников'

    def __str__(self):
        return f'{self.date} - {self.staff}'

class CashWithdrawn(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    date = models.DateField()
    withdrawn = models.IntegerField()

    class Meta:
        verbose_name = 'Выдача зарплаты наличкой'
        verbose_name_plural = 'Выдача зарплаты наличкой'

    def __str__(self):
        return f'{self.date} - {self.staff}'
