from django.contrib import admin

from tph_system.models import *

# admin.site.register(Staff)
# admin.site.register(Store)
# admin.site.register(Schedule)
# admin.site.register(ConsumablesStore)
# admin.site.register(Sales)
# admin.site.register(ConsumablesSales)
# admin.site.register(Salary)
# admin.site.register(CashWithdrawn)
# admin.site.register(Tech)
# admin.site.register(RefsAndTips)
# admin.site.register(Settings)
# admin.site.register(ImplEvents)
# admin.site.register(SalaryWeekly)


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    readonly_fields = ['date_upd', 'user_edited']


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')


@admin.register(ConsumablesStore)
class ConsumablesStoreAdmin(admin.ModelAdmin):
    readonly_fields = ('change_data', 'user_edited')


@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    readonly_fields = ('date_created', 'date_upd', 'user_edited')
    list_display = ('date', 'store', 'staff', 'photographer', 'sale_type', 'sum')
    list_filter = ('date', 'store')
    search_fields = ('sale_type', 'sum')
    search_help_text = 'Поиск по типу продажи или сумме'

@admin.register(ConsumablesSales)
class ConsumablesSalesAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')


@admin.register(Salary)
class SalaryAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')


@admin.register(CashWithdrawn)
class CashWithdrawnAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')


@admin.register(Tech)
class TechAdmin(admin.ModelAdmin):
    readonly_fields = ('date_change', 'user_edited')


@admin.register(RefsAndTips)
class RefsAndTipsAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')


@admin.register(ImplEvents)
class ImplEventsAdmin(admin.ModelAdmin):
    readonly_fields = ('date_created', 'date_updated', 'user_edited')
    list_display = ('event_type', 'event_message', 'status', 'solved', 'date_created')
    list_filter = ('status', 'event_type', 'solved')
    search_fields = ['event_message']
    search_help_text = 'Поиск по тексту события'


@admin.register(SalaryWeekly)
class SalaryWeeklyAdmin(admin.ModelAdmin):
    list_display = ['week_begin', 'week_end', 'staff']
    readonly_fields = ('date_updated', 'user_edited')


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'event_type', 'start_date', 'end_date', 'employee')
    list_filter = ('event_type', 'start_date')
    search_fields = ('title', 'description', 'employee__username')