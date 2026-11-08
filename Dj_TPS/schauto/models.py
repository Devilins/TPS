from datetime import date, datetime, time

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from tph_system.models import Staff, Store

from .parsers import PEOPLE_SEPARATOR, split_parts


class Venue(models.Model):
    """Центр, в который ездят выездные фотографы (в т.ч. центры, где нет штатной фототочки).

    Намеренно отдельно от tph_system.Store: Store - фототочка со штатом и своими параметрами ЗП,
    Venue - любой центр из таблицы заказов. Если в центре есть фототочка, она указывается в `store`.
    """

    BRAND_CHOICES = (
        ('LL', 'Laserland'),
        ('JJ', 'Joki Joya'),
        ('OT', 'Другой центр'),  # куда ездят по выездам, но своего листа в таблицах нет (например, "ТРЦ Город")
    )
    name = models.CharField(max_length=60, unique=True, verbose_name="Название центра")
    brand = models.CharField(max_length=2, choices=BRAND_CHOICES, verbose_name="Бренд")
    address = models.CharField(max_length=200, blank=True, verbose_name="Адрес",
                               help_text="Нужен для расчёта маршрутов и ссылок в карты: метро/улица, дом, торговый центр")
    difficulty = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(10)],
                                                  verbose_name="Сложность точки (1-10)")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
                              limit_choices_to={'store_status': 'Действующая'}, verbose_name="Фототочка в ERP")
    # Лист ищется в таблице бренда центра (у Laserland и Joki Joya таблицы разные), поэтому ключ - (brand, лист)
    sheet_tab_name = models.CharField(max_length=60, blank=True, verbose_name="Лист в Google-таблице бренда")
    is_active = models.BooleanField(default=True, verbose_name="Участвует в планировании")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name="Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT, related_name='+',
                                    verbose_name="Кем было изменено")

    class Meta:
        verbose_name = 'Центры'
        verbose_name_plural = 'Центры'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['brand', 'sheet_tab_name'], condition=~Q(sheet_tab_name=''),
                                    name='uniq_schauto_venue_brand_tab'),
        ]

    def __str__(self):
        return self.name


class Route(models.Model):
    """Вариант маршрута на общественном транспорте между двумя центрами (направленный).

    Вариантов на пару может быть несколько (метро, электричка, ...) - различаются `description`.
    Планировщик берёт минимальный `duration_min` из вариантов пары.
    """

    from_venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='routes_from', verbose_name="Откуда")
    to_venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='routes_to', verbose_name="Куда")
    description = models.CharField(max_length=120, blank=True, verbose_name="Вариант маршрута")
    duration_min = models.PositiveSmallIntegerField(validators=[MaxValueValidator(600)],
                                                    verbose_name="Время в пути, мин")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name="Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT, related_name='+',
                                    verbose_name="Кем было изменено")

    class Meta:
        verbose_name = 'Маршруты'
        verbose_name_plural = 'Маршруты'
        ordering = ['from_venue__name', 'to_venue__name', 'duration_min']
        constraints = [
            models.UniqueConstraint(fields=['from_venue', 'to_venue', 'description'], name='uniq_schauto_route_variant'),
            models.CheckConstraint(condition=~Q(from_venue=F('to_venue')), name='schauto_route_not_to_itself'),
        ]

    def __str__(self):
        return f'{self.from_venue} -> {self.to_venue}: {self.duration_min} мин'


class VenueAlias(models.Model):
    """Фрагмент адреса из листа "ВЫЕЗДЫ" -> центр. Хранится в нормализованном виде (parsers.norm_place)."""

    fragment = models.CharField(max_length=100, unique=True, verbose_name="Фрагмент адреса")
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='aliases', verbose_name="Центр")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name="Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT, related_name='+',
                                    verbose_name="Кем было изменено")

    class Meta:
        verbose_name = 'Адреса выездов'
        verbose_name_plural = 'Адреса выездов'
        ordering = ['venue__name', 'fragment']

    def __str__(self):
        return f'«{self.fragment}» -> {self.venue}'


class StaffAlias(models.Model):
    """Как сотрудник записан в ячейках "Фотограф"/"Ретушер" ("Даша И", "Катя Львова"). Хранится в нормализованном виде.

    Пустой `staff` означает "это не сотрудник, игнорировать" (пометки вроде "ищем").
    """

    alias = models.CharField(max_length=60, unique=True, verbose_name="Имя в таблице")
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
                              verbose_name="Сотрудник")
    date_upd = models.DateTimeField(auto_now=True, editable=False, blank=True, verbose_name="Дата изменения")
    user_edited = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT, related_name='+',
                                    verbose_name="Кем было изменено")

    class Meta:
        verbose_name = 'Имена сотрудников в таблицах'
        verbose_name_plural = 'Имена сотрудников в таблицах'
        ordering = ['alias']

    def __str__(self):
        return f'«{self.alias}» -> {self.staff or "игнорировать"}'


class PhotoOrder(models.Model):
    """Заказ из строки Google-таблицы. Персональных данных клиента здесь нет (заказчик, телефон, именинник, ссылки)."""

    STATUS_OPEN = 'open'
    STATUS_ASSIGNED = 'assigned'
    STATUS_NEEDS_FIX = 'needs_fix'
    STATUS_GONE = 'gone'
    STATUS_CHOICES = (
        (STATUS_OPEN, 'Нужен исполнитель'),
        (STATUS_ASSIGNED, 'Исполнитель указан в таблице'),
        (STATUS_NEEDS_FIX, 'Нужна ручная правка'),
        (STATUS_GONE, 'Пропал из таблицы'),
    )
    SOURCE_BRANDS = (('LL', 'Laserland'), ('JJ', 'Joki Joya'))

    brand = models.CharField(max_length=2, choices=SOURCE_BRANDS, verbose_name="Таблица")
    tab_name = models.CharField(max_length=60, verbose_name="Лист")
    sheet_gid = models.BigIntegerField(null=True, blank=True, verbose_name="gid листа")
    sheet_row = models.PositiveIntegerField(verbose_name="Строка в листе")
    fingerprint = models.CharField(max_length=32, verbose_name="Отпечаток строки")

    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, null=True, blank=True, related_name='orders',
                              verbose_name="Центр")
    place_raw = models.CharField(max_length=120, blank=True, verbose_name="Адрес из таблицы (центр не определён)")

    date = models.DateField(verbose_name="Дата")
    time_start = models.TimeField(null=True, blank=True, verbose_name="Начало")
    time_end = models.TimeField(null=True, blank=True, verbose_name="Конец")
    # Все интервалы заказа как в таблице: [["14:00","15:00"],["15:30","16:30"]]; time_start/time_end - границы всего заказа
    slots = models.JSONField(default=list, blank=True, verbose_name="Интервалы")
    extra_minutes = models.PositiveSmallIntegerField(default=0, verbose_name="Продление, мин")
    raw_time = models.CharField(max_length=60, blank=True, verbose_name="Время как в таблице")
    notes = models.CharField(max_length=200, blank=True, verbose_name="Замечания разбора")

    photographer_raw = models.CharField(max_length=120, blank=True, verbose_name="Фотограф в таблице")
    retoucher_raw = models.CharField(max_length=60, blank=True, verbose_name="Ретушёр в таблице")
    photographer = models.ForeignKey(Staff, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
                                     verbose_name="Фотограф")
    # Заказ с перерывом могут снимать двое: в ячейке «Роман + Лиза Гужвенко». Тогда `photographer` пуст, а сопоставленные с
    # сотрудниками люди лежат здесь. У заказа с одним исполнителем это поле пусто - он в `photographer`.
    photographers = models.ManyToManyField(Staff, blank=True, related_name='+', verbose_name="Фотографы (если их несколько)")
    retoucher = models.ForeignKey(Staff, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
                                  verbose_name="Ретушёр")
    no_retouch = models.BooleanField(default=False, verbose_name="Ретушь не нужна (исходники)")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN, verbose_name="Статус")
    first_seen_at = models.DateTimeField(auto_now_add=True, verbose_name="Впервые загружен")
    last_seen_at = models.DateTimeField(verbose_name="Последний раз виден в таблице")

    class Meta:
        verbose_name = 'Заказы выездных'
        verbose_name_plural = 'Заказы выездных'
        ordering = ['date', 'time_start', 'venue__name']
        constraints = [
            models.UniqueConstraint(fields=['brand', 'tab_name', 'fingerprint'], name='uniq_schauto_order_row'),
        ]
        indexes = [
            models.Index(fields=['date', 'status']),
            models.Index(fields=['venue', 'date']),
        ]
        permissions = (("import_orders", "Загрузка заказов из Google-таблиц и сопоставление имён и адресов"),)

    def __str__(self):
        return f'{self.date} {self.time_start or "?"} {self.venue or self.place_raw or "?"}'

    @property
    def slot_times(self) -> list[tuple[time, time]]:
        """Интервалы заказа; для заказов, загруженных до появления `slots`, - один интервал от начала до конца"""
        if self.slots:
            return [(time.fromisoformat(a), time.fromisoformat(b)) for a, b in self.slots]
        return [(self.time_start, self.time_end)] if self.time_start and self.time_end else []

    @property
    def intervals_display(self) -> str:
        """Полное время заказа: "14:00-15:00, 15:30-16:30" (а не от первого начала до последнего конца)"""
        return ', '.join(f'{a:%H:%M}-{b:%H:%M}' for a, b in self.slot_times)

    @property
    def parts(self) -> list[list[tuple[time, time]]]:
        """Части заказа, которые можно отдать разным фотографам (перерыв между интервалами от SPLIT_GAP_MINUTES)"""
        return split_parts(self.slot_times)

    @property
    def can_split(self) -> bool:
        return len(self.parts) > 1

    @property
    def duration_minutes(self) -> int | None:
        """Время работы: сумма интервалов (перерывы не считаются) плюс продление; None, если время не распознано"""
        slots = self.slot_times
        if not slots:
            return None
        total = sum((datetime.combine(date.min, b) - datetime.combine(date.min, a)).seconds // 60 for a, b in slots)
        return total + self.extra_minutes

    @property
    def people(self) -> list[str]:
        """Имена из ячейки «Фотограф» (после очистки): один человек или несколько, снимающих заказ с перерывом"""
        return [name for name in self.photographer_raw.split(PEOPLE_SEPARATOR) if name]

    @property
    def people_matched(self) -> bool:
        """Все названные в ячейке люди сопоставлены с сотрудниками (для списка заказов берите заказы с prefetch_related('photographers'))"""
        names = self.people
        if not names:
            return False
        if len(names) == 1:
            return self.photographer_id is not None
        return len(self.photographers.all()) >= len(names)

    @property
    def sheet_url(self) -> str:
        sheet_id = settings.SCHAUTO_SHEET_IDS.get(self.brand, '')
        if not sheet_id or self.sheet_gid is None:
            return ''
        return f'https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={self.sheet_gid}&range=A{self.sheet_row}'


class PlanRun(models.Model):
    """Распределение заказов выездным фотографам за период (результат одного расчёта).

    Хранится целиком вместе с объяснениями: то, что руководитель увидел на экране, можно потом применить без пересчёта.
    Черновик можно править (менять исполнителей), затем применить: проверка -> запись в таблицы -> запись в график (`Schedule`).
    Если часть записей не удалась, расчёт остаётся «частично применённым», и применение можно повторить - оно идемпотентно.
    """

    STATUS_DRAFT = 'draft'
    STATUS_APPLYING = 'applying'   # идёт применение; защита от двойного нажатия
    STATUS_ROLLING_BACK = 'rolling_back'   # идёт откат
    STATUS_APPLIED = 'applied'
    STATUS_PARTIAL = 'partial'
    STATUS_CHOICES = (
        (STATUS_DRAFT, 'Черновик'),
        (STATUS_APPLYING, 'Применяется'),
        (STATUS_ROLLING_BACK, 'Откатывается'),
        (STATUS_APPLIED, 'Применён'),
        (STATUS_PARTIAL, 'Применён частично'),
    )

    date_from = models.DateField(verbose_name="Период с")
    date_to = models.DateField(verbose_name="Период по")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT, verbose_name="Статус")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Рассчитан")
    created_by = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT, related_name='+',
                                   verbose_name="Кем рассчитан")
    config = models.JSONField(default=dict, blank=True, verbose_name="Параметры планировщика")
    summary = models.JSONField(default=dict, blank=True, verbose_name="Итоги")
    warnings = models.JSONField(default=list, blank=True, verbose_name="Предупреждения")
    # Заказы, назначенные вручную в таблице и учтённые как занятость: [{staff, date, start, end, venue, order_id}]
    fixed = models.JSONField(default=list, blank=True, verbose_name="Назначено вручную (учтено)")
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name="Применён")
    applied_by = models.ForeignKey(User, blank=True, null=True, on_delete=models.PROTECT, related_name='+',
                                   verbose_name="Кем применён")
    apply_log = models.JSONField(default=list, blank=True, verbose_name="Итоги применений")
    # Проблемы проверки, которые руководитель подтвердил вручную (фотограф успеет): {подпись проблемы: {text, by, at}}.
    # Подпись включает фотографа, части и цифры (нужно/есть минут), так что изменившаяся ситуация подтверждение отменяет
    confirmed = models.JSONField(default=dict, blank=True, verbose_name="Подтверждено вручную")

    @property
    def editable(self) -> bool:
        """Исполнителей можно менять, пока расчёт не применён целиком и не применяется прямо сейчас"""
        return self.status in (self.STATUS_DRAFT, self.STATUS_PARTIAL)

    @property
    def deletable(self) -> bool:
        """Удалить можно черновик, по которому ничего не вписано в таблицы (в том числе после отката применения).
        Применённый, частично применённый, применяемый или откатываемый расчёт удалять нельзя: от него зависит откат"""
        return self.status == self.STATUS_DRAFT and not self.assignments.filter(sheet_status__in=('written', 'already')).exists()

    @property
    def rollbackable(self) -> bool:
        """Откатить можно применённый (в т.ч. частично) расчёт, если в таблицы уже что-то вписано"""
        return (self.status in (self.STATUS_APPLIED, self.STATUS_PARTIAL)
                and self.assignments.filter(sheet_status__in=('written', 'already')).exists())

    class Meta:
        verbose_name = 'Расчёты распределения'
        verbose_name_plural = 'Расчёты распределения'
        ordering = ['-created_at']
        permissions = (("run_planning", "Расчёт распределения заказов выездным фотографам"),)

    def __str__(self):
        return f'Распределение {self.date_from:%d.%m.%Y}-{self.date_to:%d.%m.%Y} от {self.created_at:%d.%m.%Y %H:%M}'


class Assignment(models.Model):
    """Часть заказа в расчёте: кому отдана (или `staff` пусто - нераспределена) и почему"""

    SCHEDULE_CHOICES = (
        ('', 'Не записывалось'),
        ('created', 'Запись в график создана'),
        ('exists', 'Запись в графике уже была'),
        ('no_store', 'Нет фототочки в ERP - в график не пишем'),
    )

    plan = models.ForeignKey(PlanRun, on_delete=models.CASCADE, related_name='assignments', verbose_name="Расчёт")
    order = models.ForeignKey(PhotoOrder, on_delete=models.CASCADE, related_name='assignments', verbose_name="Заказ")
    part_no = models.PositiveSmallIntegerField(default=1, verbose_name="Часть заказа")
    parts_total = models.PositiveSmallIntegerField(default=1, verbose_name="Частей в заказе")
    date = models.DateField(verbose_name="Дата")
    start_min = models.PositiveSmallIntegerField(verbose_name="Начало, мин от полуночи")
    end_min = models.PositiveSmallIntegerField(verbose_name="Конец с продлением, мин от полуночи")
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
                              verbose_name="Исполнитель")
    auto_staff = models.ForeignKey(Staff, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
                                   verbose_name="Предложено расчётом")
    need = models.FloatField(default=0, verbose_name="Сложность части заказа")
    cost = models.FloatField(default=0, verbose_name="Штраф по навыку и знанию центра")
    candidates = models.PositiveSmallIntegerField(default=0, verbose_name="Подходило фотографов")
    reasons = models.JSONField(default=list, blank=True, verbose_name="Почему этот исполнитель")
    alternatives = models.JSONField(default=list, blank=True, verbose_name="Лучшие замены")
    rejected = models.JSONField(default=list, blank=True, verbose_name="Кто не подходит и почему")
    # Применение: что и куда уже записано (повторное применение пропускает сделанное)
    schedule_status = models.CharField(max_length=10, blank=True, default='', choices=SCHEDULE_CHOICES,
                                       verbose_name="Запись в график")
    schedule = models.ForeignKey('tph_system.Schedule', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name="Запись в графике")
    sheet_status = models.CharField(max_length=12, blank=True, default='', verbose_name="Запись в таблицу")
    sheet_detail = models.CharField(max_length=200, blank=True, default='', verbose_name="Подробности записи в таблицу")
    # Что было в ячейке «Фотограф» до записи и что стало: по этому откат возвращает ячейку точно, не трогая чужие правки
    sheet_before = models.TextField(blank=True, default='', verbose_name="Ячейка в таблице до записи")
    sheet_after = models.TextField(blank=True, default='', verbose_name="Ячейка в таблице после записи")
    # Столбец «Ретушер» (Joki Joya): фотограф, который обрабатывает фото сам, вписывается и туда
    ret_status = models.CharField(max_length=12, blank=True, default='', verbose_name="Запись в «Ретушер»")
    ret_before = models.TextField(blank=True, default='', verbose_name="«Ретушер» до записи")
    ret_after = models.TextField(blank=True, default='', verbose_name="«Ретушер» после записи")

    class Meta:
        verbose_name = 'Назначения в расчёте'
        verbose_name_plural = 'Назначения в расчёте'
        ordering = ['date', 'start_min', 'order_id', 'part_no']
        constraints = [
            models.UniqueConstraint(fields=['plan', 'order', 'part_no'], name='uniq_schauto_assignment_part'),
        ]

    def __str__(self):
        return f'{self.date} {self.time_display} -> {self.staff or "не распределён"}'

    @property
    def is_done(self) -> bool:
        """Исполнитель уже вписан в таблицу"""
        return self.sheet_status in ('written', 'already')

    @property
    def edited(self) -> bool:
        return self.staff_id != self.auto_staff_id

    SHEET_STATUS_LABELS = {
        'written': 'вписан в таблицу', 'already': 'уже был в таблице', 'conflict': 'конфликт: в таблице другой исполнитель',
        'not_found': 'строка не найдена в таблице', 'changed': 'заказ в таблице изменился', 'error': 'ошибка записи в таблицу',
    }

    @property
    def sheet_status_display(self) -> str:
        return self.SHEET_STATUS_LABELS.get(self.sheet_status, '')

    RET_STATUS_LABELS = {
        'written': 'ретушёр: вписан сам фотограф', 'already': 'ретушёр: имя уже стояло', 'other': 'ретушёр уже был указан - оставлен',
        'originals': 'ретушь не нужна (исходники)', 'not_own': 'фотограф сам не обрабатывает - ретушёр не указан',
        'no_column': 'в листе нет столбца «Ретушер»',
    }

    @property
    def ret_status_display(self) -> str:
        return self.RET_STATUS_LABELS.get(self.ret_status, '')

    @property
    def time_display(self) -> str:
        return f'{self.start_min // 60:02d}:{self.start_min % 60:02d}-{self.end_min // 60:02d}:{self.end_min % 60:02d}'
