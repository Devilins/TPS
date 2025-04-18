from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from tph_system.views import MonitoringViewSet, TelegramUserViewSet, SingleUserViewSet

router = DefaultRouter()
router.register(r'mon', MonitoringViewSet)
router.register(r'tuser', TelegramUserViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('tph_system.tph_urls')),
    path('users/', include('users.urls', namespace="users")),
    path('api/', include(router.urls)),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/get_user/<str:username>/', SingleUserViewSet.as_view({'get': 'retrieve'}), name='get_user')
]

# urlpatterns += router.urls

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls))
    ]
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
