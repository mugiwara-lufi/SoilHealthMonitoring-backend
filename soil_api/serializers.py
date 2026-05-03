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
        fields = '__all__'

class FarmPlotListSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmPlot
        fields = ['id', 'name', 'crop_type']

class FarmPlotSerializer(serializers.ModelSerializer):
    records = SoilRecordSerializer(many=True, read_only=True)
    # ADD THIS LINE: It grabs the username from the related User model
    farmer_username = serializers.CharField(source='farmer.username', read_only=True)

    class Meta:
        model = FarmPlot
        # Add 'farmer_username' to the fields list
        fields = ['id', 'farmer', 'farmer_username', 'name', 'crop_type', 'sensor_id', 'location', 'records']
        read_only_fields = ['farmer']