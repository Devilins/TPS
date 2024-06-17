from django.contrib.auth.views import PasswordChangeView, PasswordChangeDoneView
from django.urls import path
from .views import *

app_name = "users"

urlpatterns = [
    path('login/', LoginUser.as_view(), name='login'),
    path('logout/', logout_user, name='logout'),
    path('password-change/', UserPasswordChange.as_view(), name='password_change'),
    path('password-change/done/', PasswordChangeDoneView.as_view(template_name="users/password_change_done_form.html"),
         name='password_change_done')
]
