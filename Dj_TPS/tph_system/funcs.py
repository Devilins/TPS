from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist

from .models import *


def date_generator(start, end):
    while start <= end:
        yield start
        start += timedelta(days=1)


def sal_calc(time_start, time_end):

    params = Settings.objects.all()

    for day_date in date_generator(datetime.strptime(time_start, '%d.%m.%Y'), datetime.strptime(time_end, '%d.%m.%Y')):
        for one_staff in Staff.objects.all():
            cashbx_staff = 0
            sal_staff = 0
            sales = Sales.objects.filter(date=day_date.date(), staff=one_staff)

            for sl in sales:
                cashbx_staff += sl.sum
                if sl.sale_type == 'Заказной фотосет':
                    # Тут нужна проверка на будни
                    sal_staff = sl.photo_count * int(params.get(param=str(sl.store.short_name) + '_order_ph_budn').value)

            print(f"Дата - ", day_date.date(),
                  f"Касса сотрудника - ", cashbx_staff,
                  f"Зарплата - ", sal_staff,
                  f"Сотрудник - ", one_staff.name)
