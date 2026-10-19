"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
https://docs.djangoproject.com/en/6.0/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from soil_api.views import home_screen, CustomObtainAuthToken

urlpatterns = [
    path('', home_screen, name='home'),
    path('admin/', admin.site.urls),
    path('api/auth/', include('rest_framework.urls')),
    path('api/api-token-auth/', CustomObtainAuthToken.as_view(), name='main-api-token-auth'),
    path('api/', include('soil_api.urls')),
]