from django.urls import path

from .views import *

urlpatterns = [
    path('main_page/', main_page, name='main_page'),
    path('store/', store, name='store'),
    path('store/create', store_create, name='store_create'),
]
