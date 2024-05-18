from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet

from tph_system.models import *
from tph_system.serializers import StaffSerializer


class StaffViewSet(ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer


menu = ["Главная страница", "График сотрудников", "Продажи", "Расходники", "Сотрудники", "Точки", "Зарплаты",
        "Финансовая отчетность"]


def main_page(request):
    return render(request, 'tph_system/main_page.html', {
        'title': 'Главная страница',
        'menu': menu
    })


def store(request):
    stores = Store.objects.all()

    return render(request, 'tph_system/store.html', {
        'title': 'Точки',
        'menu': menu,
        'stores': stores
    })
