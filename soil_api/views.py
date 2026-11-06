import random
import requests
from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.models import User
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

from .models import FarmPlot, SoilRecord, UserProfile
from .serializers import UserSerializer, FarmPlotSerializer, SoilRecordSerializer, RegisterSerializer
from .forms import UserRegistrationForm

SUPABASE_URL = "https://fpisfwcphgjcvxomzpko.supabase.co/rest/v1/soil_records"
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
       
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'phone': phone_num,
            'is_staff': user.is_staff or user.is_superuser,
            'role': role
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