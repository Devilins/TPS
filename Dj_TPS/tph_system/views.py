from django.shortcuts import render, redirect
from rest_framework.viewsets import ModelViewSet

from tph_system.models import *
from tph_system.serializers import StaffSerializer
from tph_system.forms import StoreForm, StaffForm, ConsStoreForm
from .filters import ConsumablesStoreFilter


class StaffViewSet(ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer


def main_page(request):
    return render(request, 'tph_system/main_page.html', {
        'title': 'Главная страница',
    })


def store(request):
    stores = Store.objects.all()

    error = ''
    if request.method == 'POST':
        form_p = StoreForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('store')
        else:
            error = 'Ошибка в заполнении формы'

    form = StoreForm()

    return render(request, 'tph_system/store.html', {
        'title': 'Точки',
        'stores': stores,
        'form': form,
        'error': error
    })


def staff(request):
    staffs = Staff.objects.all()

    error = ''
    if request.method == 'POST':
        form_p = StaffForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('staff')
        else:
            error = 'Ошибка в заполнении формы'

    form = StaffForm()

    return render(request, 'tph_system/staff.html', {
        'title': 'Сотрудники',
        'staffs': staffs,
        'form': form,
        'error': error
    })


def cons_store(request):
    con_store = ConsumablesStore.objects.all()
    stores = Store.objects.all()

    cs_filter = ConsumablesStoreFilter(request.GET, queryset=con_store)
    con_store = cs_filter.qs

    error = ''
    if request.method == 'POST':
        form_p = ConsStoreForm(request.POST)
        if form_p.is_valid():
            form_p.save()
            return redirect('cons_store')
        else:
            error = 'Ошибка в заполнении формы'

    form = ConsStoreForm()

    return render(request, 'tph_system/сonsumablesStore.html', {
        'title': 'Расходники',
        'con_store': con_store,
        'form': form,
        'error': error,
        'stores': stores,
        'cs_filter': cs_filter
    })
