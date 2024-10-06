from django.core.exceptions import ObjectDoesNotExist

from .models import *


def sal_calc(time_start, time_end):
    for day_date in range(time_start, time_end):
        for one_staff in Staff.objects.all():
            try:
                sales = Sales.get(date=day_date, staff=one_staff)
            except ObjectDoesNotExist:
                sales = None

