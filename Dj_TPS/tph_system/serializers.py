from rest_framework.serializers import ModelSerializer

from django.contrib.auth.models import User
from tph_system.models import ImplEvents, Sales, TelegramUser


class MonitoringSerializer(ModelSerializer):
    class Meta:
        model = ImplEvents
        fields = '__all__'


class CashBoxSerializer(ModelSerializer):
    class Meta:
        model = Sales
        fields = '__all__'


class UserSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class TelegramUserSerializer(ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = TelegramUser
        fields = '__all__'