from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import SimpleRouter

from tph_system.views import StaffViewSet, main_page, store

router = SimpleRouter()

router.register(r'staff', StaffViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('tph_system.tph_urls')),
]

urlpatterns += router.urls
