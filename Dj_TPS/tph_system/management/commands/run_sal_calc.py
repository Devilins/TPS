from django.core.management.base import BaseCommand

from tph_system.funcs import *


class Command(BaseCommand):
    help = 'Запускает расчет зарплаты'

    def add_arguments(self, parser):
        parser.add_argument('time_start', type=str, help='Начало периода')
        parser.add_argument('time_end', type=str, help='Конец периода')

    def handle(self, *args, **kwargs):
        ts = datetime.strptime(kwargs['time_start'], "%Y-%m-%d")
        te = datetime.strptime(kwargs['time_end'], "%Y-%m-%d")
        sal_calc(ts, te, None)

        self.stdout.write(self.style.SUCCESS(f'Зарплата подсчитана по дням c {ts} по {te}'))
