from django.contrib import admin

from .models import FieldResult, ReportUpload


class FieldResultInline(admin.TabularInline):
    model = FieldResult
    extra = 0
    fields = ("section", "field_name", "sub_field", "extracted_value", "confidence", "system_value", "is_match", "reviewed")
    readonly_fields = fields


@admin.register(ReportUpload)
class ReportUploadAdmin(admin.ModelAdmin):
    list_display = ("location", "report_date", "status", "uploaded_by", "created_at")
    list_filter = ("status", "location")
    inlines = [FieldResultInline]


@admin.register(FieldResult)
class FieldResultAdmin(admin.ModelAdmin):
    list_display = ("upload", "section", "field_name", "sub_field", "extracted_value", "system_value", "is_match", "reviewed")
    list_filter = ("section", "is_match", "reviewed")
    search_fields = ("field_name",)
