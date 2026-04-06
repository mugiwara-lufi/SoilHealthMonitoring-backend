from django.urls import path
from . import views

urlpatterns = [
    # 1. Manage Plots (Farm Overview Screen)
    path('plots/', views.plot_manager, name='plot-list'),
    
    # 2. Specific Plot Details & Monitoring (Plot A, Plot B)
    path('plots/<int:pk>/', views.plot_detail_manager, name='plot-detail'),
    
    # 3. Sensor Data Endpoint (For the ESP32 to send Moisture/Temp/PH/Battery)
    path('records/add/', views.record_data, name='add-sensor-data'),
    path('records/<int:pk>/', views.record_detail_manager, name='record-detail'),

    path('user/', views.current_user, name='current-user'),
]