"""
Единственное место с бизнес-логикой сверки бумажного отчёта с CRM.

Сверяем то, для чего в CRM реально есть источник данных:
- «Касса» — агрегация Sales по payment_type + CashStore (нал. на начало/конец дня).
- «Техника» / «Расходники» — сравниваем с ТЕКУЩИМ количеством на точке (Tech.count /
  ConsumablesStore.count) — отдельного дневного лога начала/конца дня в CRM нет,
  поэтому в начало_дня и конец_дня подставляется одно и то же число.
- «Личные кассы фотографов» — имена на бланке не распознаются, построчно не сверяем;
  get_personal_cashbox_total() отдаёт ИТОГ для сверки суммы всей таблицы (см. tasks.py).
- «Вычеты ЗП наличными» — сознательно не сверяем (см. обсуждение с пользователем).
"""
from datetime import date

from django.db.models import Sum

from tph_system.models import CashStore, ConsumablesStore, Sales, Tech


def field_key(field_name: str, sub_field: str) -> str:
    return f"{field_name}|{sub_field}"


def _fmt(value) -> str:
    """Целые — без '.0', чтобы совпадать со строкой, которую выдаёт цифровая OCR-модель."""
    if value == int(value):
        return str(int(value))
    return str(value)


# Категория ROI -> предикат по Tech.name (уже приведённому к нижнему регистру/без пробелов).
# «Синхронизаторы»/«Софтбоксы» есть только в шаблоне Joki Joya — в Laserland такой техники
# на точках нет, поэтому суммы по ним там всегда будут 0 (полей для них в laserland.json тоже нет).
_TECH_MATCHERS = {
    "Объективы": lambda n: n.startswith("объектив"),
    "Тушки": lambda n: n.startswith("тушка") or n.startswith("фотоаппарат"),
    "Флешки": lambda n: n.startswith("флешка") or n.startswith("флэшка"),
    "Вспышки": lambda n: n.startswith("вспышка"),
    "Светоотражатели": lambda n: n.startswith("светоотражатель"),
    "Синхронизаторы": lambda n: n.startswith("синхронизатор"),
    "Софтбоксы": lambda n: n.startswith("софтбокс"),
    "Аккум. для фото": lambda n: n.startswith("аккумулятор") and "canon" in n,
    "Аккум. для вспышки": lambda n: n.startswith("аккумулятор") and (
        "godox" in n or "eneloop" in n or "gp reenergy" in n
    ),
    "Зарядка для фото": lambda n: n.startswith("зарядка") and "canon" in n,
    # + "батареек (4 шт)" — общая зарядка для AA-аккумуляторов вспышки без явного бренда в названии
    "Зарядка для вспышки": lambda n: n.startswith("зарядка") and ("вспышк" in n or "батареек" in n),
}

# Категория ROI -> предикат по ConsumablesStore.consumable (нижний регистр).
# «Футболки» есть только в шаблоне Joki Joya — в CRM такого расходника пока нет вообще,
# сумма всегда будет 0 (не баг, а отсутствие данных на стороне CRM).
_CONSUMABLE_MATCHERS = {
    "Большие магниты": lambda n: "магнит" in n and "больш" in n,
    "Виниловые магниты": lambda n: "магнит" in n and "винилов" in n,
    "Средние магниты": lambda n: "магнит" in n and "средн" in n,
    "Рамки": lambda n: n == "рамки",
    "Футболки": lambda n: "футболк" in n,
}


def get_system_report_data(location, report_date: date) -> dict[str, str]:
    data = {}
    data.update(_cash_data(location, report_date))
    data.update(_grouped_count_data(Tech, location, _TECH_MATCHERS))
    data.update(_grouped_count_data(ConsumablesStore, location, _CONSUMABLE_MATCHERS, name_field="consumable"))
    return data


def _cash_data(location, report_date) -> dict[str, str]:
    agg = (
        Sales.objects.filter(store=location, date=report_date)
        .values("payment_type")
        .annotate(total=Sum("sum"))
    )
    by_type = {row["payment_type"]: row["total"] or 0 for row in agg}

    terminal = (
        by_type.get("Оплата через парк", 0) + by_type.get("Карта", 0) + by_type.get("Оплата по QR коду", 0)
    )
    cash = by_type.get("Наличные", 0)
    transfers = by_type.get("Перевод по номеру телефона", 0)
    orders = by_type.get("Предоплаченный заказ", 0)

    result = {
        field_key("Общая касса", ""): _fmt(terminal + cash + transfers),
        field_key("Терминал (Карта, QR)", ""): _fmt(terminal),
        field_key("Наличные", ""): _fmt(cash),
        field_key("Переводы", ""): _fmt(transfers),
        field_key("Заказы", ""): _fmt(orders),
    }

    cash_store = CashStore.objects.filter(store=location, date=report_date).first()
    if cash_store:
        result[field_key("Наличные в начале дня", "")] = _fmt(cash_store.cash_mrn)
        result[field_key("Наличные в конце дня", "")] = _fmt(cash_store.cash_evn)
    return result


def _grouped_count_data(model, location, matchers, name_field="name") -> dict[str, str]:
    """Суммирует model.count по store, группируя по совпадению с ключевыми словами категории."""
    counts: dict[str, float] = {}
    for name, count in model.objects.filter(store=location).values_list(name_field, "count"):
        key = (name or "").strip().lower()
        counts[key] = counts.get(key, 0) + count

    result = {}
    for category, matches in matchers.items():
        total = sum(c for name, c in counts.items() if matches(name))
        value = _fmt(total)
        result[field_key(category, "начало_дня")] = value
        result[field_key(category, "конец_дня")] = value
    return result


def get_personal_cashbox_total(location, report_date: date):
    """Сумма ВСЕХ продаж на точке за дату (по всем фотографам, все типы оплаты) — для
    сверки итога свободной таблицы «Личные кассы фотографов» (см. tasks.py: имена
    сотрудников на бланке не распознаются, построчно не сверяем, только общий итог)."""
    total = Sales.objects.filter(store=location, date=report_date).aggregate(total=Sum("sum"))["total"]
    return total or 0
