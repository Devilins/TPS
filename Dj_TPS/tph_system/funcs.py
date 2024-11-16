from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum, Q, Count
from django.http.response import Http404

from .models import *


class SaleTypeError(Exception):
    pass


# Генератор списка дат от start до end
def date_generator(start, end):
    while start <= end:
        yield start
        start += timedelta(days=1)


def start_week_generator(start, end):
    while start.isocalendar().week <= end.isocalendar().week:
        yield start - timedelta(days=start.weekday())
        start += timedelta(days=7)


def start_month_generator(start, end):
    while start.month <= end.month:
        yield start
        start += timedelta(weeks=4)


def param_gets(par):
    try:
        return int(Settings.objects.get(param=str(par)).value)
    except Settings.DoesNotExist:
        error = ImplEvents.objects.create(
            event_type='Param_Gets_Error',
            event_message=f"Нет такого параметра в Настройках => {str(par)}. Для дальнейшей работы операции "
                          f"добавьте в Настройки новый параметр {str(par)} с нужным вам значением.",
            status='Системная ошибка',
            solved='Нет'
        )
        print(f"ImplEvents - новая запись {error}")
        raise SaleTypeError(f"Нет такого параметра в Настройках => {str(par)}. Для дальнейшей работы операции "
                            f"добавьте в Настройки новый параметр {str(par)} с нужным вам значением.")


def sal_calc(time_start, time_end):
    for day_date in date_generator(time_start, time_end):
        # Продажи за день без заказов
        sales_today = Sales.objects.filter(date=day_date).exclude(sale_type__in=['Заказной фотосет', 'Заказ выездной'])
        for sch in Schedule.objects.filter(date=day_date):
            cashbx_staff = 0  # Касса сотрудника за день
            sal_staff = 0  # Зарплата сотрудника за день

            # Все продажи сотрудника за день. Раскидываем на фотографа, админа и универсала и заказы.
            sales_ph = sales_today.filter(photographer=sch.staff).exclude(staff=sch.staff)
            sales_adm = sales_today.filter(staff=sch.staff).exclude(photographer=sch.staff)
            sales_univ = sales_today.filter(staff=sch.staff, photographer=sch.staff)
            sales_zak = Sales.objects.filter(date=day_date, photographer=sch.staff,
                                             sale_type__in=['Заказной фотосет', 'Заказ выездной'])
            sales_zak_admin_service = Sales.objects.filter(date=day_date, staff=sch.staff,
                                                           sale_type='Заказной фотосет'
                                                           ).exclude(photographer=sch.staff)

            if sales_zak.exists():
                # Касса заказов
                cashbx_staff += int(sales_zak.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                for sl in sales_zak:
                    if sl.sale_type == 'Заказной фотосет':
                        # Проверка на выходные
                        if day_date.weekday() in (5, 6):
                            sal_staff += sl.photo_count * param_gets(str(sl.store.short_name) + '_order_ph_wknd')
                        else:
                            sal_staff += sl.photo_count * param_gets(str(sl.store.short_name) + '_order_ph_budn')

                    elif sl.sale_type == 'Заказ выездной':
                        sal_staff += sl.photo_count * param_gets('order_ph_out')
                    else:
                        error = ImplEvents.objects.create(
                            event_type='Salary_SaleTypeError',
                            event_message=f"В заказных продажах ошибка - sale_type ({sl.sale_type}) не соответствует "
                                          f"заданным типам"
                                          f"(Заказной фотосет или Заказ выездной), sale.id = {sl.id}; sale = {sl}",
                            status='Бизнес ошибка',
                            solved='Нет'
                        )
                        print(f"ImplEvents - новая запись {error}")

            if sales_univ.exists():
                # Касса универсала
                cashbx_sum = int(sales_univ.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= param_gets('univ_cashbx_min_bord'):
                    sal_staff += param_gets('univ_min_payment')
                else:
                    sal_staff += cashbx_sum * param_gets('univ_perc_payment') / 100

            if sales_ph.exists():
                # Касса фотографа
                cashbx_sum = int(sales_ph.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= param_gets('phot_cashbx_min_border'):
                    sal_staff += param_gets('phot_min_payment')
                elif day_date.weekday() in (5, 6):  # Выходные
                    if cashbx_sum <= param_gets('phot_cashbx_perc_border_wknd'):  # 15000
                        sal_staff += cashbx_sum * param_gets('phot_stand_perc_pay') / 100  # 0.2
                    elif int(sch.aggregate(stsum=Count('staff'))['stsum']) < param_gets('phot_count_incr_pay_if'):
                        sal_staff += cashbx_sum * param_gets('phot_few_incr_perc_pay') / 100  # 0.22
                    else:
                        sal_staff += cashbx_sum * param_gets('phot_many_incr_perc_pay') / 100  # 0.25
                else:
                    if cashbx_sum <= param_gets('phot_cashbx_perc_border_budn'):  # 10000
                        sal_staff += cashbx_sum * param_gets('phot_stand_perc_pay') / 100  # 0.2
                    elif int(sch.aggregate(stsum=Count('staff'))['stsum']) < param_gets('phot_count_incr_pay_if'):
                        sal_staff += cashbx_sum * param_gets('phot_few_incr_perc_pay') / 100  # 0.22
                    else:
                        sal_staff += cashbx_sum * param_gets('phot_many_incr_perc_pay') / 100  # 0.25

            if sales_adm.exists():
                # Касса администратора
                cashbx_sum = int(sales_adm.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= param_gets('admin_cashbx_min_border'):
                    sal_staff += param_gets('admin_min_payment')
                elif day_date.weekday() in (5, 6):  # Выходные
                    if cashbx_sum < param_gets('admin_cashbx_perc_border_wknd'):  # 20000
                        sal_staff += (800 + cashbx_sum * param_gets('admin_stand_perc_pay') / 100)  # 0.1
                    else:
                        sal_staff += cashbx_sum * param_gets(
                            str(sch.store.short_name) + '_admin_incr_perc_pay_wknd') / 100  # 0.17
                else:
                    if cashbx_sum < param_gets('admin_cashbx_perc_border_budn'):  # 10000
                        sal_staff += (800 + cashbx_sum * param_gets('admin_stand_perc_pay') / 100)  # 0.1
                    else:
                        sal_staff += cashbx_sum * param_gets('admin_incr_perc_pay_budn') / 100  # 0.2

            if not sales_zak.exists() and not sales_adm.exists() and not sales_ph.exists() and not sales_univ.exists():
                # Начисление минимальной зарплаты сотрудникам, если за день все кассы 0
                if sch.position == 'Администратор':
                    sal_staff = param_gets('admin_min_payment')
                elif sch.position == 'Фотограф':
                    sal_staff = param_gets('phot_min_payment')
                elif sch.position == 'Универсальный фотограф':
                    sal_staff = param_gets('univ_min_payment')
                else:
                    error = ImplEvents.objects.create(
                        event_type='Salary_PositionError',
                        event_message=f"В графике {sch} не указана роль. Текущее значение => {sch.position}",
                        status='Бизнес ошибка',
                        solved='Нет'
                    )
                    print(f"ImplEvents - новая запись {error}")

            if sales_zak_admin_service.exists():
                # Кол-во заказов. Для начисления админу за сопровождения заказа.
                zak_count = sales_zak_admin_service.count()
                sal_staff += zak_count * param_gets('admin_order_service')

            # Update в БД
            salary, created = Salary.objects.update_or_create(
                store=sch.store,
                staff=sch.staff,
                date=day_date,
                defaults={'salary_sum': sal_staff, 'cash_box': cashbx_staff}
            )
            action = 'Добавлено' if created else 'Обновлено'
            print(f"sal_calc => {salary}; {action}")

            # Новая запись в системных событиях
            rec = ImplEvents.objects.create(
                event_type='Salary_Calculation',
                event_message=f"Произведен расчет зарплаты за {day_date} по сотруднику {sch.staff}. В БД {action}",
                status='Успешно'
            )
            print(f"ImplEvents - новая запись {rec}")


def sal_weekly_update(time_start, time_end):
    for start_week in start_week_generator(time_start, time_end):
        # Вычисляем конец недели (воскресенье)
        end_week = start_week + timedelta(days=6)
        salary_week = Salary.objects.filter(date__in=date_generator(start_week, end_week))
        if salary_week.exists():
            # Группируем по сотрудникам и суммируем зп
            sal_group = salary_week.values('staff').annotate(sal_sum=Sum('salary_sum')).annotate(cashbx_sum=Sum('cash_box'))
            for dic in sal_group:
                staff = Staff.objects.get(id=dic.get('staff'))
                salary = dic.get('sal_sum', 0)
                cashbx = dic.get('cashbx_sum', 0)
                withdrawn = CashWithdrawn.objects.filter(
                    staff=staff,
                    date__in=date_generator(start_week + timedelta(days=7), end_week + timedelta(days=7))
                )
                if withdrawn.exists():
                    withdrawn = withdrawn.aggregate(sum_cash=Sum('withdrawn'))['sum_cash']
                else:
                    withdrawn = 0

                # Update в БД
                salary_w, created = SalaryWeekly.objects.update_or_create(
                    staff=staff,
                    week_begin=start_week,
                    week_end=end_week,
                    defaults={'salary_sum': salary, 'cash_box_week': cashbx,
                              'cash_withdrawn': withdrawn, 'to_pay': salary - withdrawn}
                )
                action = 'Добавлено' if created else 'Обновлено'
                print(f"sal_weekly_update => {salary_w}; {action}")

                # Новая запись в системных событиях
                rec = ImplEvents.objects.create(
                    event_type='Salary_Weekly_Update',
                    event_message=f"В зарплаты за неделю занесены данные за период {start_week} - {end_week} "
                                  f"по сотруднику {staff}. В БД {action}",
                    status='Успешно'
                )
                print(f"ImplEvents - новая запись {rec}")


def fin_stats_calc(time_start, time_end):
    pass