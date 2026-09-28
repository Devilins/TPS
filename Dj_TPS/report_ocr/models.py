from django.conf import settings
from django.db import models
from tph_system.models import Store


class ReportUpload(models.Model):
    """Одна загрузка фото бумажного отчёта за конкретную точку и дату."""

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_PENDING, "В очереди"),
        (STATUS_PROCESSING, "Обрабатывается"),
        (STATUS_DONE, "Готово"),
        (STATUS_ERROR, "Ошибка распознавания"),
    ]

    # она уже должна однозначно определять бренд/шаблон (Laserland/Joki Joya) — см. get_template_key().
    location = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="report_uploads"
    )
    report_date = models.DateField(verbose_name="Дата отчёта")
    photo = models.ImageField(upload_to="report_ocr/uploads/%Y/%m/%d/")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # один отчёт на точку в день — повторная загрузка должна явно заменять, не плодить дубли
        constraints = [
            models.UniqueConstraint(
                fields=["location", "report_date"], name="uniq_report_per_location_date"
            )
        ]
        ordering = ["-report_date", "-created_at"]

    def __str__(self):
        return f"{self.location} — {self.report_date}"

    def get_template_key(self) -> str:
        """Бренд/шаблон бланка для выбора ROI-карты — по конвенции short_name (см. tph_system.funcs)."""
        return "joki_joya" if "JJ" in self.location.short_name else "laserland"


class FieldResult(models.Model):
    """Результат распознавания одного числового поля бланка."""

    upload = models.ForeignKey(ReportUpload, on_delete=models.CASCADE, related_name="fields")

    section = models.CharField(max_length=50)  # "Техника", "Расходники", "Касса", ...
    field_name = models.CharField(max_length=100)  # "Аккум. для фото", "Общая касса", ...
    sub_field = models.CharField(max_length=20, blank=True)  # "начало_дня" / "конец_дня" / ""

    extracted_value = models.CharField(max_length=50, blank=True)
    confidence = models.FloatField(null=True, blank=True)  # минимум по цифрам в значении

    system_value = models.CharField(max_length=50, blank=True)  # из CRM, для той же даты/точки
    is_match = models.BooleanField(null=True)

    # правка куратора при ревью — одновременно и итог, и обучающий пример на будущее дообучение
    confirmed_value = models.CharField(max_length=50, blank=True)
    reviewed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    crop_image = models.ImageField(
        upload_to="report_ocr/crops/%Y/%m/%d/", blank=True,
        help_text="Вырезанная ячейка — нужна и для ревью, и как сэмпл для дообучения",
    )

    class Meta:
        indexes = [models.Index(fields=["upload", "section"])]
        ordering = ["upload", "id"]

    def __str__(self):
        return f"{self.field_name} {self.sub_field}".strip() + f" = {self.extracted_value}"

    @property
    def needs_review(self) -> bool:
        """Низкая уверенность ИЛИ расхождение с системой — то, что стоит показать куратору в первую очередь."""
        low_conf = self.confidence is not None and self.confidence < 0.85
        return (not self.reviewed) and (low_conf or self.is_match is False)
