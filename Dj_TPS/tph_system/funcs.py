from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum, Q, Count

from .models import *

import qrcode
from PIL import Image, ImageDraw, ImageFont


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
    while start < end:
        yield start - timedelta(days=start.day - 1)
        start += relativedelta(months=1)


s = list(Settings.objects.values('param', 'value'))
print('INFO - Settings загружены')


def param_gets(par):
    suc = 0
    res = 0
    for i in s:
        if i['param'] == str(par):
            suc += 1
            res = int(i['value'])
    if suc == 0:
        error = ImplEvents.objects.create(
            event_type='Param_Gets_Error',
            event_message=f"Нет такого параметра в Настройках => {str(par)}. Для дальнейшей работы операции "
                          f"добавьте в Настройки новый параметр {str(par)} с нужным вам значением.",
            status='Системная ошибка',
            solved='Нет'
        )
        print(f"ImplEvents - новая запись {error}")
    elif suc > 1:
        error = ImplEvents.objects.create(
            event_type='Param_Gets_Error',
            event_message=f"В Настройках обнаружено {suc} одинаковых параметра {str(par)}. Для корректной работы операции "
                          f"нужно, чтобы параметр {str(par)} был Уникальным!",
            status='Системная ошибка',
            solved='Нет'
        )
        print(f"ImplEvents - новая запись {error}")

    return res


def dt_format(date):
    return date.strftime("%d.%m.%Y")


def sal_calc(time_start, time_end, one_staff_calc: Staff | None):  # Добавляем переменную с объектом сотрудник, или с его 'id'
    for day_date in date_generator(time_start, time_end):
        # Продажи за день без заказов
        sales_today = Sales.objects.filter(date=day_date).exclude(sale_type__in=['Заказной фотосет', 'Заказ выездной', 'Заказная видеосъемка'])

        if one_staff_calc:
            staff_sch = Schedule.objects.filter(date=day_date, staff=one_staff_calc)
        else:
            staff_sch = Schedule.objects.filter(date=day_date)
            # Если подсчет не по одному сотруднику, то оставляем фильтр без staff и загоняем все потом в for.

        for sch in staff_sch:
            cashbx_staff = 0  # Касса сотрудника за день
            sal_staff = 0  # Зарплата сотрудника за день

            # Все продажи сотрудника за день. Раскидываем на фотографа, админа и универсала и заказы.
            sales_ph = sales_today.filter(store=sch.store, photographer=sch.staff).exclude(staff=sch.staff)
            sales_adm = sales_today.filter(store=sch.store, staff=sch.staff).exclude(photographer=sch.staff)
            sales_univ = sales_today.filter(store=sch.store, staff=sch.staff, photographer=sch.staff)
            sales_zak = Sales.objects.filter(store=sch.store, date=day_date, photographer=sch.staff,
                                             sale_type__in=['Заказной фотосет', 'Заказ выездной', 'Заказная видеосъемка'])

            phot_in_store_cnt = len(Schedule.objects.filter(date=day_date, store=sch.store, position='Фотограф'))

            c_log = ''
            if sales_zak.exists():
                # Касса заказов
                cashbx_staff += int(sales_zak.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                c_log = c_log + 'Заказы: '
                for sl in sales_zak:
                    if sl.sale_type == 'Заказной фотосет':
                        # Проверка на выходные
                        if day_date.weekday() in (5, 6):
                            delta = float(sl.photo_count) * param_gets(str(sl.store.short_name) + '_order_ph_wknd')
                            sal_staff += delta
                            c_log = c_log + str(delta) + f' ({str(sl.photo_count)} * {param_gets(str(sl.store.short_name) + '_order_ph_wknd')}) + '
                        else:
                            delta = float(sl.photo_count) * param_gets(str(sl.store.short_name) + '_order_ph_budn')
                            sal_staff += delta
                            c_log = c_log + str(delta) + f' ({str(sl.photo_count)} * {param_gets(str(sl.store.short_name) + '_order_ph_budn')}) + '
                    elif sl.sale_type == 'Заказ выездной' and sch.position == 'Выездной фотограф':
                        pass  # Подсчет зп для выездных фотографов считается на 328 строчке. Тут только проверка роли.

                    elif sl.sale_type == 'Заказная видеосъемка' and sch.position == 'Видеограф':
                        delta = float(sl.photo_count) * param_gets('video_order_ph_out')
                        sal_staff += delta
                        c_log = c_log + 'Видеосъемка ' + str(delta) + f' ({str(sl.photo_count)} * {param_gets('video_order_ph_out')}) + '
                    else:
                        error = ImplEvents.objects.create(
                            event_type='Salary_PositionError',
                            event_message=f"В графике {sch} некорректно указана роль. Текущее значение => {sch.position}. "
                                          f"Влияет на расчет ЗП по {sl.sale_type}",
                            status='Бизнес ошибка',
                            solved='Нет'
                        )
                        print(f"ImplEvents - новая запись {error}")
                    # else:
                    #     error = ImplEvents.objects.create(
                    #         event_type='Salary_SaleTypeError',
                    #         event_message=f"В заказных продажах ошибка - sale_type ({sl.sale_type}) не соответствует "
                    #                       f"заданным типам "
                    #                       f"(Заказной фотосет или Заказ выездной), sale.id = {sl.id}; sale = {sl}",
                    #         status='Бизнес ошибка',
                    #         solved='Нет'
                    #     )
                    #     print(f"ImplEvents - новая запись {error}")

            if sales_univ.exists() and sales_adm.exists():
                # 1) Считаем общую кассу (sales_univ + sales_adm)
                # 2) Мин оплата добавляется в зависимости от порога от общей кассы
                # 3) ЗП Универсала от кассы универсала (без univ_min_payment)
                # 4) ЗП Админа от кассы админа (без admin_min_payment - если роль не Админ)
                #       Повышенный процент надо считать от общей кассы!
                cashbx_univ = int(sales_univ.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_adm = int(sales_adm.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_sum = cashbx_univ + cashbx_adm
                cashbx_staff += cashbx_sum
                counting_flag = False
                adm_pre_pay = None
                if sch.position == 'Универсальный фотограф':
                    c_log = c_log + 'Универсал + Админ: '
                    if cashbx_sum <= param_gets('univ_cashbx_min_bord'):
                        delta = param_gets('univ_min_payment')
                        sal_staff += delta
                        c_log = c_log + str(delta) + '(У) + '
                    else:
                        counting_flag = True
                elif sch.position == 'Администратор':
                    c_log = c_log + 'Админ + Универсал: '
                    adm_pre_pay = param_gets('admin_min_payment')
                    if cashbx_sum <= param_gets('admin_cashbx_min_border'):
                        delta = adm_pre_pay
                        sal_staff += delta
                        c_log = c_log + str(delta) + '(А) + '
                    else:
                        counting_flag = True

                if counting_flag:
                    # ЗП Универсала
                    delta = cashbx_univ * param_gets('univ_perc_payment') / 100
                    sal_staff += delta
                    c_log = c_log + str(delta) + f' ({str(cashbx_univ)} * {param_gets('univ_perc_payment') / 100})(У) + '

                    # ЗП Админа
                    if day_date.weekday() in (5, 6):  # Выходные
                        if cashbx_sum < param_gets('admin_cashbx_perc_border_wknd'):  # 20000
                            if not adm_pre_pay:
                                delta = cashbx_adm * param_gets('admin_stand_perc_pay_wknd') / 100  # 0.1
                                c_log = c_log + str(delta) + f' ({cashbx_adm} * {param_gets('admin_stand_perc_pay_wknd') / 100})(А) + '
                            else:
                                delta = adm_pre_pay + cashbx_adm * param_gets('admin_stand_perc_pay_wknd') / 100  # 0.1
                                c_log = c_log + str(delta) + f' ({adm_pre_pay} + {cashbx_adm} * {param_gets('admin_stand_perc_pay_wknd') / 100})(А) + '
                            sal_staff += delta
                        else:
                            delta = cashbx_adm * param_gets(str(sch.store.short_name) + '_admin_incr_perc_pay_wknd') / 100  # 0.17
                            sal_staff += delta
                            c_log = c_log + str(delta) + f' ({str(cashbx_adm)} * {param_gets(str(sch.store.short_name) + '_admin_incr_perc_pay_wknd') / 100})(А) + '
                    else:
                        if cashbx_sum < param_gets('admin_cashbx_perc_border_budn'):  # 10000
                            if not adm_pre_pay:
                                delta = cashbx_adm * param_gets('admin_stand_perc_pay_budn') / 100  # 0.1
                                c_log = c_log + str(delta) + f' ({cashbx_adm} * {param_gets('admin_stand_perc_pay_budn') / 100})(А) + '
                            else:
                                delta = adm_pre_pay + cashbx_adm * param_gets('admin_stand_perc_pay_budn') / 100  # 0.1
                                c_log = c_log + str(delta) + f' ({adm_pre_pay} + {cashbx_adm} * {param_gets('admin_stand_perc_pay_budn') / 100})(А) + '
                            sal_staff += delta
                        else:
                            delta = cashbx_adm * param_gets('admin_incr_perc_pay_budn') / 100  # 0.2
                            sal_staff += delta
                            c_log = c_log + str(delta) + f' ({str(cashbx_adm)} * {param_gets('admin_incr_perc_pay_budn') / 100})(А) + '

            elif sales_univ.exists():
                c_log = c_log + 'Универсал: '
                # Касса универсала
                cashbx_sum = int(sales_univ.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= param_gets('univ_cashbx_min_bord'):
                    delta = param_gets('univ_min_payment')
                    sal_staff += delta
                    c_log = c_log + str(delta) + ' + '
                else:
                    delta = cashbx_sum * param_gets('univ_perc_payment') / 100
                    sal_staff += delta
                    c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('univ_perc_payment') / 100}) + '

            elif sales_ph.exists():
                c_log = c_log + 'Фотограф: '
                # Касса фотографа
                cashbx_sum = int(sales_ph.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= param_gets('phot_cashbx_min_border'):
                    delta = param_gets('phot_min_payment')
                    sal_staff += delta
                    c_log = c_log + str(delta) + ' + '
                elif day_date.weekday() in (5, 6):  # Выходные
                    if cashbx_sum < param_gets('phot_cashbx_perc_border_wknd'):  # 15000
                        delta = cashbx_sum * param_gets('phot_stand_perc_pay_wknd') / 100  # 0.2
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('phot_stand_perc_pay_wknd') / 100}) + '
                    elif phot_in_store_cnt < param_gets('phot_count_incr_pay_if'):
                        delta = cashbx_sum * param_gets(str(sch.store.short_name) + '_phot_few_incr_perc_pay_wknd') / 100  # 0.23
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets(str(sch.store.short_name) + '_phot_few_incr_perc_pay_wknd') / 100}) + '
                    else:
                        delta = cashbx_sum * param_gets('phot_many_incr_perc_pay_wknd') / 100  # 0.25
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('phot_many_incr_perc_pay_wknd') / 100}) + '
                else:
                    if cashbx_sum < param_gets('phot_cashbx_perc_border_budn'):  # 10000
                        delta = cashbx_sum * param_gets('phot_stand_perc_pay_budn') / 100  # 0.2
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('phot_stand_perc_pay_budn') / 100}) + '
                    elif phot_in_store_cnt < param_gets('phot_count_incr_pay_if'):
                        delta = cashbx_sum * param_gets(str(sch.store.short_name) + '_phot_few_incr_perc_pay_budn') / 100  # 0.25
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets(str(sch.store.short_name) + '_phot_few_incr_perc_pay_budn') / 100}) + '
                    else:
                        delta = cashbx_sum * param_gets('phot_many_incr_perc_pay_budn') / 100  # 0.25
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('phot_many_incr_perc_pay_budn') / 100}) + '

            elif sales_adm.exists():
                c_log = c_log + 'Администратор: '
                # Касса администратора
                cashbx_sum = int(sales_adm.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                cashbx_staff += cashbx_sum

                if cashbx_sum <= param_gets('admin_cashbx_min_border'):
                    delta = param_gets('admin_min_payment')
                    sal_staff += delta
                    c_log = c_log + str(delta) + ' + '
                elif day_date.weekday() in (5, 6):  # Выходные
                    if cashbx_sum < param_gets('admin_cashbx_perc_border_wknd'):  # 20000
                        delta = param_gets('admin_min_payment') + cashbx_sum * param_gets('admin_stand_perc_pay_wknd') / 100  # 0.1
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({param_gets('admin_min_payment')} + {cashbx_sum} * {param_gets('admin_stand_perc_pay_wknd') / 100}) + '
                    else:
                        delta = cashbx_sum * param_gets(str(sch.store.short_name) + '_admin_incr_perc_pay_wknd') / 100  # 0.17
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets(str(sch.store.short_name) + '_admin_incr_perc_pay_wknd') / 100}) + '
                else:
                    if cashbx_sum < param_gets('admin_cashbx_perc_border_budn'):  # 10000
                        delta = param_gets('admin_min_payment') + cashbx_sum * param_gets('admin_stand_perc_pay_budn') / 100  # 0.1
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({param_gets('admin_min_payment')} + {cashbx_sum} * {param_gets('admin_stand_perc_pay_budn') / 100}) + '
                    else:
                        delta = cashbx_sum * param_gets('admin_incr_perc_pay_budn') / 100  # 0.2
                        sal_staff += delta
                        c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('admin_incr_perc_pay_budn') / 100}) + '

            if (not Sales.objects.filter(store=sch.store, date=day_date,
                                         photographer=sch.staff,
                                         sale_type__in=['Заказ выездной', 'Заказная видеосъемка']).exists()
                    and not sales_adm.exists() and not sales_ph.exists() and not sales_univ.exists()):
                c_log = c_log + 'Кассы 0, мин зп: '
                # Начисление минимальной зарплаты сотрудникам, если за день все кассы 0
                match sch.position:
                    case 'Администратор':
                        sal_staff += param_gets('admin_min_payment')
                        c_log = c_log + str(param_gets('admin_min_payment'))
                    case 'Фотограф':
                        sal_staff += param_gets('phot_min_payment')
                        c_log = c_log + str(param_gets('phot_min_payment'))
                    case 'Универсальный фотограф':
                        sal_staff += param_gets('univ_min_payment')
                        c_log = c_log + str(param_gets('univ_min_payment'))
                    case 'Видеограф':
                        pass
                    case 'Выездной фотограф':
                        pass
                    case _:
                        error = ImplEvents.objects.create(
                            event_type='Salary_PositionError',
                            event_message=f"В графике {sch} не указана роль. Текущее значение => {sch.position}. "
                                          f"Влияет на начисление минимальной зарплаты.",
                            status='Бизнес ошибка',
                            solved='Нет'
                        )
                        print(f"ImplEvents - новая запись {error}")

            if sch.position == 'Администратор':
                # Заказы, где сотрудник является только админом. Работает только для роли администратор
                sales_zak_admin_service = Sales.objects.filter(store=sch.store, date=day_date, staff=sch.staff,
                                                               sale_type__in=['Заказной фотосет', 'Заказ выездной', 'Заказная видеосъемка']
                                                               ).exclude(photographer=sch.staff)
                if sales_zak_admin_service.exists():
                    c_log = c_log + 'Админу за сопровождение заказов: '
                    # Кол-во заказов. Для начисления админу за сопровождения заказа.
                    zak_count = sales_zak_admin_service.count()
                    delta = zak_count * param_gets('admin_order_service')
                    sal_staff += delta
                    c_log = c_log + str(delta) + f' ({zak_count} * {param_gets('admin_order_service')}) + '

            if sch.position == 'Выездной фотограф':
                # Отдельно считается ЗП для выездных фотографов.
                sales_order_zak = Sales.objects.filter(store=sch.store, date=day_date, photographer=sch.staff, sale_type='Заказ выездной')
                sales_ph_order = sales_ph.exclude(sale_type='Исходники заказа')
                sales_univ_order = sales_univ.exclude(sale_type='Исходники заказа')
                cashbx_staff = 0
                sal_staff = 0

                c_log = 'Выездной фотограф: '
                if sales_order_zak.exists():
                    cashbx_staff += int(sales_order_zak.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                    for sl in sales_order_zak:
                        if day_date.weekday() in (5, 6):  # Выходные
                            sal_staff += float(sl.photo_count) * param_gets('order_ph_out_wknd')
                            c_log = c_log + str(sal_staff) + f' ({str(sl.photo_count)} * {param_gets('order_ph_out_wknd')}) + '
                        else:  # Будни
                            sal_staff += float(sl.photo_count) * param_gets('order_ph_out_budn')
                            c_log = c_log + str(sal_staff) + f' ({str(sl.photo_count)} * {param_gets('order_ph_out_budn')}) + '

                        # ------Старый подсчет, который зависит от кол-ва часов в заказе.
                        # if sl.photo_count >= 2:
                        #     sal_staff += float(sl.photo_count) * param_gets('order_ph_out_less')
                        #     c_log = c_log + str(sal_staff) + f' ({str(sl.photo_count)} * {param_gets('order_ph_out_less')}) + '
                        # else:
                        #     sal_staff += float(sl.photo_count) * param_gets('order_ph_out')
                        #     c_log = c_log + str(sal_staff) + f' ({str(sl.photo_count)} * {param_gets('order_ph_out')}) + '

                if sales_ph_order.exists():
                    c_log = c_log + 'Фотограф(В): '
                    # Касса фотографа выездного
                    cashbx_sum = int(sales_ph_order.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                    cashbx_staff += cashbx_sum

                    if day_date.weekday() in (5, 6):  # Выходные
                        if cashbx_sum <= param_gets('phot_cashbx_perc_border_wknd'):  # 15000
                            delta = cashbx_sum * param_gets('phot_stand_perc_pay_wknd') / 100  # 0.2
                            sal_staff += delta
                            c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('phot_stand_perc_pay_wknd') / 100}) + '
                        else:
                            delta = cashbx_sum * param_gets(str(sch.store.short_name) + '_phot_few_incr_perc_pay_wknd') / 100  # 0.23
                            sal_staff += delta
                            c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets(str(sch.store.short_name) + '_phot_few_incr_perc_pay_wknd') / 100}) + '
                    else:
                        if cashbx_sum <= param_gets('phot_cashbx_perc_border_budn'):  # 10000
                            delta = cashbx_sum * param_gets('phot_stand_perc_pay_budn') / 100  # 0.2
                            sal_staff += delta
                            c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('phot_stand_perc_pay_budn') / 100}) + '
                        else:
                            delta = cashbx_sum * param_gets(str(sch.store.short_name) + '_phot_few_incr_perc_pay_budn') / 100  # 0.25
                            sal_staff += delta
                            c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets(str(sch.store.short_name) + '_phot_few_incr_perc_pay_budn') / 100}) + '

                if sales_univ_order.exists():
                    c_log = c_log + 'Универсал(В): '
                    # Касса универсала выездного
                    cashbx_sum = int(sales_univ.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
                    cashbx_staff += cashbx_sum
                    # Расчет
                    delta = cashbx_sum * param_gets('univ_perc_payment') / 100
                    sal_staff += delta
                    c_log = c_log + str(delta) + f' ({str(cashbx_sum)} * {param_gets('univ_perc_payment') / 100}) + '

            # Оформление логов расчета
            if c_log[-2] == '+':
                c_log = c_log[:len(c_log)-3:]

            # Update в БД
            salary, created = Salary.objects.update_or_create(
                store=sch.store,
                staff=sch.staff,
                date=day_date,
                defaults={'salary_sum': sal_staff, 'cash_box': cashbx_staff, 'cnt_logs': c_log}
            )
            action = 'Добавлено' if created else 'Обновлено'
            print(f"sal_calc => {salary}; {action}")

            # Новая запись в системных событиях
            ImplEvents.objects.create(
                event_type='Salary_Calculation',
                event_message=f"Произведен расчет зарплаты за {dt_format(day_date)} по сотруднику {sch.staff} ({sch.position}).\n"
                              f"Зарплата: {sal_staff}, Касса: {cashbx_staff}.\nВ БД {action}.\nЛог расчета -> {c_log}",
                status='Успешно'
            )


def sal_weekly_update(time_start, time_end, one_staff_calc: Staff | None):
    for start_week in start_week_generator(time_start, time_end):
        # Вычисляем конец недели (воскресенье)
        end_week = start_week + timedelta(days=6)

        # Проверка на правильное заполнение CashWithdrawn всеми сотрудниками за нужный период +- 2 недели
        per_withdrawn = CashWithdrawn.objects.filter(
            date__in=date_generator(start_week - timedelta(days=14), end_week + timedelta(days=14)),
            week_beg_rec=None
        )
        if per_withdrawn.exists():
            error = ImplEvents.objects.create(
                event_type='Week_Beg_Rec_Empty',
                event_message=f"В Зарплатах Наличными сотрудники не указали неделю, за которую забрали ЗП. "
                              f"Влияет на начисление зарплаты. Кол-во неправильных записей - {per_withdrawn.count()}. "
                              f"Список записей - {per_withdrawn}",
                status='Бизнес ошибка',
                solved='Нет'
            )
            print(f"ImplEvents - новая запись {error}")

        if one_staff_calc:
            salary_week = Salary.objects.filter(date__in=date_generator(start_week, end_week), staff=one_staff_calc)
        else:
            salary_week = Salary.objects.filter(date__in=date_generator(start_week, end_week))

        if salary_week.exists():
            # Группируем по сотрудникам и суммируем зп
            sal_group = salary_week.values('staff').annotate(sal_sum=Sum('salary_sum')).annotate(
                cashbx_sum=Sum('cash_box'))
            for dic in sal_group:
                staff = Staff.objects.get(id=dic.get('staff'))
                salary = dic.get('sal_sum', 0)
                cashbx = dic.get('cashbx_sum', 0)
                withdrawn = CashWithdrawn.objects.filter(
                    staff=staff,
                    week_beg_rec=start_week
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
                    event_message=f"В зарплаты за неделю занесены данные за период {dt_format(start_week)} - {dt_format(end_week)} "
                                  f"по сотруднику {staff}.\nЗарплата за неделю: {salary}, Вычеты ЗП наличными: {withdrawn}, Касса за неделю: {cashbx}.\nВ БД {action}",
                    status='Успешно'
                )
        else:
            error = ImplEvents.objects.create(
                event_type='Salary_Weekly_Update_Empty',
                event_message=f"В зарплаты за неделю данные НЕ занесены, потому что за период {dt_format(start_week)} - {dt_format(end_week)} "
                              f"нет записей с зарплатами по дням.",
                status='Бизнес ошибка',
                solved='Нет'
            )
            print(f"ImplEvents - новая запись {error}")


def fin_stats_calc(time_start, time_end):
    for start_month in start_month_generator(time_start, time_end):
        # Вычисляем конец месяца
        end_month = start_month + relativedelta(months=1) - relativedelta(days=1)
        # Расчеты за месяц
        sales = Sales.objects.filter(date__gte=start_month, date__lte=end_month)
        salary = Salary.objects.filter(date__gte=start_month, date__lte=end_month)
        if sales.exists() or salary.exists():
            cashboxes = int(sales.aggregate(cashbx_sum=Sum('sum'))['cashbx_sum'])
            salaries = int(salary.aggregate(sal_sum=Sum('salary_sum'))['sal_sum'])
            profit = cashboxes - salaries

            # Update в БД
            fin_stats, created = FinStatsMonth.objects.update_or_create(
                date=start_month,
                defaults={'revenue': cashboxes, 'salaries': salaries, 'profit': profit}
            )
            action = 'Добавлено' if created else 'Обновлено'
            print(f"fin_stats_calc => {fin_stats}; {action}")

            # Новая запись в системных событиях
            rec = ImplEvents.objects.create(
                event_type='FinStatsMonth_Update',
                event_message=f"В финансовые отчеты по компании занесены данные за период {dt_format(start_month)} - {dt_format(end_month)}.\n"
                              f"В БД {action}",
                status='Успешно'
            )
        else:
            error = ImplEvents.objects.create(
                event_type='FinStatsMonth_Update_Empty',
                event_message=f"В финансовые отчеты по компании данные НЕ занесены, потому что за период {dt_format(start_month)} - {dt_format(end_month)} "
                              f"нет записей с зарплатами по дням и продажами.",
                status='Бизнес ошибка',
                solved='Нет'
            )
            print(f"ImplEvents - новая запись {error}")


def fin_stats_staff_calc(time_start, time_end):
    for start_month in start_month_generator(time_start, time_end):
        # Вычисляем конец месяца
        end_month = start_month + relativedelta(months=1) - relativedelta(days=1)
        # Расчеты за месяц
        salary_month = Salary.objects.filter(date__in=date_generator(start_month, end_month))
        if salary_month.exists():
            # Группируем по сотрудникам и суммируем зп
            sal_group = salary_month.values('staff').annotate(sal_sum=Sum('salary_sum')).annotate(
                cashbx_sum=Sum('cash_box'))
            for dic in sal_group:
                staff = Staff.objects.get(id=dic.get('staff'))
                salary = dic.get('sal_sum', 0)
                cashbx = dic.get('cashbx_sum', 0)

                # Update в БД
                fin_stats, created = FinStatsStaff.objects.update_or_create(
                    date=start_month,
                    staff=staff,
                    defaults={'cash_box': cashbx, 'salary': salary}
                )
                action = 'Добавлено' if created else 'Обновлено'
                print(f"fin_stats_calc => {fin_stats}; {action}")

                # Новая запись в системных событиях
                rec = ImplEvents.objects.create(
                    event_type='FinStatsStaff_Update',
                    event_message=f"В финансовые отчеты по сотрудникам занесены данные за период {dt_format(start_month)} - {dt_format(end_month)}.\n"
                                  f"Сотрудник - {staff}.\nВ БД {action}",
                    status='Успешно'
                )
        else:
            error = ImplEvents.objects.create(
                event_type='FinStatsStaff_Update_Empty',
                event_message=f"В финансовые отчеты по сотрудникам данные НЕ занесены, потому что за период {dt_format(start_month)} - {dt_format(end_month)} "
                              f"нет записей с зарплатами по дням.",
                status='Бизнес ошибка',
                solved='Нет'
            )
            print(f"ImplEvents - новая запись {error}")


def reports_list_update(time_start, time_end):
    for day_date in date_generator(time_start, time_end):
        now_day_sch = Schedule.objects.filter(date=day_date).values('store').annotate(cnt=Count('id'))
        if now_day_sch:
            for st_id in now_day_sch:
                store = Store.objects.get(id=st_id['store'])
                cashbx = Sales.objects.filter(date=day_date, store=store).aggregate(cashbx_sum=Sum('sum'))['cashbx_sum']

                if not cashbx:
                    cashbx = 0

                # Update в БД
                rep, created = CheckReports.objects.update_or_create(
                    store=store,
                    date=day_date,
                    defaults={'sum_cashbox': cashbx}
                )
                action = 'Добавлено' if created else 'Обновлено'
                print(f"reports_list_update => {rep}; {action}")

                # Новая запись в системных событиях
                rec = ImplEvents.objects.create(
                    event_type='CheckReports_Update',
                    event_message=f"Обновление отчетов за период {dt_format(time_start)} - {dt_format(time_end)}.\n"
                                  f"Точка - {store}.\nВ БД {action}",
                    status='Успешно'
                )


def qr_generate_tech():
    tech = Tech.objects.filter(name__icontains='Тушка')
    tech = tech.union(Tech.objects.filter(name__icontains='Объектив'))
    tech = list(tech.union(Tech.objects.filter(name__icontains='Вспышка')))
    for t in tech:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=1,
        )

        qr.add_data(f'https://takephoto-erp.ru/tech/{t.id}/update')
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # RGB (для работы с текстом)
        img = img.convert("RGB")

        # Текст подписи (многострочный)
        name = t.name.split(sep=" ", maxsplit=2)
        text = f"{name[0]} {name[1]}\n{name[2]}\n{t.serial_num}"

        # Параметры шрифта
        font_size = 35  # Размер шрифта
        font_path = 'C:/Windows/Fonts/Arial/arial.ttf'  # Путь к шрифту (должен поддерживать кириллицу)

        # Загружаем шрифт
        try:
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            print("Шрифт не найден, используется стандартный.")
            font = ImageFont.load_default()

        # Вычисляем размеры текста
        draw = ImageDraw.Draw(img)
        text_width = max(draw.textlength(line, font=font) for line in text.split("\n")) + 20
        text_height = sum(font.getbbox(line)[3] - font.getbbox(line)[1] for line in text.split("\n"))

        # Отступы
        padding = 0  # Отступ между QR-кодом и текстом
        line_spacing = 10  # Расстояние между строками текста

        # Создаем новое изображение с местом для текста
        qr_width, qr_height = img.size
        new_height = qr_height + padding + text_height + (len(text.split("\n")) - 1) * line_spacing + 20
        new_img = Image.new("RGB", (max(qr_width, int(text_width)), new_height), "white")

        # Вставляем QR-код в новое изображение
        new_img.paste(img, ((new_img.width - qr_width) // 2, 0))

        # Рисуем текст
        draw = ImageDraw.Draw(new_img)
        y_text = qr_height + padding  # Начальная позиция текста по вертикали

        for line in text.split("\n"):
            # Вычисляем ширину текущей строки
            line_width = draw.textlength(line, font=font)
            # Позиция текста по горизонтали (центрирование)
            x_text = (new_img.width - line_width) // 2
            # Рисуем строку
            draw.text((x_text, y_text), line, fill="black", font=font)
            # Обновляем позицию для следующей строки
            y_text += font.getbbox(line)[3] - font.getbbox(line)[1] + line_spacing

        # Сохраняем результат
        new_img.save(f"QR_Codes_Tech/QR_{t.name}_{t.serial_num}.png")
