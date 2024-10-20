from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum, Q, Count

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
            cashbx_staff = 0  # Касса сотрудника за день
            sal_staff = 0  # Зарплата сотрудника за день

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
                # Касса фотографа
                cashbx_sum = int(sales_ph.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= int(params.get(param='phot_cashbx_min_border').value):
                    sal_staff += int(params.get(param='phot_min_payment').value)
                elif day_date.weekday() in (5, 6):  # Выходные
                    if cashbx_sum <= int(params.get(param='phot_cashbx_perc_border_wknd').value):  # 15000
                        sal_staff += cashbx_sum * int(params.get(param='phot_stand_perc_pay').value) / 100  # 0.2
                    elif int(sch.aggregate(stsum=Count('staff'))['stsum']) < int(params.get(param='phot_count_incr_pay_if').value):
                        sal_staff += cashbx_sum * int(params.get(param='phot_few_incr_perc_pay').value) / 100  # 0.22
                    else:
                        sal_staff += cashbx_sum * int(params.get(param='phot_many_incr_perc_pay').value) / 100  # 0.25
                else:
                    if cashbx_sum <= int(params.get(param='phot_cashbx_perc_border_budn').value):  # 10000
                        sal_staff += cashbx_sum * int(params.get(param='phot_stand_perc_pay').value) / 100  # 0.2
                    elif int(sch.aggregate(stsum=Count('staff'))['stsum']) < int(params.get(param='phot_count_incr_pay_if').value):
                        sal_staff += cashbx_sum * int(params.get(param='phot_few_incr_perc_pay').value) / 100  # 0.22
                    else:
                        sal_staff += cashbx_sum * int(params.get(param='phot_many_incr_perc_pay').value) / 100  # 0.25

            if sales_adm.exists():
                # Касса администратора
                cashbx_sum = int(sales_adm.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= int(params.get(param='admin_cashbx_min_border').value):
                    sal_staff += int(params.get(param='admin_min_payment').value)
                elif day_date.weekday() in (5, 6):  # Выходные
                    if cashbx_sum < int(params.get(param='admin_cashbx_perc_border_wknd').value):  # 20000
                        sal_staff += (800 + cashbx_sum * int(params.get(param='admin_stand_perc_pay').value) / 100)  # 0.1
                    else:
                        sal_staff += cashbx_sum * int(params.get(param=str(
                            sch.store.short_name) + '_admin_incr_perc_pay_wknd').value) / 100  # 0.17
                else:
                    if cashbx_sum < int(params.get(param='admin_cashbx_perc_border_budn').value):  # 10000
                        sal_staff += (800 + cashbx_sum * int(params.get(param='admin_stand_perc_pay').value) / 100)  # 0.1
                    else:
                        sal_staff += cashbx_sum * int(params.get(param='admin_incr_perc_pay_budn').value) / 100  # 0.2

            if not sales_zak.exists() and not sales_adm.exists() and not sales_ph.exists() and not sales_univ.exists():
                # !!! Дописать начисление минимальной зарплаты сотрудникам, если за день все кассы 0
                pass

            # Отладочная информация
            print(f"Дата - ", day_date.date(),
                  f"Касса сотрудника - ", cashbx_staff,
                  f"Зарплата - ", sal_staff,
                  f"Сотрудник - ", sch.staff.name, sch.staff.f_name)
            print(f"sales_ph = ", sales_ph, "\n",
                  f"sales_adm = ", sales_adm, "\n",
                  f"sales_univ = ", sales_univ, "\n",
                  f"sales_zak = ", sales_zak, "\n")
