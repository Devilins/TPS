from django.db.models.signals import pre_save
from django.dispatch import receiver

from .middleware import *


@receiver(pre_save)
def set_user_edited(sender, instance, **kwargs):
    if hasattr(sender, 'user_edited'):
        current_user = get_current_user()
        if current_user and current_user.is_authenticated:
            instance.user_edited = current_user
