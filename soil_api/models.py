from django.db import models
from django.contrib.auth.models import User

class FarmPlot(models.Model):
    farmer = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100) # e.g., "Plot A"
    crop_type = models.CharField(max_length=100) # e.g., "Rice Field"
    sensor_id = models.CharField(max_length=50, blank=True, null=True) # Allowed to be empty/null initially
    location = models.CharField(max_length=255) # e.g., "North Sector"
    
    def __str__(self):
        return f"{self.name} ({self.sensor_id or 'No Sensor'})"

class SoilRecord(models.Model):
    plot = models.ForeignKey(FarmPlot, on_delete=models.CASCADE, related_name='records')
    soil_moisture = models.FloatField()
    soil_temperature = models.FloatField()
    ph_level = models.FloatField()
    battery_percentage = models.IntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Update for {self.plot.name} at {self.timestamp}"