from django.http import HttpResponse
from rest_framework.viewsets import ModelViewSet

from tph_system.models import Staff
from tph_system.serializers import StaffSerializer


class StaffViewSet(ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer


def main_page(request):
    return HttpResponse("<h1>Главная страница TPS</h1>")