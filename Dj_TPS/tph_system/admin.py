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
    list_display = ('date', 'store', 'staff', 'position', 'date_upd', 'user_edited')
    list_filter = ('date', 'store', 'staff')
    list_per_page = 30


@admin.register(ConsumablesStore)
class ConsumablesStoreAdmin(admin.ModelAdmin):
    readonly_fields = ('change_data', 'user_edited')
    list_display = ('consumable', 'cons_short', 'store', 'count', 'change_data')
    list_filter = ('store', 'consumable')
    list_per_page = 30


@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    readonly_fields = ('date_created', 'date_upd', 'user_edited')
    list_display = ('date', 'store', 'staff', 'photographer', 'sale_type', 'sum')
    list_filter = ('date', 'store')
    search_fields = ('sale_type', 'sum')
    search_help_text = 'Поиск по типу продажи или сумме'
    list_per_page = 30


@admin.register(ConsumablesSales)
class ConsumablesSalesAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_per_page = 30


@admin.register(Salary)
class SalaryAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_display = ('date', 'store', 'staff', 'salary_sum', 'date_upd')
    list_filter = ('store', 'staff')
    list_per_page = 30


@admin.register(CashWithdrawn)
class CashWithdrawnAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_display = ('date', 'store', 'staff', 'withdrawn', 'date_upd')
    list_filter = ('store', 'staff')
    list_per_page = 30


@admin.register(Tech)
class TechAdmin(admin.ModelAdmin):
    readonly_fields = ('date_change', 'user_edited')
    list_display = ('store', 'name', 'serial_num', 'count', 'date_change')
    list_filter = ('store', 'name')
    list_per_page = 30


@admin.register(RefsAndTips)
class RefsAndTipsAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_display = ('tip', 'refs', 'date_upd')
    search_fields = ['tip']
    search_help_text = 'Поиск по информации'
    list_per_page = 30


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_display = ('param', 'param_f_name', 'value', 'date_upd')
    search_fields = ('param', 'param_f_name')
    search_help_text = 'Поиск по параметру и описанию'
    list_per_page = 30


@admin.register(ImplEvents)
class ImplEventsAdmin(admin.ModelAdmin):
    readonly_fields = ('date_created', 'date_updated', 'user_edited')
    list_display = ('event_type', 'short_event_message', 'status', 'solved', 'date_updated', 'user_edited')
    list_filter = ('status', 'event_type', 'solved')
    search_fields = ['event_message']
    search_help_text = 'Поиск по тексту события'
    list_per_page = 30


@admin.register(SalaryWeekly)
class SalaryWeeklyAdmin(admin.ModelAdmin):
    list_display = ['week_begin', 'week_end', 'staff', 'salary_sum', 'paid_out']
    readonly_fields = ('date_updated', 'user_edited')
    list_filter = ['staff']
    list_per_page = 30


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'event_type', 'start_date', 'end_date', 'employee')
    list_filter = ('event_type', 'start_date')
    search_fields = ('title', 'description', 'employee__username')