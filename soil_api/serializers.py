from rest_framework import serializers
from .models import FarmPlot, SoilRecord, UserProfile
from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    owner_id = serializers.SerializerMethodField()
    owner_username = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'password', 'name', 'email', 
            'role', 'is_active', 'is_staff', 'is_superuser', 'owner_id', 'owner_username'
        ]

    def get_name(self, obj):
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return full_name if full_name else obj.username

    def get_role(self, obj):
        return 'ADMIN' if (obj.is_staff or obj.is_superuser) else 'FARMER'

    def get_owner_id(self, obj):
        if hasattr(obj, 'profile') and obj.profile.owner:
            return obj.profile.owner.id
        return None

    def get_owner_username(self, obj):
        if hasattr(obj, 'profile') and obj.profile.owner:
            return obj.profile.owner.username
        return None

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    owner_email = serializers.EmailField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = User
        fields = ('username', 'password', 'email', 'first_name', 'last_name', 'owner_email')

    def create(self, validated_data):
        owner_email = validated_data.pop('owner_email', None)
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            email=validated_data.get('email', ''),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )

        if owner_email:
            try:
                owner_user = User.objects.get(email=owner_email)
                if hasattr(user, 'profile'):
                    user.profile.owner = owner_user
                    user.profile.save()
            except User.DoesNotExist:
                pass 

        return user


class SoilRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SoilRecord
        fields = [
            'id', 'plot', 'soil_moisture', 'soil_temperature', 
            'ec', 'ph_level', 'nitrogen', 'phosphorus', 
            'potassium', 'battery_percentage', 'timestamp'
        ]


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
        recent_records = obj.records.all()[:20]
        return SoilRecordSerializer(recent_records, many=True).data