from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from tph_system.models import ImplEvents, Schedule, Staff


class Command(BaseCommand):
    help = ("Предлагает тип «Выездной» тем действующим сотрудникам, которые за последние дни стояли в графике "
            "с ролью «Выездной фотограф». Без --apply ничего не меняет.")

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=180, help='Глубина истории графика, дней (по умолчанию 180)')
        parser.add_argument('--apply', action='store_true', help='Проставить тип «Выездной»')

    def handle(self, *args, **options):
        since = timezone.localdate() - timedelta(days=options['days'])
        rows = (Schedule.objects
                .filter(position='Выездной фотограф', date__gte=since,
                        staff__dism_status='Работает', staff__staff_type='Штат')
                .values('staff_id').annotate(cnt=Count('id')).order_by('-cnt'))
        counts = {r['staff_id']: r['cnt'] for r in rows}
        staff_list = list(Staff.objects.filter(id__in=counts))
        staff_list.sort(key=lambda s: -counts[s.id])

        if not staff_list:
            self.stdout.write('Некого предлагать: подходящих сотрудников нет')
            return
        for s in staff_list:
            self.stdout.write(f'{s} (id={s.id}): смен выездным за период - {counts[s.id]}')

        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                f'Это только предложение ({len(staff_list)} чел.). Запустите с --apply, чтобы проставить тип '
                f'«Выездной»; оценку навыков нужно заполнить вручную.'))
            return
        for s in staff_list:
            s.staff_type = 'Выездной'
            s.save(update_fields=['staff_type', 'date_upd'])
        ImplEvents.objects.create(
            event_type='Schauto_Suggest_Types', status='Успешно', solved='Да',
            event_message='Тип «Выездной» проставлен: ' + ', '.join(str(s) for s in staff_list))
        self.stdout.write(self.style.SUCCESS(f'Тип «Выездной» проставлен: {len(staff_list)}'))
