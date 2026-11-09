# config/urls.py (or your main project urls.py)

from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from soil_api import views

router = DefaultRouter()
router.register(r'users', views.UserViewSet, basename='user')

urlpatterns = [
    path('', include(router.urls)),

    # Registration & Verification
    path('send-otp/', views.send_registration_otp, name='send-otp'),
    path('verify-register/', views.verify_and_register, name='verify-register'),

    # Farm Plots
    path('plots/', views.plot_manager, name='plot-list'),
    path('plots/admin-manageable/', views.admin_manageable_plots, name='admin-manageable-plots'),
    path('plots/<int:pk>/', views.plot_detail_manager, name='plot-detail'),
    path('plots/<int:plot_id>/ph-analytics/', views.get_ph_analytics, name='ph-analytics'),

    # Soil Records
    path('records/add/', views.record_data, name='add-sensor-data'),
    path('records/<int:pk>/', views.record_detail_manager, name='record-detail'),
    path('soil-records/', views.get_supabase_records, name='supabase-soil-records'),

    # User
    path('user/', views.current_user, name='current-user'),
    path('register-web/', views.register_user_web, name='register-user-web'),
    path('register/', views.register_user, name='api-register-user'),
    path('api-token-auth/', views.CustomObtainAuthToken.as_view(), name='api-token-auth'),

    # Sensor Management
    path('sensors/register/', views.register_sensor, name='sensor-register'),
    path('sensors/available/', views.available_sensors, name='sensor-available'),
    path('sensors/claim/', views.claim_sensor, name='sensor-claim'),
    path('sensors/disconnect/', views.disconnect_sensor, name='sensor-disconnect'),
    path('sensors/latest/', views.latest_sensor_reading, name='sensor-latest'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)