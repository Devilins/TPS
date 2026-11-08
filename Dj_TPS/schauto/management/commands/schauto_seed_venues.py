from django.core.management.base import BaseCommand, CommandError

from schauto.gsheet import BRANDS, KIND_CENTER, KIND_TRIPS, KIND_VIDEO, SheetError, center_name
from schauto.models import Venue, VenueAlias
from schauto.parsers import norm_text
from schauto.sheetrows import find_address
from schauto.tabsource import default_source
from tph_system.models import ImplEvents, Store

SKIP_REASONS = {
    KIND_TRIPS: 'выезды на адреса, центры для них заводятся отдельно',
    KIND_VIDEO: 'заказные видеосъёмки (видеографы), пока не планируются',
}

# Центры, куда ездят по листу "ВЫЕЗДЫ" (нет своих листов и фототочек): название -> фрагменты адреса. Дополнять можно на экране "Сопоставления"
TRIP_VENUES = (
    ('Экзотаг Рио', ('рио ленинский',)),
    ('Экзотаг Город', ('трц город',)),
)


def match_store(brand: str, base: str) -> tuple[Store | None, bool]:
    """Фототочка ERP для центра: бренд по префиксу short_name (LL/JJ), название центра входит в название точки.
    Возвращает (действующая точка, если она одна; признак "подходят только закрытые точки")."""
    key = norm_text(base)
    if not key:
        return None, False
    found = [s for s in Store.objects.filter(short_name__startswith=brand) if key in norm_text(s.name)]
    active = [s for s in found if s.store_status == 'Действующая']
    closed = [s for s in found if s.store_status == 'Закрытая']
    return (active[0] if len(active) == 1 else None), bool(closed and not active)


class Command(BaseCommand):
    help = ("Создаёт центры (Venue) по листам Google-таблиц заказов (таблица Laserland и таблица Joki Joya), привязывает к ним "
            "действующие фототочки ERP и заводит центры для листа выездов. Уже заведённые листы пропускает. "
            "ID таблиц берутся из SCHAUTO_SHEET_ID_LL / SCHAUTO_SHEET_ID_JJ.")

    def add_arguments(self, parser):
        parser.add_argument('--brand', choices=BRANDS, action='append',
                            help='Бренд (можно несколько раз); по умолчанию - оба, у которых задан ID таблицы')
        parser.add_argument('--sheet-id', default=None,
                            help='ID таблицы вместо SCHAUTO_SHEET_ID_* (только вместе с одним --brand)')
        parser.add_argument('--dry-run', action='store_true', help='Только показать, что будет сделано')
        parser.add_argument('--fill-addresses', action='store_true',
                            help='Заполнить пустые адреса центров из строки заголовков их листов (читает все листы центров)')
        parser.add_argument('--relink', action='store_true',
                            help='Если центр с таким названием уже есть, но с другим листом - перепривязать к этому листу')

    def handle(self, *args, **options):
        brands = options['brand'] or list(BRANDS)
        if options['sheet_id'] and len(brands) != 1:
            raise CommandError('--sheet-id можно указывать только вместе с одним --brand')
        explicit = bool(options['brand'])
        source, note = default_source()
        if note:
            self.stdout.write(self.style.WARNING(note))

        report = {'created': [], 'relinked': [], 'linked': [], 'trip': [], 'addresses': []}
        for brand in brands:
            try:
                tabs = source.tabs(brand, options['sheet_id'])
            except SheetError as e:
                if explicit:
                    raise CommandError(str(e))
                self.stdout.write(self.style.WARNING(f'[{brand}] пропущен: {e}'))
                continue
            self.stdout.write(f'[{brand}] листов в таблице: {len(tabs)}')
            for tab in tabs:
                if tab.kind != KIND_CENTER:
                    self.stdout.write(f'[{brand}] пропущен лист «{tab.name}»: {SKIP_REASONS.get(tab.kind, "игнорируется")}')
                    continue
                self._seed_center(brand, tab, options, report)
            if options['fill_addresses']:
                self._fill_addresses(source, brand, tabs, options, report)
        self._seed_trip_venues(options['dry_run'], report)

        if any(report.values()) and not options['dry_run']:
            ImplEvents.objects.create(
                event_type='Schauto_Seed_Venues', status='Успешно', solved='Да',
                event_message='; '.join(f'{label} ({len(report[key])}): {", ".join(report[key])}' for key, label in (
                    ('created', 'создано'), ('relinked', 'перепривязано'), ('linked', 'привязаны фототочки'),
                    ('trip', 'центры выездов'), ('addresses', 'заполнены адреса')) if report[key]))
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Новых центров: {len(report["created"])}, перепривязано: {len(report["relinked"])}, '
            f'привязано фототочек: {len(report["linked"])}, центров выездов: {len(report["trip"])}, '
            f'заполнено адресов: {len(report["addresses"])}'))

    def _seed_center(self, brand, tab, options, report):
        dry = options['dry_run']
        existing = Venue.objects.filter(brand=brand, sheet_tab_name=tab.name).first()
        if existing:
            self._link_store(existing, tab.center, dry, report)
            return
        name = center_name(tab.center, brand)
        by_name = Venue.objects.filter(name=name).first()
        if by_name is None:
            store, closed = match_store(brand, tab.center)
            if not dry:
                Venue.objects.create(name=name, brand=brand, sheet_tab_name=tab.name, store=store, is_active=not closed)
            report['created'].append(name)
            details = (f', фототочка «{store}»' if store else '') + (', фототочка закрыта - центр неактивен' if closed else '')
            self.stdout.write(f'[{brand}] {"будет создан" if dry else "создан"} центр «{name}» (лист «{tab.name}»{details})')
        elif options['relink'] and by_name.brand == brand:
            old_tab = by_name.sheet_tab_name
            if not dry:
                by_name.sheet_tab_name = tab.name
                by_name.save(update_fields=['sheet_tab_name', 'date_upd'])
            report['relinked'].append(name)
            self.stdout.write(f'[{brand}] {"будет перепривязан" if dry else "перепривязан"} центр «{name}»: '
                              f'лист «{old_tab}» -> «{tab.name}»')
            self._link_store(by_name, tab.center, dry, report)
        else:
            self.stderr.write(f'[{brand}] лист «{tab.name}»: центр «{name}» уже есть (лист «{by_name.sheet_tab_name}»); '
                              f'для перепривязки запустите с --relink')

    def _fill_addresses(self, source, brand, tabs, options, report):
        """Пустые адреса центров бренда - из ячейки с адресом в строке заголовков листа (только пустые, существующие не трогаем)"""
        targets = []
        for tab in tabs:
            venue = Venue.objects.filter(brand=brand, sheet_tab_name=tab.name, address='').first() if tab.kind == KIND_CENTER else None
            if venue:
                targets.append((venue, tab))
        if not targets:
            return
        try:
            data = source.read(brand, [tab for _, tab in targets], options['sheet_id'])
        except SheetError as e:
            self.stderr.write(f'[{brand}] не удалось прочитать листы для адресов ({e})')
            return
        addresses = []
        for _, tab in targets:
            rows, error = data[tab.gid]
            if error:      # лист не прочитался - остальные продолжаем
                self.stderr.write(f'[{brand}] лист «{tab.name}»: не удалось прочитать ({error})')
            addresses.append(find_address(rows) if rows is not None else '')
        for (venue, tab), address in zip(targets, addresses):
            if not address:
                self.stdout.write(f'[{brand}] у центра «{venue.name}» адрес в листе не найден - заполните вручную')
                continue
            if not options['dry_run']:
                venue.address = address
                venue.save(update_fields=['address', 'date_upd'])
            report['addresses'].append(venue.name)
            self.stdout.write(f'[{brand}] {"будет записан" if options["dry_run"] else "записан"} адрес «{venue.name}»: {address}')

    def _link_store(self, venue, base, dry, report):
        """Привязка фототочки ERP к уже заведённому центру: только если она не задана; активность центра не меняем"""
        if venue.store_id is not None:
            return
        store, closed = match_store(venue.brand, base)
        if store:
            if not dry:
                venue.store = store
                venue.save(update_fields=['store', 'date_upd'])
            report['linked'].append(venue.name)
            self.stdout.write(f'[{venue.brand}] {"будет привязана" if dry else "привязана"} фототочка «{store}» к центру «{venue.name}»')
        elif closed and venue.is_active:
            self.stdout.write(self.style.WARNING(
                f'[{venue.brand}] у центра «{venue.name}» фототочка закрыта в ERP - при необходимости деактивируйте центр'))

    def _seed_trip_venues(self, dry, report):
        for name, fragments in TRIP_VENUES:
            venue = Venue.objects.filter(name=name).first()
            if venue is None:
                if not dry:
                    venue = Venue.objects.create(name=name, brand='OT')
                report['trip'].append(name)
                self.stdout.write(f'{"Будет создан" if dry else "Создан"} центр выездов «{name}»')
            for fragment in fragments:
                alias = VenueAlias.objects.filter(fragment=fragment).first()
                if alias is None:
                    if not dry and venue is not None:
                        VenueAlias.objects.create(fragment=fragment, venue=venue)
                    self.stdout.write(f'{"Будет добавлен" if dry else "Добавлен"} фрагмент адреса «{fragment}» -> «{name}»')
                elif venue is not None and alias.venue_id != venue.id:
                    self.stderr.write(f'Фрагмент адреса «{fragment}» уже указывает на «{alias.venue}», а не на «{name}» - не менял')
