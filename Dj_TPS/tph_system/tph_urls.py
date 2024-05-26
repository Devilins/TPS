from django.urls import path

from .views import *

urlpatterns = [
    path('main_page/', main_page, name='main_page'),
    path('store/', store, name='store'),
    path('staff/', staff, name='staff'),
    path('consumables/', cons_store, name='cons_store'),
]
