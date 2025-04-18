from rest_framework.serializers import ModelSerializer, PrimaryKeyRelatedField

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
        read_only_fields = ['username', 'first_name', 'last_name']


class TelegramUserSerializer(ModelSerializer):
    user = PrimaryKeyRelatedField(queryset=User.objects.all(), required=True)

    class Meta:
        model = TelegramUser
        fields = '__all__'

    def to_representation(self, instance):
        """Для вывода полных данных пользователя"""
        self.fields['user'] = UserSerializer()
        return super().to_representation(instance)
