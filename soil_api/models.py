from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    owner = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='sub_farmers'
    ) 

    def __str__(self):
        return f"Profile for {self.user.username}"


class FarmPlot(models.Model):
    farmer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='farm_plots')
    name = models.CharField(max_length=100)
    crop_type = models.CharField(max_length=100)
    sensor_id = models.CharField(max_length=50, blank=True, null=True)
    location = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.name} ({self.sensor_id or 'No Sensor'})"


class SoilRecord(models.Model):
    plot = models.ForeignKey(FarmPlot, on_delete=models.CASCADE, related_name='records')
    soil_moisture = models.FloatField()
    soil_temperature = models.FloatField()
    ec = models.FloatField(default=0.0) 
    ph_level = models.FloatField()
    nitrogen = models.FloatField(default=0.0)
    phosphorus = models.FloatField(default=0.0)
    potassium = models.FloatField(default=0.0)
    battery_percentage = models.IntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Update for {self.plot.name} at {self.timestamp}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)