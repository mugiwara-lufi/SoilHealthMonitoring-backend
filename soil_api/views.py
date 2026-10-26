import requests
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes, authentication_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status, viewsets, permissions
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from django.db.models import Avg, Prefetch, Q
from django.db.models.functions import TruncDay, TruncHour
from django.contrib.auth.models import User
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token

from .models import FarmPlot, SoilRecord, UserProfile
from .serializers import UserSerializer, FarmPlotSerializer, SoilRecordSerializer, RegisterSerializer
from .forms import UserRegistrationForm

SUPABASE_URL = "https://fpisfwcphgjcvxomzpko.supabase.co/rest/v1/soil_records"
SUPABASE_KEY = "sb_publishable_cyQgbi_v02dkhswabEBWoQ_3exGPlaK"

class CustomObtainAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        role = 'admin' if (user.is_staff or user.is_superuser) else 'user'
       
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'username': user.username,
            'email': user.email,
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

    @action(detail=True, methods=['post'], url_path='assign-plots')
    def assign_plots(self, request, pk=None):
        target_user = self.get_object()
        plot_ids = request.data.get('plot_ids', [])
       
        if not isinstance(plot_ids, list):
            return Response(
                {'error': 'plot_ids must be a list of integers.'},
                status=status.HTTP_400_BAD_REQUEST
            )
           
        if request.user.is_superuser:
            plots = FarmPlot.objects.filter(id__in=plot_ids)
        else:
            sub_farmer_ids = UserProfile.objects.filter(owner=request.user).values_list('user_id', flat=True)
            plots = FarmPlot.objects.filter(
                Q(id__in=plot_ids) & (Q(farmer=request.user) | Q(farmer_id__in=sub_farmer_ids))
            )
           
        updated_count = plots.update(farmer=target_user)
        return Response({
            'message': f'Successfully assigned {updated_count} plot(s) to {target_user.username}.',
            'assigned_plot_ids': list(plots.values_list('id', flat=True))
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
            login(request, user)
            return redirect('plot-list')
    else:
        form = UserRegistrationForm()
    return render(request, 'register_web.html', {'form': form})

@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register_user(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response({"message": "User created", "id": user.id}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    role = 'admin' if (request.user.is_staff or request.user.is_superuser) else 'user'
    return Response({
        "id": request.user.id,
        "username": request.user.username,
        "email": request.user.email,
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
            # INHERITANCE LOGIC: If the hired worker registered with an owner's email, 
            # they inherit access to view the owner's plots and sensors alongside their own.
            profile = getattr(request.user, 'profile', None)
            owner = profile.owner if profile else None
            if owner:
                plots = FarmPlot.objects.filter(Q(farmer=request.user) | Q(farmer=owner)).prefetch_related(records_prefetch)
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
        return Response({"message": "Plot removed"}, status=status.HTTP_204_NO_CONTENT)

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
        return Response({"message": "Record deleted"}, status=status.HTTP_204_NO_CONTENT)

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
        'weekly': {
            'labels': weekly_labels,
            'values': weekly_values
        },
        'hourly': {
            'labels': hourly_labels,
            'values': hourly_values
        }
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