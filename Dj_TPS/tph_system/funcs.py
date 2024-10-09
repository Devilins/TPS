from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum

from .models import *


# Генератор списка дат от start до end
def date_generator(start, end):
    while start <= end:
        yield start
        start += timedelta(days=1)


def sal_calc(time_start, time_end):

    params = Settings.objects.all()

    for day_date in date_generator(datetime.strptime(time_start, '%d.%m.%Y'),
                                   datetime.strptime(time_end, '%d.%m.%Y')):
        for one_staff in Staff.objects.all(): # ДОДЕЛАТЬ - чтобы в объекты попадали только те сотрудники,
                                                        # которые в day_date в смене.
            cashbx_staff = 0  # Касса сотрудника за день
            sal_staff = 0     # Зарплата сотрудника за день
            # Все продажи сотрудника за день. Раскидываем на фотографа, админа и универсала.
            sales_ph = Sales.objects.filter(date=day_date.date(), photographer=one_staff).exclude(staff=one_staff)
            sales_adm = Sales.objects.filter(date=day_date.date(), staff=one_staff).exclude(photographer=one_staff)
            sales_univ = Sales.objects.filter(date=day_date.date(), staff=one_staff, photographer=one_staff)

            if sales_univ.exists():
                # Касса универсала
                cashbx_sum = sales_univ.exclude(sale_type__in=['Заказной фотосет','Заказ выездной']
                                                ).aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']
                cashbx_staff += cashbx_sum

                if cashbx_sum <= int(params.get(param='univ_cashbx_min_border').value):
                    sal_staff = int(params.get(param='univ_min_payment').value)
                    # Доделать - 1000 платим, если не было заказов!
                else:
                    sal_staff += cashbx_sum * int(params.get(param='univ_perc_payment').value)

            if sales_ph.exists():
                for sl in sales_ph:
                    cashbx_staff += sl.sum
                    if sl.sale_type == 'Заказной фотосет':
                        # Проверка на выходные
                        if day_date.weekday() in (5, 6):
                            sal_staff += sl.photo_count * int(
                                params.get(param=str(sl.store.short_name) + '_order_ph_wknd').value)
                        else:
                            sal_staff += sl.photo_count * int(
                                params.get(param=str(sl.store.short_name) + '_order_ph_budn').value)
                    elif sl.sale_type == 'Заказ выездной':
                        sal_staff += sl.photo_count * int(params.get(param='order_ph_out').value)
                    else:
                        sal_ph_caser(day_date, one_staff, sl)

            if sales_adm.exists():
                for sl in sales_adm:
                    cashbx_staff += sl.sum
                    sal_adm_caser(day_date, one_staff, sl)

            print(f"Дата - ", day_date.date(),
                  f"Касса сотрудника - ", cashbx_staff,
                  f"Зарплата - ", sal_staff,
                  f"Сотрудник - ", one_staff.name, one_staff.f_name)


def sal_univ_caser(date, staff, cashbx):
    pass


def sal_ph_caser(date, staff, sale):
    pass


def sal_adm_caser(date, staff, sale):
    pass