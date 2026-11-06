from rest_framework import serializers
from .models import FarmPlot, SoilRecord, UserProfile
from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    old_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    owner_id = serializers.SerializerMethodField()
    owner_username = serializers.SerializerMethodField()
    phone = serializers.CharField(source='profile.phone', required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'password', 'old_password', 'first_name', 'last_name', 'name', 'email',
            'phone', 'role', 'is_active', 'is_staff', 'is_superuser', 'owner_id', 'owner_username'
        ]
        extra_kwargs = {
            'is_active': {'required': False},
            'is_staff': {'required': False},
        }

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
        profile_data = validated_data.pop('profile', {})
        password = validated_data.pop('password', None)
        validated_data.pop('old_password', None)
       
        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
            user.save()
           
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if 'phone' in profile_data:
            profile.phone = profile_data['phone']
            profile.save()
           
        return user

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        password = validated_data.pop('password', None)
        old_password = validated_data.pop('old_password', None)

        # Safely update standard User fields present in validated_data
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
           
        if password:
            request = self.context.get('request')
            # Require and check old_password when a user updates their own password
            if request and request.user == instance:
                if not old_password:
                    raise serializers.ValidationError({'old_password': 'Current password is required.'})
                if not instance.check_password(old_password):
                    raise serializers.ValidationError({'old_password': 'Incorrect current password.'})
            instance.set_password(password)
           
        instance.save()

        # Update phone number in UserProfile if provided
        if profile_data and 'phone' in profile_data:
            profile, _ = UserProfile.objects.get_or_create(user=instance)
            profile.phone = profile_data['phone']
            profile.save()

        return instance


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    owner_email = serializers.EmailField(required=False, allow_blank=True, write_only=True)
    phone = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = User
        fields = ('username', 'password', 'email', 'first_name', 'last_name', 'owner_email', 'phone')

    def create(self, validated_data):
        owner_email = validated_data.pop('owner_email', None)
        phone = validated_data.pop('phone', None)

        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            email=validated_data.get('email', ''),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )

        profile, _ = UserProfile.objects.get_or_create(user=user)
        if phone:
            profile.phone = phone

        if owner_email:
            try:
                owner_user = User.objects.get(email=owner_email)
                profile.owner = owner_user
            except User.DoesNotExist:
                pass

        profile.save()
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
    owner_id = serializers.SerializerMethodField()
    owner_username = serializers.SerializerMethodField()
    owner_email = serializers.SerializerMethodField()

    class Meta:
        model = FarmPlot
        fields = [
            'id', 'farmer', 'farmer_username', 'name', 'crop_type',
            'sensor_id', 'location', 'records', 'owner_id', 'owner_username', 'owner_email'
        ]
        read_only_fields = ['farmer']

    def get_records(self, obj):
        recent_records = obj.records.all()[:20]
        return SoilRecordSerializer(recent_records, many=True).data

    def get_owner_id(self, obj):
        if hasattr(obj.farmer, 'profile') and obj.farmer.profile.owner:
            return obj.farmer.profile.owner.id
        return obj.farmer.id

    def get_owner_username(self, obj):
        if hasattr(obj.farmer, 'profile') and obj.farmer.profile.owner:
            return obj.farmer.profile.owner.username
        return obj.farmer.username

    def get_owner_email(self, obj):
        if hasattr(obj.farmer, 'profile') and obj.farmer.profile.owner:
            return obj.farmer.profile.owner.email
        return obj.farmer.email