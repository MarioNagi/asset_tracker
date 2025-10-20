# tracking/tasks.py

from celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
from .models import Tool, Car, TireRecord
from django.template.loader import render_to_string
from django.conf import settings
from datetime import datetime, timedelta

@shared_task
def send_calibration_reminders():
    today = timezone.now().date()
    upcoming_tools = Tool.objects.filter(calibration_date__lte=today + timezone.timedelta(days=7))
    for tool in upcoming_tools:
        subject = f"Calibration Reminder: {tool.name}"
        message = render_to_string('emails/calibration_reminder.html', {'tool': tool})
        recipient_list = [tool.assigned_user.email]
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)

@shared_task
def send_rego_reminders():
    today = timezone.now().date()
    upcoming_cars = Car.objects.filter(rego_expiry_date__lte=today + timezone.timedelta(days=30))
    for car in upcoming_cars:
        subject = f"Registration Expiry Reminder: {car.rego}"
        message = render_to_string('emails/rego_reminder.html', {'car': car})
        recipient_list = [car.assigned_user.email]
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)

@shared_task
def check_vehicle_registrations():
    """Check for vehicles with registration expiring in 30 days"""
    threshold_date = timezone.now().date() + timedelta(days=30)
    expiring_vehicles = Car.objects.filter(rego_expiry_date=threshold_date)
    
    for vehicle in expiring_vehicles:
        if vehicle.assigned_user and vehicle.assigned_user.email:
            context = {
                'vehicle': vehicle,
                'expiry_date': vehicle.rego_expiry_date,
                'days_remaining': 30
            }
            html_message = render_to_string('emails/rego_reminder.html', context)
            
            send_mail(
                subject=f'Vehicle Registration Expiring Soon - {vehicle.rego}',
                message=f'The registration for vehicle {vehicle.rego} will expire on {vehicle.rego_expiry_date}.',
                html_message=html_message,
                from_email='noreply@koinonia.com',
                recipient_list=[vehicle.assigned_user.email]
            )

@shared_task
def check_maintenance_schedule():
    """Check for vehicles due for maintenance"""
    # Check by date
    date_threshold = timezone.now().date()
    vehicles_due_by_date = Car.objects.filter(next_service_date__lte=date_threshold)
    
    # Check by odometer reading
    for car in Car.objects.all():
        latest_reading = car.odometer_readings.order_by('-reading_date').first()
        if latest_reading and car.last_service_km:
            km_since_service = latest_reading.reading_value - car.last_service_km
            if km_since_service >= car.service_interval_km:
                if car not in vehicles_due_by_date:
                    vehicles_due_by_date |= Car.objects.filter(id=car.id)

    for vehicle in vehicles_due_by_date:
        if vehicle.assigned_user and vehicle.assigned_user.email:
            context = {
                'vehicle': vehicle,
                'service_date': vehicle.next_service_date,
                'last_service_km': vehicle.last_service_km,
                'current_km': vehicle.odometer_readings.order_by('-reading_date').first().reading_value if vehicle.odometer_readings.exists() else None
            }
            html_message = render_to_string('emails/maintenance_reminder.html', context)
            
            send_mail(
                subject=f'Vehicle Service Due - {vehicle.rego}',
                message=f'Vehicle {vehicle.rego} is due for service.',
                html_message=html_message,
                from_email='noreply@koinonia.com',
                recipient_list=[vehicle.assigned_user.email]
            )

@shared_task
def check_tire_schedule():
    """Check for vehicles due for tire service"""
    today = timezone.now().date()
    tire_records = TireRecord.objects.all()
    
    for record in tire_records:
        latest_odometer = record.car.odometer_readings.order_by('-reading_date').first()
        if latest_odometer and latest_odometer.reading_value >= record.next_change_km:
            if record.car.assigned_user and record.car.assigned_user.email:
                context = {
                    'vehicle': record.car,
                    'last_tire_service': record.change_date,
                    'current_km': latest_odometer.reading_value,
                    'recommended_change_km': record.next_change_km
                }
                html_message = render_to_string('emails/tire_service_reminder.html', context)
                
                send_mail(
                    subject=f'Tire Service Due - {record.car.rego}',
                    message=f'Vehicle {record.car.rego} is due for tire service.',
                    html_message=html_message,
                    from_email='noreply@koinonia.com',
                    recipient_list=[record.car.assigned_user.email]
                )
