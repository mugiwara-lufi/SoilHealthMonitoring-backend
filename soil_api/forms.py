from django import forms
from django.contrib.auth.models import User

class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Enter Password'}))
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Enter Username'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Enter Email'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'Enter First Name'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Enter Last Name'}),
        }