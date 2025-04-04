from django.core.management.base import BaseCommand

from tph_system.funcs import *


class Command(BaseCommand):
    help = 'Запускает генерацию QR кодов техники'

    def handle(self, *args, **kwargs):
        qr_generate_tech()

        self.stdout.write(self.style.SUCCESS(f'QR коды для техники сгенерированы успешно'))
