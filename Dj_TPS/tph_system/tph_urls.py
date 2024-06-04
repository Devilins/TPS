from django.urls import path

from .views import *

urlpatterns = [
    path('main_page/', main_page, name='main_page'),
    path('store/', store, name='store'),
    path('staff/', staff, name='staff'),
    path('consumables/', cons_store, name='cons_store'),
    path('store/<int:pk>/update', StoreUpdateView.as_view(), name='store_update'),
    path('store/<int:pk>/delete', StoreDeleteView.as_view(), name='store_delete')
]
