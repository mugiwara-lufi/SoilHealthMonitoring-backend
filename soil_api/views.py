from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import render, redirect
from django.contrib.auth import login

# Explicitly import these to ensure we can override defaults
from rest_framework.authentication import TokenAuthentication, BasicAuthentication

from .models import FarmPlot, SoilRecord
from .serializers import (
    FarmPlotSerializer, 
    FarmPlotListSerializer, 
    SoilRecordSerializer, 
    RegisterSerializer
)
from .forms import UserRegistrationForm

# --- HOME SCREEN VIEW ---
def home_screen(request):
    return render(request, 'home.html')

# --- WEB-BASED REGISTRATION VIEW (Standard Form) ---
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
@authentication_classes([]) # Force Django to ignore Session/CSRF checks
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
@permission_classes([IsAuthenticated])
def plot_manager(request):
    if request.method == 'GET':
        plots = FarmPlot.objects.filter(farmer=request.user)
        serializer = FarmPlotSerializer(plots, many=True) 
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = FarmPlotSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(farmer=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def plot_detail_manager(request, pk):
    try:
        plot = FarmPlot.objects.get(pk=pk, farmer=request.user)
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
@permission_classes([IsAuthenticated])
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