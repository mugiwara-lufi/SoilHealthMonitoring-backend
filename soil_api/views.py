import random
import requests
import os
from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Avg, Prefetch, Q
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from django.core.cache import cache

from rest_framework import status, viewsets, permissions
from rest_framework.decorators import api_view, permission_classes, authentication_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token

from .models import FarmPlot, SoilRecord, UserProfile, SensorDevice
from .serializers import UserSerializer, FarmPlotSerializer, SoilRecordSerializer, RegisterSerializer
from .forms import UserRegistrationForm

SUPABASE_URL = "https://fpisfwcphgjcvxomzpko.supabase.co/rest/v1/soil_records"
SUPABASE_COMMANDS_URL = "https://fpisfwcphgjcvxomzpko.supabase.co/rest/v1/device_commands"
SUPABASE_KEY = "sb_publishable_cyQgbi_v02dkhswabEBWoQ_3exGPlaK"


# --- OTP & IN-APP REGISTRATION VIEWS ---

@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def send_registration_otp(request):
    username = request.data.get('username', '').strip()
    email = request.data.get('email', '').strip().lower()
    owner_email = request.data.get('owner_email', '').strip().lower()
    role = request.data.get('role', 'user').strip()  # 'admin' or 'user'
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    password = request.data.get('password', '')

    if not email or not username:
        return Response({'error': 'Username and Email address are required.'}, status=status.HTTP_400_BAD_REQUEST)

    # Check for existing accounts
    if User.objects.filter(username=username).exists():
        return Response({'error': 'Username is already taken.'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(email=email).exists():
        return Response({'error': 'An account with this email address already exists.'}, status=status.HTTP_400_BAD_REQUEST)

    is_linking_to_owner = bool(owner_email and owner_email != email)

    if is_linking_to_owner:
        owner_user = User.objects.filter(email=owner_email).first()
        if not owner_user:
            return Response(
                {'error': f'No registered Farm Owner found with email: {owner_email}'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Directly create account with is_active = False so it needs admin/owner in-app approval
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_active=False  # Pending in-app activation
        )
        UserProfile.objects.update_or_create(
            user=user,
            defaults={'owner': owner_user}
        )

        # GENERATE AUTH TOKEN IMMEDIATELY UPON REGISTRATION TO FIX MISSING TOKEN ROW
        token, _ = Token.objects.get_or_create(user=user)

        return Response({
            "message": "Account created successfully. Pending Farm Owner approval.",
            "target_email": owner_email,
            "is_owner_linking": True,
            "token": token.key,
            "user_id": user.id
        }, status=status.HTTP_201_CREATED)

    # STANDARD REGISTRATION FLOW WITH OTP
    otp_code = str(random.randint(100000, 999999))
    cache.set(f"reg_otp_{email}", otp_code, timeout=600)

    is_admin = role.lower() == 'admin'
    subject = f"JJMAP - {'Farm Owner / Admin' if is_admin else 'Farmer'} Email Verification Code"
    message = (
        f"Hello {username},\n\n"
        f"Thank you for registering on JJMAP Soil Health Monitor.\n\n"
        f"Your Verification Code is: {otp_code}\n\n"
        f"Enter this code in the app to complete your registration. Code expires in 10 minutes."
    )

    try:
        send_mail(
            subject,
            message,
            None,
            [email],
            fail_silently=False,
        )
        return Response({
            "message": f"Verification code sent to {email}",
            "target_email": email,
            "is_owner_linking": False
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": f"Failed to send email: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def verify_and_register(request):
    """Standard OTP verification endpoint for direct account registrations."""
    otp = request.data.get('otp', '').strip()
    email = request.data.get('email', '').strip().lower()
    is_staff = request.data.get('is_staff', False) or (request.data.get('role', '').lower() == 'admin')

    cached_otp = cache.get(f"reg_otp_{email}")

    if not cached_otp or cached_otp != otp:
        return Response({'error': 'Invalid or expired verification code.'}, status=status.HTTP_400_BAD_REQUEST)

    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()

        if is_staff:
            user.is_staff = True
            user.save()

        UserProfile.objects.get_or_create(user=user)
        cache.delete(f"reg_otp_{email}")
        token, _ = Token.objects.get_or_create(user=user)

        return Response({
            "message": "Account verified and registered successfully.",
            "token": token.key,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "is_staff": user.is_staff,
            "role": 'admin' if user.is_staff else 'user'
        }, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- LEGACY DIRECT REGISTER (DISABLED TO MANDATE OTP) ---

@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register_user(request):
    return Response(
        {"error": "Direct registration is disabled. Please complete email verification."},
        status=status.HTTP_403_FORBIDDEN
    )


# --- EXISTING VIEWS ---

class CustomObtainAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        # Check if account is activated / approved by Farm Owner
        if not user.is_active:
            return Response(
                {'non_field_errors': ['Your account is not approved yet. Please wait for the Farm Owner to activate it.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        token, created = Token.objects.get_or_create(user=user)
        role = 'admin' if (user.is_staff or user.is_superuser) else 'user'
        phone_num = user.profile.phone if hasattr(user, 'profile') and user.profile.phone else ''
        
        # FIX: Extract the profile image URL without changing the overall response structure
        user_data = UserSerializer(user, context={'request': request}).data
        profile_image = user_data.get('profile_image', None)
       
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'phone': phone_num,
            'is_staff': user.is_staff or user.is_superuser,
            'role': role,
            'profile_image': profile_image  # <-- Just appending this to your existing fields
        })


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return User.objects.all().order_by('-date_joined')
       
        sub_farmer_ids = UserProfile.objects.filter(owner=user).values_list('user_id', flat=True)
        return User.objects.filter(
            Q(id__in=sub_farmer_ids) | Q(id=user.id)
        ).distinct().order_by('-date_joined')

    def perform_create(self, serializer):
        created_user = serializer.save()
        UserProfile.objects.get_or_create(
            user=created_user,
            defaults={'owner': self.request.user}
        )
        # Ensure token is created even when created via admin panel
        Token.objects.get_or_create(user=created_user)

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=True, methods=['patch', 'post'], permission_classes=[AllowAny], url_path='set-active')
    def set_active(self, request, pk=None):
        """Allow quick toggling of user activation status without strict token barriers."""
        try:
            target_user = self.get_queryset().get(pk=pk) if not request.user.is_superuser else User.objects.get(pk=pk)
        except User.DoesNotExist:
            # Fallback direct lookup if queryset filters restrict it
            try:
                target_user = User.objects.get(pk=pk)
            except User.DoesNotExist:
                return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        is_active_val = request.data.get('is_active')
        if is_active_val is not None:
            target_user.is_active = bool(is_active_val)
            target_user.save()

        is_staff_val = request.data.get('is_staff')
        if is_staff_val is not None:
            target_user.is_staff = bool(is_staff_val)
            target_user.save()

        return Response({
            'message': f'User @{target_user.username} status updated successfully.',
            'id': target_user.id,
            'is_active': target_user.is_active,
            'is_staff': target_user.is_staff
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='assign-plots')
    def assign_plots(self, request, pk=None):
        target_user = self.get_object()
        plot_ids = request.data.get('plot_ids', [])
       
        if not isinstance(plot_ids, list):
            return Response({'error': 'plot_ids must be a list of integers.'}, status=status.HTTP_400_BAD_REQUEST)
           
        try:
            plot_ids = [int(pid) for pid in plot_ids]
        except (ValueError, TypeError):
            return Response({'error': 'All plot_ids must be valid integers.'}, status=status.HTTP_400_BAD_REQUEST)
           
        if request.user.is_superuser:
            manageable_plots = FarmPlot.objects.all()
        else:
            sub_farmer_ids = UserProfile.objects.filter(owner=request.user).values_list('user_id', flat=True)
            manageable_plots = FarmPlot.objects.filter(
                Q(farmer=request.user) | Q(farmer_id__in=sub_farmer_ids)
            )
           
        manageable_plots.filter(farmer=target_user).exclude(id__in=plot_ids).update(farmer=request.user)
        assigned_plots = manageable_plots.filter(id__in=plot_ids)
        assigned_plots.update(farmer=target_user)

        return Response({
            'message': f'Successfully updated plot assignments for {target_user.username}.',
            'assigned_plot_ids': list(assigned_plots.values_list('id', flat=True))
        }, status=status.HTTP_200_OK)


def home_screen(request):
    return render(request, 'home.html')


def register_user_web(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            UserProfile.objects.get_or_create(user=user)
            Token.objects.get_or_create(user=user)
            login(request, user)
            return redirect('plot-list')
    else:
        form = UserRegistrationForm()
    return render(request, 'register_web.html', {'form': form})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    role = 'admin' if (request.user.is_staff or request.user.is_superuser) else 'user'
    phone_num = request.user.profile.phone if hasattr(request.user, 'profile') and request.user.profile.phone else ''
    return Response({
        "id": request.user.id,
        "username": request.user.username,
        "first_name": request.user.first_name,
        "last_name": request.user.last_name,
        "email": request.user.email,
        "phone": phone_num,
        "full_name": f"{request.user.first_name} {request.user.last_name}".strip(),
        "role": role
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def plot_manager(request):
    records_prefetch = Prefetch('records', queryset=SoilRecord.objects.order_by('-timestamp'))
   
    if request.method == 'GET':
        if request.user.is_superuser:
            plots = FarmPlot.objects.all().prefetch_related(records_prefetch)
        elif request.user.is_staff:
            sub_farmer_ids = UserProfile.objects.filter(owner=request.user).values_list('user_id', flat=True)
            plots = FarmPlot.objects.filter(
                Q(farmer=request.user) | Q(farmer_id__in=sub_farmer_ids)
            ).prefetch_related(records_prefetch)
        else:
            plots = FarmPlot.objects.filter(farmer=request.user).prefetch_related(records_prefetch)
           
        serializer = FarmPlotSerializer(plots, many=True)
        return Response(serializer.data)
       
    elif request.method == 'POST':
        serializer = FarmPlotSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(farmer=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_manageable_plots(request):
    records_prefetch = Prefetch('records', queryset=SoilRecord.objects.order_by('-timestamp'))
    if request.user.is_superuser:
        plots = FarmPlot.objects.all().prefetch_related(records_prefetch)
    else:
        sub_farmer_ids = UserProfile.objects.filter(owner=request.user).values_list('user_id', flat=True)
        plots = FarmPlot.objects.filter(
            Q(farmer=request.user) | Q(farmer_id__in=sub_farmer_ids)
        ).prefetch_related(records_prefetch)
       
    serializer = FarmPlotSerializer(plots, many=True)
    return Response(serializer.data)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def plot_detail_manager(request, pk):
    try:
        records_prefetch = Prefetch('records', queryset=SoilRecord.objects.order_by('-timestamp'))
        plot = FarmPlot.objects.prefetch_related(records_prefetch).get(pk=pk)
    except FarmPlot.DoesNotExist:
        return Response({"error": "Plot not found"}, status=status.HTTP_404_NOT_FOUND)

    is_owner = plot.farmer == request.user
    is_managing_admin = False
   
    if hasattr(plot.farmer, 'profile') and plot.farmer.profile.owner == request.user:
        is_managing_admin = True
       
    if not (request.user.is_superuser or is_owner or is_managing_admin):
        return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

    if 'sensor_id' in request.data:
        return Response(
        {"error": "Use /api/sensors/claim/ or /api/sensors/disconnect/ to change sensor assignments."},
        status=status.HTTP_400_BAD_REQUEST
    )

    if request.method == 'GET':
        serializer = FarmPlotSerializer(plot)
        return Response(serializer.data)
       
    elif request.method in ['PUT', 'PATCH']:
        serializer = FarmPlotSerializer(plot, data=request.data, partial=(request.method == 'PATCH'))
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
       
    elif request.method == 'DELETE':
        plot.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([AllowAny])
def record_data(request):
    serializer = SoilRecordSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def record_detail_manager(request, pk):
    try:
        record = SoilRecord.objects.get(pk=pk)
    except SoilRecord.DoesNotExist:
        return Response({"error": "Record not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = SoilRecordSerializer(record)
        return Response(serializer.data)
       
    elif request.method in ['PUT', 'PATCH']:
        serializer = SoilRecordSerializer(record, data=request.data, partial=(request.method == 'PATCH'))
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
       
    elif request.method == 'DELETE':
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_ph_analytics(request, plot_id):
    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    twenty_four_hours_ago = now - timedelta(hours=24)
   
    weekly_records = (
        SoilRecord.objects.filter(plot_id=plot_id, timestamp__gte=seven_days_ago)
        .annotate(day=TruncDay('timestamp'))
        .values('day')
        .annotate(avg_ph=Avg('ph_level'))
        .order_by('day')
    )
   
    days_map = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'}
    weekly_labels = []
    weekly_values = []
   
    for item in weekly_records:
        day_name = days_map[item['day'].weekday()]
        weekly_labels.append(day_name)
        weekly_values.append(round(item['avg_ph'], 1))
       
    if not weekly_values:
        weekly_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        weekly_values = [4.0, 4.5, 5.5, 6.2, 6.5, 6.8, 7.6]

    hourly_records = (
        SoilRecord.objects.filter(plot_id=plot_id, timestamp__gte=twenty_four_hours_ago)
        .annotate(hour=TruncHour('timestamp'))
        .values('hour')
        .annotate(avg_ph=Avg('ph_level'))
        .order_by('hour')
    )
   
    hourly_labels = []
    hourly_values = []
   
    for item in hourly_records:
        hourly_labels.append(item['hour'].strftime('%H:00'))
        hourly_values.append(round(item['avg_ph'], 1))
       
    if not hourly_values:
        hourly_labels = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00', '24:00']
        hourly_values = [5.2, 5.4, 5.6, 5.8, 5.9, 5.7, 5.6]

    return Response({
        'weekly': {'labels': weekly_labels, 'values': weekly_values},
        'hourly': {'labels': hourly_labels, 'values': hourly_values}
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_supabase_records(request):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    params = {
        "select": "*",
        "order": "timestamp.desc",
        "limit": "20"
    }

    try:
        response = requests.get(SUPABASE_URL, headers=headers, params=params)
       
        if response.status_code in [200, 206]:
            supabase_data = response.json()
           
            for item in supabase_data:
                sensor_id = item.get('sensor_id')
               
                if sensor_id:
                    plot = FarmPlot.objects.filter(sensor_id=sensor_id).first()
                   
                    if plot:
                        record_time = parse_datetime(item.get('timestamp'))
                       
                        SoilRecord.objects.get_or_create(
                            plot=plot,
                            timestamp=record_time,
                            defaults={
                                'soil_moisture': item.get('soil_moisture', 0.0),
                                'soil_temperature': item.get('soil_temperature', 0.0),
                                'ec': item.get('ec', 0.0),
                                'ph_level': item.get('ph_level', 0.0),
                                'nitrogen': item.get('nitrogen', 0.0),
                                'phosphorus': item.get('phosphorus', 0.0),
                                'potassium': item.get('potassium', 0.0),
                                'battery_percentage': item.get('battery_percentage', 100),
                            }
                        )

            return Response(supabase_data, status=status.HTTP_200_OK)
        else:
            return Response(
                {"error": "Failed to fetch data from Supabase", "details": response.text},
                status=response.status_code
            )
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



# ---------------------------------------------------------------------
# SENSOR MANAGEMENT VIEWS
#
# Requires SensorDevice in models.py with fields:
# sensor_id (unique), owner (User FK), configured_by (nullable User FK),
# and plot (nullable OneToOneField to FarmPlot).
# ---------------------------------------------------------------------

def _sensor_account_owner(user):
    """Return the root Farm Owner for a user, or the user themselves."""
    profile = (
        UserProfile.objects
        .filter(user=user)
        .select_related("owner")
        .first()
    )
    return profile.owner if profile and profile.owner_id else user


def _user_can_manage_plot(user, plot):
    """Allow the plot's farmer, its Farm Owner, or a superuser."""
    if user.is_superuser or plot.farmer_id == user.id:
        return True

    return UserProfile.objects.filter(
        user=plot.farmer,
        owner=user
    ).exists()


def _supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def register_sensor(request):
    """Register a sensor to the user's Farm Owner account."""
    sensor_id = str(request.data.get("sensor_id", "")).strip()

    if not sensor_id:
        return Response(
            {"error": "sensor_id is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    account_owner = _sensor_account_owner(request.user)

    sensor, created = SensorDevice.objects.get_or_create(
        sensor_id=sensor_id,
        defaults={
            "owner": account_owner,
            "configured_by": request.user,
            "plot": None,
        }
    )

    if sensor.owner_id != account_owner.id:
        return Response(
            {"error": "This sensor is already registered to another Farm Owner account."},
            status=status.HTTP_403_FORBIDDEN
        )

    # Sensor visibility and management belong to the exact account that
    # originally configured it. Never transfer this ownership implicitly.
    if sensor.configured_by_id != request.user.id:
        return Response(
            {"error": "This sensor was configured by another account and cannot be accessed here."},
            status=status.HTTP_403_FORBIDDEN
        )

    return Response(
        {
            "message": (
                "Sensor registered successfully."
                if created
                else "Sensor is already registered to your account."
            ),
            "sensor_id": sensor.sensor_id,
            "assigned_plot_id": sensor.plot_id,
            "created": created,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def available_sensors(request):
    """
    Return only unassigned sensors registered to this Farm Owner account
    AND configured by the currently authenticated account. Sensors owned
    by another account or configured by another account are never exposed.
    """
    account_owner = _sensor_account_owner(request.user)
    plot_id = request.query_params.get("plot_id")

    if plot_id:
        try:
            plot = FarmPlot.objects.get(pk=plot_id)
        except (FarmPlot.DoesNotExist, TypeError, ValueError):
            return Response(
                {"error": "Plot not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if not _user_can_manage_plot(request.user, plot):
            return Response(
                {"error": "You cannot access this plot."},
                status=status.HTTP_403_FORBIDDEN
            )

    # Only unassigned sensors are available.
    sensors = SensorDevice.objects.filter(
        owner=account_owner,
        configured_by=request.user,
        plot__isnull=True
    ).order_by("sensor_id")

    # Exclude older assignments that exist in FarmPlot.sensor_id
    # but may not have been saved in SensorDevice.plot.
    assigned_sensor_ids = set(
        FarmPlot.objects.exclude(
            sensor_id__isnull=True
        ).exclude(
            sensor_id=""
        ).values_list("sensor_id", flat=True)
    )

    data = [
        {
            "sensor_id": sensor.sensor_id,
            "assigned_plot_id": None,
            "is_connected": False,
            "configured_by_id": sensor.configured_by_id,
        }
        for sensor in sensors
        if sensor.sensor_id not in assigned_sensor_ids
    ]

    return Response(data, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def claim_sensor(request):
    """Connect a registered sensor to exactly one plot."""
    sensor_id = str(request.data.get("sensor_id", "")).strip()
    plot_id = request.data.get("plot_id")

    if not sensor_id or not plot_id:
        return Response(
            {"error": "Both sensor_id and plot_id are required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            sensor = SensorDevice.objects.select_for_update().get(
                sensor_id=sensor_id
            )
            plot = FarmPlot.objects.select_for_update().get(pk=plot_id)

            account_owner = _sensor_account_owner(request.user)

            if sensor.owner_id != account_owner.id:
                return Response(
                    {"error": "This sensor is not registered to your Farm Owner account."},
                    status=status.HTTP_403_FORBIDDEN
                )

            if sensor.configured_by_id != request.user.id:
                return Response(
                    {"error": "Only the account that configured this sensor can connect it."},
                    status=status.HTTP_403_FORBIDDEN
                )

            if not _user_can_manage_plot(request.user, plot):
                return Response(
                    {"error": "You cannot manage this plot."},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Do not allow a sensor assigned to another plot.
            if sensor.plot_id and sensor.plot_id != plot.id:
                return Response(
                    {
                        "error": (
                            f"{sensor_id} is already connected to another plot. "
                            "Disconnect it first."
                        )
                    },
                    status=status.HTTP_409_CONFLICT
                )

            # Check legacy FarmPlot assignments too.
            legacy_assignment = FarmPlot.objects.filter(
                sensor_id=sensor_id
            ).exclude(pk=plot.pk).first()

            if legacy_assignment:
                return Response(
                    {
                        "error": (
                            f"{sensor_id} is already assigned to "
                            f"{legacy_assignment.name}."
                        )
                    },
                    status=status.HTTP_409_CONFLICT
                )

            # A plot can only have one sensor.
            other_sensor = SensorDevice.objects.filter(
                plot=plot
            ).exclude(pk=sensor.pk).first()

            if other_sensor:
                return Response(
                    {"error": "This plot already has another sensor assigned."},
                    status=status.HTTP_409_CONFLICT
                )

            if plot.sensor_id and plot.sensor_id != sensor_id:
                return Response(
                    {"error": "This plot already has another sensor assigned."},
                    status=status.HTTP_409_CONFLICT
                )

            sensor.plot = plot
            sensor.save(update_fields=["plot"])

            plot.sensor_id = sensor_id
            plot.save(update_fields=["sensor_id"])

    except SensorDevice.DoesNotExist:
        return Response(
            {"error": "Sensor is not registered to your account."},
            status=status.HTTP_404_NOT_FOUND
        )

    except FarmPlot.DoesNotExist:
        return Response(
            {"error": "Plot not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except (TypeError, ValueError):
        return Response(
            {"error": "Invalid plot_id."},
            status=status.HTTP_400_BAD_REQUEST
        )

    return Response(
        {
            "message": "Sensor connected successfully.",
            "sensor_id": sensor.sensor_id,
            "plot_id": plot.id,
        },
        status=status.HTTP_200_OK
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def disconnect_sensor(request):
    """
    Remove the sensor from its current plot but retain its
    registration and account ownership, and send a Wi-Fi reset command.
    """
    sensor_id = str(request.data.get("sensor_id", "")).strip()
    plot_id = request.data.get("plot_id")

    if not sensor_id:
        return Response(
            {"error": "sensor_id is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            sensor = SensorDevice.objects.select_for_update().get(
                sensor_id=sensor_id
            )

            account_owner = _sensor_account_owner(request.user)

            if sensor.owner_id != account_owner.id:
                return Response(
                    {"error": "This sensor is not registered to your Farm Owner account."},
                    status=status.HTTP_403_FORBIDDEN
                )

            if sensor.configured_by_id != request.user.id:
                return Response(
                    {"error": "Only the account that configured this sensor can disconnect it."},
                    status=status.HTTP_403_FORBIDDEN
                )

            if sensor.plot_id is None:
                return Response(
                    {
                        "message": "Sensor is already disconnected.",
                        "sensor_id": sensor.sensor_id,
                    },
                    status=status.HTTP_200_OK
                )

            if plot_id is not None and str(sensor.plot_id) != str(plot_id):
                return Response(
                    {"error": "The supplied plot_id does not match the sensor's assignment."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            plot = FarmPlot.objects.select_for_update().get(
                pk=sensor.plot_id
            )

            if not _user_can_manage_plot(request.user, plot):
                return Response(
                    {"error": "You cannot manage the currently assigned plot."},
                    status=status.HTTP_403_FORBIDDEN
                )

            sensor.plot = None
            sensor.save(update_fields=["plot"])

            if plot.sensor_id == sensor.sensor_id:
                plot.sensor_id = None
                plot.save(update_fields=["sensor_id"])

        # Create the remote reset command in Supabase
        command_payload = {
            "sensor_id": sensor.sensor_id,
            "command": "RESET_WIFI",
            "status": "PENDING"
        }
       
        try:
            cmd_resp = requests.post(
                SUPABASE_COMMANDS_URL,
                headers=_supabase_headers(),
                json=command_payload,
                timeout=10
            )
            if cmd_resp.status_code in (200, 201, 204):
                wifi_status = "sent"
            else:
                wifi_status = f"not_sent_status_{cmd_resp.status_code}"
        except Exception as e:
            wifi_status = "not_sent_error"

    except SensorDevice.DoesNotExist:
        return Response(
            {"error": "Sensor not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except FarmPlot.DoesNotExist:
        # Clear stale assignment if its plot was deleted.
        sensor.plot = None
        sensor.save(update_fields=["plot"])
        wifi_status = "not_sent_stale"

    except (TypeError, ValueError):
        return Response(
            {"error": "Invalid plot_id."},
            status=status.HTTP_400_BAD_REQUEST
        )

    return Response(
        {
            "message": "Sensor disconnected. Registration and ownership were retained.",
            "sensor_id": sensor.sensor_id,
            "wifi_reset_command": wifi_status
        },
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def latest_sensor_reading(request):
    """
    Retrieve the latest reading directly from Supabase for the
    sensor assigned to the requested plot.
    """
    plot_id = request.query_params.get("plot_id")

    if not plot_id:
        return Response(
            {"error": "plot_id query parameter is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        plot = FarmPlot.objects.get(pk=plot_id)

    except (FarmPlot.DoesNotExist, TypeError, ValueError):
        return Response(
            {"error": "Plot not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    if not _user_can_manage_plot(request.user, plot):
        return Response(
            {"error": "You cannot access this plot."},
            status=status.HTTP_403_FORBIDDEN
        )

    account_owner = _sensor_account_owner(request.user)

    sensor = SensorDevice.objects.filter(
        owner=account_owner,
        configured_by=request.user,
        plot=plot
    ).first()

    # Verify both sides of the assignment.
    if (
        not sensor
        or not plot.sensor_id
        or sensor.sensor_id != plot.sensor_id
    ):
        return Response(
            {
                "sensor_id": None,
                "reading": None,
                "message": "No registered sensor is connected to this plot."
            },
            status=status.HTTP_200_OK
        )

    params = {
        "select": "*",
        "sensor_id": f"eq.{sensor.sensor_id}",
        "order": "timestamp.desc",
        "limit": "1",
    }

    try:
        response = requests.get(
            SUPABASE_URL,
            headers=_supabase_headers(),
            params=params,
            timeout=15
        )

        if response.status_code not in (200, 206):
            return Response(
                {
                    "error": "Failed to fetch readings from Supabase.",
                    "details": response.text,
                },
                status=status.HTTP_502_BAD_GATEWAY
            )

        rows = response.json()

        if not isinstance(rows, list):
            return Response(
                {"error": "Unexpected response format from Supabase."},
                status=status.HTTP_502_BAD_GATEWAY
            )

        if not rows:
            return Response(
                {
                    "sensor_id": sensor.sensor_id,
                    "reading": None,
                    "message": "No readings have been uploaded by this sensor yet."
                },
                status=status.HTTP_200_OK
            )

        return Response(
            {
                "sensor_id": sensor.sensor_id,
                "reading": rows[0],
            },
            status=status.HTTP_200_OK
        )

    except requests.RequestException as exc:
        return Response(
            {
                "error": "Could not connect to Supabase.",
                "details": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY
        )

    except ValueError:
        return Response(
            {"error": "Supabase returned invalid JSON."},
            status=status.HTTP_502_BAD_GATEWAY
        )