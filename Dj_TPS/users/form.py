from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm


class LoginUserForm(AuthenticationForm):
    username = forms.CharField(label="Имя пользователя",
                               widget=forms.TextInput(attrs={
                                   'class': 'form-control',
                                   'placeholder': 'Имя пользователя'
                               }))
    password = forms.CharField(label="Пароль",
                               widget=forms.PasswordInput(attrs={
                                   'class': 'form-control',
                                   'placeholder':'Пароль'
                               }))

    class Meta:
        model = get_user_model()
        fields = ['username', 'password']
