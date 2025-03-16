from rest_framework.serializers import ModelSerializer

from tph_system.models import ImplEvents


class MonitoringSerializer(ModelSerializer):
    class Meta:
        model = ImplEvents
        fields = '__all__'
