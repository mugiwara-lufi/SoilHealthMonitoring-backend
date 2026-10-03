from rest_framework import serializers
from .models import FarmPlot, SoilRecord
from django.contrib.auth.models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('username', 'password', 'email', 'first_name', 'last_name')

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            email=validated_data.get('email', ''),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        return user


class SoilRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SoilRecord
        fields = [
            'id', 'plot', 'soil_moisture', 'soil_temperature', 
            'humidity', 'ph_level', 'nitrogen', 'phosphorus', 
            'potassium', 'battery_percentage', 'timestamp'
        ]


# "Lite" Serializer for the Plot List
class FarmPlotListSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmPlot
        fields = ['id', 'name', 'crop_type']


class FarmPlotSerializer(serializers.ModelSerializer):
    records = serializers.SerializerMethodField()
    farmer_username = serializers.CharField(source='farmer.username', read_only=True)
    sensor_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = FarmPlot
        fields = ['id', 'farmer', 'farmer_username', 'name', 'crop_type', 'sensor_id', 'location', 'records']
        read_only_fields = ['farmer']

    def get_records(self, obj):
        # Fetch records sorted by NEWEST first, limiting to the last 20 entries
        recent_records = obj.records.order_by('-timestamp')[:20]
        return SoilRecordSerializer(recent_records, many=True).data