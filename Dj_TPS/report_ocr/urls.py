from django.urls import path

from . import views

app_name = "report_ocr"

urlpatterns = [
    path("", views.list_view, name="list"),
    path("upload/", views.upload_view, name="upload"),
    path("report/<int:pk>/", views.detail_view, name="detail"),
    path("report/<int:pk>/delete/", views.ReportUploadDeleteView.as_view(), name="delete"),
    path("field/<int:pk>/confirm/", views.confirm_field_view, name="confirm_field"),
]
