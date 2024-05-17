from django.contrib import admin
from django.urls import path
from rest_framework.routers import SimpleRouter

from tph_system.views import StaffViewSet, main_page

router = SimpleRouter()

router.register(r'staff', StaffViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('main_page/', main_page),
]

urlpatterns += router.urls
