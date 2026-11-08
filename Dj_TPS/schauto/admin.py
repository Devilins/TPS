from django.contrib import admin

from .models import Assignment, PhotoOrder, PlanRun, Route, StaffAlias, Venue, VenueAlias


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_display = ('name', 'brand', 'address', 'difficulty', 'store', 'sheet_tab_name', 'is_active')
    list_filter = ('brand', 'is_active')
    search_fields = ('name', 'address', 'sheet_tab_name')
    list_per_page = 40


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_display = ('from_venue', 'to_venue', 'description', 'duration_min')
    list_filter = ('from_venue', 'to_venue')
    list_per_page = 40


@admin.register(VenueAlias)
class VenueAliasAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_display = ('fragment', 'venue')
    search_fields = ('fragment', 'venue__name')


@admin.register(StaffAlias)
class StaffAliasAdmin(admin.ModelAdmin):
    readonly_fields = ('date_upd', 'user_edited')
    list_display = ('alias', 'staff')
    search_fields = ('alias', 'staff__name', 'staff__f_name')


@admin.register(PhotoOrder)
class PhotoOrderAdmin(admin.ModelAdmin):
    list_display = ('date', 'time_start', 'time_end', 'venue', 'brand', 'tab_name', 'photographer', 'status')
    list_filter = ('brand', 'status', 'venue')
    date_hierarchy = 'date'
    list_per_page = 40


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0
    can_delete = False
    fields = ('order', 'part_no', 'date', 'staff', 'need', 'cost')
    readonly_fields = fields
    show_change_link = False


@admin.register(PlanRun)
class PlanRunAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'date_from', 'date_to', 'status', 'created_by')
    readonly_fields = ('created_at', 'created_by', 'config', 'summary', 'warnings', 'fixed')
    inlines = [AssignmentInline]
    list_per_page = 40
