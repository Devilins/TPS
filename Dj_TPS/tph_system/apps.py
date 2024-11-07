from django.apps import AppConfig


class TphSystemConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tph_system'

    def ready(self):
        import tph_system.signals  # импортируем сигналы
