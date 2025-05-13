import json
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.db.models.signals import pre_save, pre_delete, post_save
from django.contrib.contenttypes.models import ContentType
from django.dispatch import receiver

from .middleware import *
from .models import ImplEvents, TelegramUser, CashWithdrawn
from .funcs import sal_weekly_update


@receiver(pre_save)
def set_user_edited(sender, instance, **kwargs):
    if hasattr(sender, 'user_edited'):
        current_user = get_current_user()
        if current_user and current_user.is_authenticated:
            instance.user_edited = current_user


@receiver(post_save)
def run_cw_sal_sync(sender, instance, **kwargs):
    if sender == CashWithdrawn and hasattr(sender, 'week_beg_rec'):
        if instance.week_beg_rec is not None:
            end_week = instance.week_beg_rec + timedelta(days=6)
            sal_weekly_update(instance.week_beg_rec, end_week)


@receiver(pre_delete)
def log_deletion(sender, instance, **kwargs):
    """
    Сигнал, который создает запись в ImplEvents перед удалением объекта
    """
    # Пропускаем логирование удаления самих логов
    if sender == ImplEvents or sender == Session or sender == TelegramUser:
        return

    try:
        # Получаем текущего пользователя
        user = get_current_user()

        # Формируем сообщение о событии
        event_message = {
            'model': sender._meta.model_name,
            'app': sender._meta.app_label,
            'object_id': str(instance.pk),
            'object_repr': str(instance)
        }

        # Пытаемся добавить данные объекта
        try:
            obj_data = {}
            for field in instance._meta.fields:
                value = getattr(instance, field.name)
                if hasattr(value, 'pk'):  # Для ForeignKey
                    obj_data[field.name] = {
                        'id': value.pk,
                        'repr': str(value)
                    }
                elif hasattr(value, 'isoformat'):  # Для дат
                    obj_data[field.name] = value.isoformat()
                else:
                    obj_data[field.name] = str(value)

            event_message['object_data'] = obj_data
        except Exception as e:
            event_message['serialization_error'] = str(e)

        # Создаем запись в логах
        ImplEvents.objects.create(
            event_type=f"Delete_rec_from_{event_message['model']}",
            event_message=json.dumps(event_message, ensure_ascii=False, indent=2),
            status='Удаление записи',
            user_edited=user if user else None
        )
    except Exception as e:
        user = get_current_user()
        # Логируем ошибку, но не препятствуем удалению
        ImplEvents.objects.create(
            event_type='Delete_Error',
            event_message=f"Ошибка при логировании удаления: {str(e)}",
            status='Системная ошибка',
            solved='Нет',
            user_edited=user if user else None
        )
