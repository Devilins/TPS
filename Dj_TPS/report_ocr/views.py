from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
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
from tph_system.views import fx_stores_stf_working_list

VIEW_ALL_PERM = "report_ocr.view_all_report_uploads"

SECTION_ORDER = ["Дата Отчёта", "Мета", "Касса", "Техника", "Расходники",
                 "Личные кассы фотографов", "Вычеты ЗП наличными"]
SUB_FIELD_LABELS = {"начало_дня": "начало дня", "конец_дня": "конец дня"}


def _staff_today_stores(user):
    """Точки, на которых сотрудник работает сегодня (пустой список, если ни на одной)"""
    return fx_stores_stf_working_list(timezone.localdate(), user) or []


def _visible_uploads(user):
    """Сверки, доступные пользователю: все - при праве, иначе только сегодняшние по его точкам"""
    uploads = ReportUpload.objects.select_related("location")
    if user.has_perm(VIEW_ALL_PERM):
        return uploads
    return uploads.filter(location__in=_staff_today_stores(user), report_date=timezone.localdate())


def _upload_form_kwargs(user):
    """Без права на все сверки в форме загрузки - только сегодняшние точки сотрудника и сегодняшняя дата"""
    if user.has_perm(VIEW_ALL_PERM):
        return {}
    return {"stores": _staff_today_stores(user), "fixed_date": timezone.localdate()}


@login_required
@permission_required(perm='report_ocr.add_reportupload', raise_exception=True)
def upload_view(request):
    # Без права на все сверки загрузка доступна только сотруднику, работающему сегодня на точке
    if not request.user.has_perm(VIEW_ALL_PERM) and not _staff_today_stores(request.user):
        return redirect("report_ocr:list")

    if request.method == "POST":
        form = ReportUploadForm(request.POST, request.FILES, **_upload_form_kwargs(request.user))
        if form.is_valid():
            upload = form.save(commit=False)
            upload.uploaded_by = request.user
            upload.save()
            process_report.delay(upload.id)
            messages.success(request, "Фото принято, обрабатывается — обновите страницу через минуту.")
            return redirect("report_ocr:detail", pk=upload.pk)
    else:
        form = ReportUploadForm(**_upload_form_kwargs(request.user))
    return render(request, "report_ocr/upload.html", {"title": "Загрузка фото отчёта", "form": form})


@login_required
@permission_required(perm='report_ocr.view_reportupload', raise_exception=True)
def list_view(request):
    # Без права - только сегодняшний день и точки, на которых сотрудник работает сегодня
    uploads = _visible_uploads(request.user)
    view_all = request.user.has_perm(VIEW_ALL_PERM)
    upload_enabled = view_all or bool(_staff_today_stores(request.user))

    current_filter_params = request.GET.urlencode()
    upload_filter = ReportUploadFilter(request.GET, queryset=uploads)
    if not view_all:
        # Фильтровать по точке и дате такие пользователи не могут
        del upload_filter.filters["location"]
        del upload_filter.filters["report_date"]
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
        "view_all": view_all,
        "upload_enabled": upload_enabled,
    })


@login_required
@permission_required(perm=['report_ocr.view_reportupload', 'report_ocr.view_fieldresult'], raise_exception=True)
def detail_view(request, pk):
    upload = get_object_or_404(_visible_uploads(request.user), pk=pk)
    fields = list(upload.fields.all())

    # Секции в порядке бланка, внутри секции - порядок распознавания (начало/конец дня рядом)
    sections = {}
    for f in fields:
        f.sub_label = SUB_FIELD_LABELS.get(f.sub_field, f.sub_field)
        sections.setdefault(f.section, []).append(f)
    sections = sorted(
        ({"name": name, "fields": items, "review_count": sum(f.needs_review for f in items)}
         for name, items in sections.items()),
        key=lambda sec: SECTION_ORDER.index(sec["name"]) if sec["name"] in SECTION_ORDER else len(SECTION_ORDER),
    )

    total = len(fields)
    reviewed = sum(f.reviewed for f in fields)
    stats = {
        "total": total,
        "match": sum(f.is_match is True for f in fields),
        "mismatch": sum(f.is_match is False for f in fields),
        "review": sum(f.needs_review for f in fields),
        "reviewed": reviewed,
        "reviewed_pct": round(reviewed * 100 / total) if total else 0,
    }

    return render(request, "report_ocr/detail.html", {
        "title": f"{upload.location} — {upload.report_date}",
        "upload": upload,
        "fields": fields,
        "sections": sections,
        "stats": stats,
        "current_filter_params": request.GET.urlencode(),
    })


class ReportUploadDeleteView(PermissionRequiredMixin, LoginRequiredMixin, DeleteView):
    model = ReportUpload
    template_name = "report_ocr/upload_delete.html"
    permission_required = 'report_ocr.delete_reportupload'
    permission_denied_message = 'У вас нет прав на удаление сверок бумажных отчётов'

    def get_queryset(self):
        return _visible_uploads(self.request.user)

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
@permission_required(perm='report_ocr.change_fieldresult', raise_exception=True)
def confirm_field_view(request, pk):
    if request.method != "POST":
        return HttpResponseForbidden()
    field = get_object_or_404(FieldResult, pk=pk, upload__in=_visible_uploads(request.user))
    value = request.POST.get("value", "").strip()
    field.confirmed_value = value if value else field.extracted_value
    field.reviewed = True
    field.reviewed_by = request.user
    field.reviewed_at = timezone.now()
    field.save()
    return redirect("report_ocr:detail", pk=field.upload_id)
