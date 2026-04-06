from django.contrib import admin
from .models import FarmPlot, SoilRecord

# Register your models here
@admin.register(FarmPlot)
class FarmPlotAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'crop_type', 'farmer', 'sensor_id')
    search_fields = ('name', 'sensor_id')

@admin.register(SoilRecord)
class SoilRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'plot', 'soil_moisture', 'soil_temperature', 'timestamp')
    list_filter = ('plot', 'timestamp')