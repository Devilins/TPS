from django.urls import path

from .views import *

urlpatterns = [
    path('main_page/', MainPage.as_view(), name='main_page'),
    path('store/', store, name='store'),
    path('staff/', staff, name='staff'),
    path('consumables/', cons_store, name='cons_store'),
    path('tech/', tech_mtd, name='tech'),
    path('store/<int:pk>/update', StoreUpdateView.as_view(), name='store_update'),
    path('store/<int:pk>/delete', StoreDeleteView.as_view(), name='store_delete'),
    path('staff/<int:pk>/update', StaffUpdateView.as_view(), name='staff_update'),
    path('staff/<int:pk>/delete', StaffDeleteView.as_view(), name='staff_delete'),
    path('consumables/<int:pk>/update', ConStoreUpdateView.as_view(), name='con_store_update'),
    path('consumables/<int:pk>/delete', ConStoreDeleteView.as_view(), name='con_store_delete'),
    path('tech/<int:pk>/update', TechUpdateView.as_view(), name='tech_update'),
    path('tech/<int:pk>/delete', TechDeleteView.as_view(), name='tech_delete')
]
