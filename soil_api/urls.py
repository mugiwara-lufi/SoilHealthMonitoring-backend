from django.urls import path
from . import views
from rest_framework.authtoken.views import obtain_auth_token 

urlpatterns = [
    # 1. Manage Plots (Farm Overview Screen)
    path('plots/', views.plot_manager, name='plot-list'),
    
    # 2. Specific Plot Details & Monitoring
    path('plots/<int:pk>/', views.plot_detail_manager, name='plot-detail'),
    
    # 3. Chart Analytics Endpoint
    path('plots/<int:plot_id>/ph-analytics/', views.get_ph_analytics, name='ph-analytics'),

    # 4. Sensor Data Endpoints
    path('records/add/', views.record_data, name='add-sensor-data'),
    path('records/<int:pk>/', views.record_detail_manager, name='record-detail'),

    path('user/', views.current_user, name='current-user'),

    # 5. User Registration & Auth Endpoints
    path('register/', views.register_user_web, name='register-user'),
    path('api/register/', views.register_user, name='api-register-user'),
    path('api-token-auth/', obtain_auth_token),
]