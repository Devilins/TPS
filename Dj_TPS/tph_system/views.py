from django.http import HttpResponse
from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet

from tph_system.models import Staff
from tph_system.serializers import StaffSerializer


class StaffViewSet(ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer


def main_page(request):
    return render(request, 'tph_system/main_page.html')


def store(request):
    return render(request, 'tph_system/store.html')