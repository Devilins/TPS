from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DeleteView

from .filters import ReportUploadFilter
from .forms import ReportUploadForm
from .models import FieldResult, ReportUpload
from .tasks import process_report


@login_required
def upload_view(request):
    if request.method == "POST":
        form = ReportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.save(commit=False)
            upload.uploaded_by = request.user
            upload.save()
            process_report.delay(upload.id)
            messages.success(request, "Фото принято, обрабатывается — обновите страницу через минуту.")
            return redirect("report_ocr:detail", pk=upload.pk)
    else:
        form = ReportUploadForm()
    return render(request, "report_ocr/upload.html", {"title": "Загрузка фото отчёта", "form": form})


@login_required
def list_view(request):
    uploads = ReportUpload.objects.select_related("location")

    current_filter_params = request.GET.urlencode()
    upload_filter = ReportUploadFilter(request.GET, queryset=uploads)
    uploads = upload_filter.qs

    paginator = Paginator(uploads, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "report_ocr/list.html", {
        "title": "Сверка бумажных отчётов",
        "upload_filter": upload_filter,
        "current_filter_params": current_filter_params,
        "paginator": paginator,
        "page_obj": page_obj,
        "upload_count": paginator.count,
    })


@login_required
def detail_view(request, pk):
    upload = get_object_or_404(ReportUpload.objects.select_related("location"), pk=pk)
    fields = list(upload.fields.all())
    fields.sort(key=lambda f: (not f.needs_review, f.section, f.field_name))
    return render(request, "report_ocr/detail.html", {
        "title": f"{upload.location} — {upload.report_date}",
        "upload": upload,
        "fields": fields,
        "current_filter_params": request.GET.urlencode(),
    })


class ReportUploadDeleteView(LoginRequiredMixin, DeleteView):
    model = ReportUpload
    template_name = "report_ocr/upload_delete.html"

    def get_success_url(self):
        # Возвращаем URL с сохраненными параметрами фильтрации
        return reverse("report_ocr:list") + "?" + self.request.GET.urlencode()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Удаление отчёта"
        context["current_filter_params"] = self.request.GET.urlencode()
        return context

    def form_valid(self, form):
        # исходное фото — единственный файл в media, привязанный к записи;
        # без этого он остаётся сиротой на диске после удаления записи
        if self.object.photo:
            self.object.photo.delete(save=False)
        return super().form_valid(form)


@login_required
def confirm_field_view(request, pk):
    if request.method != "POST":
        return HttpResponseForbidden()
    field = get_object_or_404(FieldResult, pk=pk)
    value = request.POST.get("value", "").strip()
    field.confirmed_value = value if value else field.extracted_value
    field.reviewed = True
    field.reviewed_by = request.user
    field.reviewed_at = timezone.now()
    field.save()
    return redirect("report_ocr:detail", pk=field.upload_id)
