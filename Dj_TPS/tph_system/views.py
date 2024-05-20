from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet

from tph_system.models import *
from tph_system.serializers import StaffSerializer


class StaffViewSet(ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer


def main_page(request):
    return render(request, 'tph_system/main_page.html', {
        'title': 'Главная страница',
    })


def store(request):
    stores = Store.objects.all()

    return render(request, 'tph_system/store.html', {
        'title': 'Точки',
        'stores': stores,
    })

def store_create(request):
    return render(request, 'tph_system/store_create.html', {
        'title': 'Добавление новой точки',
    })
