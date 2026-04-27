from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import FarmPlot, SoilRecord
from .serializers import FarmPlotSerializer, FarmPlotListSerializer, SoilRecordSerializer
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from .serializers import RegisterSerializer
from django.shortcuts import render
from django.shortcuts import render, redirect
from django.contrib.auth import login
from .forms import UserRegistrationForm # Import the form we just created

# --- HOME SCREEN VIEW ---
def home_screen(request):
    return render(request, 'home.html')

# --- WEB-BASED REGISTRATION VIEW (The Fill-up Form) ---
def register_user_web(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password']) # Hashes password
            user.save()
            login(request, user) # Auto-login after registration
            return redirect('plot-list') 
    else:
        form = UserRegistrationForm()
    return render(request, 'register_web.html', {'form': form})

def home_screen(request):
    return render(request, 'home.html')


@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({
            "message": "User created successfully",
            "user": serializer.data
        }, status=status.HTTP_201_CREATED)
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

# --- PLOT MANAGEMENT (For Farm Overview UI) ---
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def plot_manager(request):
    if request.method == 'GET':
        plots = FarmPlot.objects.filter(farmer=request.user)
        serializer = FarmPlotListSerializer(plots, many=True)
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

# --- SENSOR DATA INGESTION (For the ESP32) ---
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