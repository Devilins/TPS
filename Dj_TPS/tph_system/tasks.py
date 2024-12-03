from background_task import background
from django.utils import timezone
from .funcs import *


@background
def daily_salary_calculation():
    try:
        time_start = datetime.now().replace(hour=0, minute=1, second=0, microsecond=0)
        time_end = datetime.now()
        sal_calc(time_start, time_end)
        sal_weekly_update(time_start, time_end)

        rec = ImplEvents.objects.create(
            event_type='Job_sal_calc',
            event_message=f"Джоб подсчета зарплаты отработал за {datetime.now()}",
            status='Успешно'
        )
        print(f"ImplEvents - новая запись {rec}")
    except Exception as e:
        error = ImplEvents.objects.create(
            event_type='Job_sal_calc_Error',
            event_message=f"Ошибка при запуске джоба по расчету зарплат: {e}",
            status='Системная ошибка',
            solved='Нет'
        )
        print(f"ImplEvents - новая запись {error}")


# Запуск каждый день в 23:45 (Почему-то создает на 2:45 если использовать timezone. С datetime все ок.)
daily_salary_calculation(schedule=timezone.now().replace(hour=23, minute=45, second=0, microsecond=0), repeat=86400)


@background
def weekly_fin_calc():
    try:
        time_start = datetime.now().replace(hour=0, minute=1, second=0, microsecond=0) - timedelta(days=6)
        time_end = datetime.now()
        fin_stats_calc(time_start, time_end)
        fin_stats_staff_calc(time_start, time_end)

        rec = ImplEvents.objects.create(
            event_type='Job_fin_stats_calc',
            event_message=f"Джоб по финансовым отчетам отработал за {datetime.now()}",
            status='Успешно'
        )
        print(f"ImplEvents - новая запись {rec}")
    except Exception as e:
        error = ImplEvents.objects.create(
            event_type='Job_fin_stats_calc_Error',
            event_message=f"Ошибка при запуске джоба по финансовым отчетам: {e}",
            status='Системная ошибка',
            solved='Нет'
        )
        print(f"ImplEvents - новая запись {error}")


# Запуск каждую неделю в 23:50 (Почему-то создает на 2:45 если использовать timezone. С datetime все ок.)
weekly_fin_calc(schedule=timezone.now().replace(hour=23, minute=50, second=0, microsecond=0), repeat=86400 * 7)
