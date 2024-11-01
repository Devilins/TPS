from django.contrib import admin

from tph_system.models import *

admin.site.register(Staff)
admin.site.register(Store)
admin.site.register(Schedule)
admin.site.register(ConsumablesStore)
admin.site.register(Sales)
admin.site.register(ConsumablesSales)
admin.site.register(Salary)
admin.site.register(CashWithdrawn)
admin.site.register(Tech)
admin.site.register(RefsAndTips)
admin.site.register(Settings)
admin.site.register(ImplErrors)
#admin.site.register(SalaryWeekly)


@admin.register(SalaryWeekly)
class SalaryWeekly_Admin(admin.ModelAdmin):
    list_display = ['week_begin', 'week_end', 'staff']

