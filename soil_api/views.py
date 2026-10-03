from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg, Prefetch
from django.db.models.functions import TruncDay, TruncHour

from .models import FarmPlot, SoilRecord
from .serializers import (
    FarmPlotSerializer, 
    SoilRecordSerializer, 
    RegisterSerializer
)
from .forms import UserRegistrationForm

# --- HOME SCREEN VIEW ---
def home_screen(request):
    return render(request, 'home.html')

# --- WEB REGISTRATION VIEW ---
def register_user_web(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            login(request, user)
            return redirect('plot-list') 
    else:
        form = UserRegistrationForm()
    return render(request, 'register_web.html', {'form': form})

# --- MOBILE API REGISTRATION VIEW ---
@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register_user(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"message": "User created"}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    return Response({
        "id": request.user.id,
        "username": request.user.username,
        "email": request.user.email,
        "full_name": f"{request.user.first_name} {request.user.last_name}"
    })

# --- PLOT MANAGEMENT ---
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])  # Set to AllowAny or IsAuthenticated depending on your auth strategy
def plot_manager(request):
    if request.method == 'GET':
        # Prefetch soil records sorted newest-first so records[0] in frontend is always the latest update
        records_prefetch = Prefetch(
            'records',
            queryset=SoilRecord.objects.order_by('-timestamp')
        )

        if request.user.is_authenticated:
            plots = FarmPlot.objects.filter(farmer=request.user).prefetch_related(records_prefetch)
        else:
            plots = FarmPlot.objects.all().prefetch_related(records_prefetch)

        serializer = FarmPlotSerializer(plots, many=True) 
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = FarmPlotSerializer(data=request.data)
        if serializer.is_valid():
            farmer_user = request.user if request.user.is_authenticated else None
            serializer.save(farmer=farmer_user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])  # Allows public PATCH / GET updates for testing
def plot_detail_manager(request, pk):
    try:
        # Sort pre-fetched records newest-first for the detail view as well
        records_prefetch = Prefetch('records', queryset=SoilRecord.objects.order_by('-timestamp'))
        plot = FarmPlot.objects.prefetch_related(records_prefetch).get(pk=pk)
    except FarmPlot.DoesNotExist:
        return Response({"error": "Plot not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = FarmPlotSerializer(plot)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        serializer = FarmPlotSerializer(
            plot, 
            data=request.data, 
            partial=(request.method == 'PATCH') 
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        plot.delete()
        return Response({"message": "Plot removed"}, status=status.HTTP_204_NO_CONTENT)

# --- SENSOR DATA INGESTION ---
@api_view(['POST'])
@permission_classes([AllowAny])
def record_data(request):
    serializer = SoilRecordSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
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

# --- ANALYTICS ENDPOINT ---
@api_view(['GET'])
@permission_classes([AllowAny])
def get_ph_analytics(request, plot_id):
    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    twenty_four_hours_ago = now - timedelta(hours=24)

    # 1. Weekly pH
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

    # 2. Hourly pH
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