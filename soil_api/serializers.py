from rest_framework import serializers
from .models import FarmPlot, SoilRecord

class SoilRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SoilRecord
        fields = '__all__'

# 1. New "Lite" Serializer for the Plot List
class FarmPlotListSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmPlot
        fields = ['id', 'name', 'crop_type'] # Only shows these three fields

# 2. "Full" Serializer for the Plot Detail
class FarmPlotSerializer(serializers.ModelSerializer):
    records = SoilRecordSerializer(many=True, read_only=True)

    class Meta:
        model = FarmPlot
        fields = ['id', 'farmer', 'name', 'crop_type', 'sensor_id', 'location', 'records']