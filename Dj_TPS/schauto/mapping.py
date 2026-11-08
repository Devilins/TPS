"""Сопоставление текста из таблиц с объектами системы: имена -> Staff (через StaffAlias), адреса выездов -> Venue."""
from collections import defaultdict

from tph_system.models import Staff

from .models import StaffAlias, VenueAlias
from .parsers import NO_RETOUCH_VALUES, norm_place, norm_text

PERSON_EMPTY = 'empty'
PERSON_MATCHED = 'matched'
PERSON_IGNORED = 'ignored'
PERSON_UNMATCHED = 'unmatched'


class Resolver:
    """Снимок справочников на момент создания: алиасы, ФИО работающих сотрудников, фрагменты адресов."""

    def __init__(self):
        self.aliases = {a.alias: a.staff_id for a in StaffAlias.objects.all()}
        self.by_name = defaultdict(set)
        for s in Staff.objects.filter(dism_status='Работает'):
            # "Имя Фамилия" и "Фамилия Имя"; одно имя без фамилии автоматически не сопоставляем (слишком много тёзок)
            for full in (f'{s.name} {s.f_name}', f'{s.f_name} {s.name}'):
                self.by_name[norm_text(full)].add(s.id)
        self.places = sorted(((a.fragment, a.venue_id) for a in VenueAlias.objects.all()),
                             key=lambda item: -len(item[0]))  # длинные фрагменты первыми

    def person(self, clean_name: str) -> tuple[str, int | None]:
        """(статус, staff_id) для очищенного имени из ячейки"""
        key = norm_text(clean_name)
        if not key:
            return PERSON_EMPTY, None
        if key in self.aliases:
            staff_id = self.aliases[key]
            return (PERSON_IGNORED, None) if staff_id is None else (PERSON_MATCHED, staff_id)
        ids = self.by_name.get(key)
        if ids and len(ids) == 1:
            return PERSON_MATCHED, next(iter(ids))
        return PERSON_UNMATCHED, None

    def is_no_retouch(self, clean_name: str) -> bool:
        return norm_text(clean_name) in NO_RETOUCH_VALUES

    def place(self, raw_place: str) -> int | None:
        normalized = f' {norm_place(raw_place)} '
        for fragment, venue_id in self.places:
            if f' {fragment} ' in normalized:
                return venue_id
        return None
