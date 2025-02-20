from django.core.management.base import BaseCommand

from tph_system.funcs import *


class Command(BaseCommand):
    help = 'Заполнение финансового отчета за месяцы, входящие в заданный период'

    def add_arguments(self, parser):
        parser.add_argument('time_start', type=str, help='Начало периода')
        parser.add_argument('time_end', type=str, help='Конец периода')

    def handle(self, *args, **kwargs):
        ts = datetime.strptime(kwargs['time_start'], "%Y-%m-%d")
        te = datetime.strptime(kwargs['time_end'], "%Y-%m-%d")
        fin_stats_calc(ts, te)
        fin_stats_staff_calc(ts, te)

        self.stdout.write(self.style.SUCCESS(f'Финансовая отчетность заполнена по месяцам c {ts} по {te}'))
