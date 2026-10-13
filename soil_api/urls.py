from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'users', views.UserViewSet, basename='user')

urlpatterns = [
    path('', include(router.urls)),

    path('plots/', views.plot_manager, name='plot-list'),
    path('plots/admin-manageable/', views.admin_manageable_plots, name='admin-manageable-plots'),
    path('plots/<int:pk>/', views.plot_detail_manager, name='plot-detail'),
    path('plots/<int:plot_id>/ph-analytics/', views.get_ph_analytics, name='ph-analytics'),

    path('records/add/', views.record_data, name='add-sensor-data'),
    path('records/<int:pk>/', views.record_detail_manager, name='record-detail'),

    path('user/', views.current_user, name='current-user'),

    path('register/', views.register_user_web, name='register-user'),
    path('api/register/', views.register_user, name='api-register-user'),
    path('api-token-auth/', views.CustomObtainAuthToken.as_view(), name='api-token-auth'),
]