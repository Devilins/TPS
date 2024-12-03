from django.core.management.base import BaseCommand
from tph_system.tasks import *


class Command(BaseCommand):
    help = 'Запускает ежедневную задачу расчета зарплаты'

    def handle(self, *args, **options):
        # Запускаем задачу
        daily_salary_calculation(schedule=datetime.now())
        # weekly_fin_calc(schedule=datetime.now())
        self.stdout.write(self.style.SUCCESS('Задача расчета зарплаты запущена'))
