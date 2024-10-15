from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum, Q

from .models import *


class SaleTypeError(Exception):
    pass

# Генератор списка дат от start до end
def date_generator(start, end):
    while start <= end:
        yield start
        start += timedelta(days=1)


def sal_calc(time_start, time_end):
    params = Settings.objects.all()

    for day_date in date_generator(datetime.strptime(time_start, '%d.%m.%Y'),
                                   datetime.strptime(time_end, '%d.%m.%Y')):
        # Продажи за день без заказов
        sales_today = Sales.objects.filter(date=day_date.date()).exclude(
                        sale_type__in=['Заказной фотосет', 'Заказ выездной'])
        for sch in Schedule.objects.filter(date=day_date.date()):
            # Касса сотрудника за день
            cashbx_staff = 0
            # cashbx_staff = int(Sales.objects.filter(Q(photographer=sch.staff, date=day_date.date()) |
            #                                         Q(staff=sch.staff, date=day_date.date())
            #                                         ).aggregate(cashbx_staff=Sum('sum')['cashbx_staff']))
            # Зарплата сотрудника за день
            sal_staff = 0

            # Все продажи сотрудника за день. Раскидываем на фотографа, админа и универсала и заказы.
            sales_ph = sales_today.filter(photographer=sch.staff).exclude(staff=sch.staff)
            sales_adm = sales_today.filter(staff=sch.staff).exclude(photographer=sch.staff)
            sales_univ = sales_today.filter(staff=sch.staff, photographer=sch.staff)
            sales_zak = Sales.objects.filter(date=day_date.date(), photographer=sch.staff,
                                             sale_type__in=['Заказной фотосет', 'Заказ выездной'])

            if sales_zak.exists():
                # Касса заказов
                cashbx_staff += int(sales_zak.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])

                for sl in sales_zak:
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
                        raise SaleTypeError(f"В заказных продажах ошибка в sale_type, sale.id = ", sl.id)

            if sales_univ.exists():
                # Касса универсала
                cashbx_sum = int(sales_univ.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= int(params.get(param='univ_cashbx_min_bord').value):
                    sal_staff += int(params.get(param='univ_min_payment').value)
                else:
                    sal_staff += cashbx_sum * int(params.get(param='univ_perc_payment').value) / 100

            if sales_ph.exists():
                for sl in sales_ph:
                    sal_ph_caser(day_date, sch.staff, sl)

            if sales_adm.exists():
                for sl in sales_adm:
                    sal_adm_caser(day_date, sch.staff, sl)

            print(f"Дата - ", day_date.date(),
                  f"Касса сотрудника - ", cashbx_staff,
                  f"Зарплата - ", sal_staff,
                  f"Сотрудник - ", sch.staff.name, sch.staff.f_name)
            print(f"sales_ph = ", sales_ph, "\n",
                  f"sales_adm = ", sales_adm, "\n",
                  f"sales_univ = ", sales_univ, "\n",
                  f"sales_zak = ", sales_zak, "\n")

def sal_univ_caser(date, staff, cashbx):
    pass


def sal_ph_caser(date, staff, sale):
    pass


def sal_adm_caser(date, staff, sale):
    pass
