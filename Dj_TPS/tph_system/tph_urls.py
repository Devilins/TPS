from django.urls import path
from .views import *

urlpatterns = [
    path('', index, name='index'),
    path('main_page/', main_page, name='main_page'),
    path('store/', store, name='store'),
    path('staff/', staff, name='staff'),
    path('consumables/', cons_store, name='cons_store'),
    path('tech/', tech_mtd, name='tech'),
    path('schedule/', schedule_mtd, name='schedule'),
    path('sales/', sales, name='sales'),
    path('cash_withdrawn/', cash_withdrawn, name='cash_withdrawn'),
    path('update-schedule/', update_schedule, name='update_schedule'),
    path('store/<int:pk>/update', StoreUpdateView.as_view(), name='store_update'),
    path('store/<int:pk>/delete', StoreDeleteView.as_view(), name='store_delete'),
    path('staff/<int:pk>/update', StaffUpdateView.as_view(), name='staff_update'),
    path('staff/<int:pk>/delete', StaffDeleteView.as_view(), name='staff_delete'),
    path('consumables/<int:pk>/update', ConStoreUpdateView.as_view(), name='con_store_update'),
    path('consumables/<int:pk>/delete', ConStoreDeleteView.as_view(), name='con_store_delete'),
    path('tech/<int:pk>/update', TechUpdateView.as_view(), name='tech_update'),
    path('tech/<int:pk>/delete', TechDeleteView.as_view(), name='tech_delete'),
    path('sales/<int:pk>/update', SalesUpdateView.as_view(), name='sales_update'),
    path('sales/<int:pk>/delete', SalesDeleteView.as_view(), name='sales_delete'),
    path('cash_withdrawn/<int:pk>/update', CashWithdrawnUpdateView.as_view(), name='c_w_update'),
    path('cash_withdrawn/<int:pk>/delete', CashWithdrawnDeleteView.as_view(), name='c_w_delete')
]
