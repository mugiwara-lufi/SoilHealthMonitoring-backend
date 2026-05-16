from django.urls import path
from . import views
# Import the specific view function directly to avoid naming conflicts
from rest_framework.authtoken.views import obtain_auth_token 

urlpatterns = [
    # 1. Manage Plots (Farm Overview Screen)
    path('plots/', views.plot_manager, name='plot-list'),
    
    # 2. Specific Plot Details & Monitoring
    path('plots/<int:pk>/', views.plot_detail_manager, name='plot-detail'),
    
    # 3. Sensor Data Endpoints
    path('records/add/', views.record_data, name='add-sensor-data'),
    path('records/<int:pk>/', views.record_detail_manager, name='record-detail'),

    path('user/', views.current_user, name='current-user'),

    # 4. User Registration Endpoint
    path('register/', views.register_user_web, name='register-user'),

    # This direct reference is safer than using auth_views.obtain_auth_token
    path('api-token-auth/', obtain_auth_token),
]