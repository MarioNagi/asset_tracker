# tracking/tasks.py

import logging

from celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Prefetch
from django.template.loader import render_to_string
from datetime import timedelta

from .models import (
    AlertContact, Tool, Car, TireRecord, OdometerReading,
    TransferFollowUpTask, VehicleRetirementTask, SpecialMaintenanceRequirement,
)
from .notification_service import send_tracked_notification
from .notifications import _fleet_recipients, _state_recipient

logger = logging.getLogger(__name__)


def _send_reminder(subject, message, recipient, html_message=None, context_label=''):
    """Send one reminder without letting a single failure abort the batch.

    Scheduled reminders iterate over the whole fleet. An unroutable address or a
    transient SMTP error must not prevent every later vehicle from being
    notified, so each send is isolated and failures are logged rather than
    raised.
    """
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as exc:
        logger.error(
            'Failed to send reminder "%s" to %s%s: %s',
            subject, recipient, context_label, exc,
        )
        return False


def _latest_reading(car):
    """Return the newest prefetched odometer reading without a new query."""
    readings = list(car.odometer_readings.all())
    return readings[0] if readings else None


# Prefetch newest-first so _latest_reading() can read index 0 in memory.
_LATEST_READINGS = Prefetch(
    'odometer_readings',
    queryset=OdometerReading.objects.order_by('-reading_date'),
)


@shared_task
def send_calibration_reminders():
    today = timezone.now().date()
    upcoming_tools = Tool.objects.filter(
        calibration_date__lte=today + timedelta(days=7),
        assigned_user__email__isnull=False,
    ).exclude(assigned_user__email='').select_related('assigned_user')

    sent = failed = 0
    for tool in upcoming_tools:
        subject = f"Calibration Reminder: {tool.tool_name}"
        message = render_to_string('emails/calibration_reminder.html', {'tool': tool})
        if _send_reminder(
            subject, message, tool.assigned_user.email,
            context_label=f' for tool {tool.internal_number}',
        ):
            sent += 1
        else:
            failed += 1

    logger.info('Calibration reminders: %s sent, %s failed.', sent, failed)
    return {'sent': sent, 'failed': failed}


@shared_task
def send_rego_reminders():
    today = timezone.now().date()
    upcoming_cars = Car.objects.active().filter(
        rego_expiry_date__lte=today + timedelta(days=30),
        assigned_user__email__isnull=False,
    ).exclude(assigned_user__email='').select_related('assigned_user')

    sent = failed = 0
    for car in upcoming_cars:
        subject = f"Registration Expiry Reminder: {car.rego}"
        message = render_to_string('emails/rego_reminder.html', {'car': car})
        if _send_reminder(
            subject, message, car.assigned_user.email,
            context_label=f' for vehicle {car.rego}',
        ):
            sent += 1
        else:
            failed += 1

    logger.info('Registration reminders: %s sent, %s failed.', sent, failed)
    return {'sent': sent, 'failed': failed}


@shared_task
def check_vehicle_registrations():
    """Check for vehicles with registration expiring in 30 days"""
    threshold_date = timezone.now().date() + timedelta(days=30)
    expiring_vehicles = (
        Car.objects.active()
        .filter(rego_expiry_date=threshold_date)
        .select_related('assigned_user')
    )

    sent = failed = 0
    for vehicle in expiring_vehicles:
        if not (vehicle.assigned_user and vehicle.assigned_user.email):
            continue
        context = {
            'vehicle': vehicle,
            'expiry_date': vehicle.rego_expiry_date,
            'days_remaining': 30,
        }
        html_message = render_to_string('emails/rego_reminder.html', context)
        if _send_reminder(
            subject=f'Vehicle Registration Expiring Soon - {vehicle.rego}',
            message=(
                f'The registration for vehicle {vehicle.rego} will expire on '
                f'{vehicle.rego_expiry_date}.'
            ),
            recipient=vehicle.assigned_user.email,
            html_message=html_message,
            context_label=f' for vehicle {vehicle.rego}',
        ):
            sent += 1
        else:
            failed += 1

    logger.info('Registration expiry checks: %s sent, %s failed.', sent, failed)
    return {'sent': sent, 'failed': failed}


@shared_task
def check_maintenance_schedule():
    """Check for vehicles due for maintenance by date or by distance driven."""
    date_threshold = timezone.now().date()

    # Resolve both due-by-date and due-by-odometer in one pass over the fleet
    # instead of OR-ing a fresh queryset per vehicle.
    fleet = (
        Car.objects.active()
        .select_related('assigned_user')
        .prefetch_related(_LATEST_READINGS)
    )

    due_vehicles = []
    for car in fleet:
        due_by_date = (
            car.next_service_date is not None
            and car.next_service_date <= date_threshold
        )
        due_by_km = False
        latest_reading = _latest_reading(car)
        if latest_reading and car.last_service_km:
            km_since_service = latest_reading.reading_value - car.last_service_km
            due_by_km = km_since_service >= car.service_interval_km
        if due_by_date or due_by_km:
            due_vehicles.append((car, latest_reading))

    sent = failed = 0
    for vehicle, latest_reading in due_vehicles:
        if not (vehicle.assigned_user and vehicle.assigned_user.email):
            continue
        context = {
            'vehicle': vehicle,
            'service_date': vehicle.next_service_date,
            'last_service_km': vehicle.last_service_km,
            'current_km': latest_reading.reading_value if latest_reading else None,
        }
        html_message = render_to_string('emails/maintenance_reminder.html', context)
        if _send_reminder(
            subject=f'Vehicle Service Due - {vehicle.rego}',
            message=f'Vehicle {vehicle.rego} is due for service.',
            recipient=vehicle.assigned_user.email,
            html_message=html_message,
            context_label=f' for vehicle {vehicle.rego}',
        ):
            sent += 1
        else:
            failed += 1

    logger.info(
        'Maintenance schedule checks: %s due, %s sent, %s failed.',
        len(due_vehicles), sent, failed,
    )
    return {'due': len(due_vehicles), 'sent': sent, 'failed': failed}


@shared_task
def check_tire_schedule():
    """Check for vehicles due for tire service"""
    tire_records = (
        TireRecord.objects
        .filter(car__status=Car.STATUS_IN_SERVICE)
        .select_related('car', 'car__assigned_user')
        .prefetch_related(Prefetch('car__odometer_readings',
                                   queryset=OdometerReading.objects.order_by('-reading_date')))
    )

    sent = failed = 0
    for record in tire_records:
        latest_odometer = _latest_reading(record.car)
        if not (latest_odometer and latest_odometer.reading_value >= record.next_change_km):
            continue
        if not (record.car.assigned_user and record.car.assigned_user.email):
            continue
        context = {
            'vehicle': record.car,
            'last_tire_service': record.change_date,
            'current_km': latest_odometer.reading_value,
            'recommended_change_km': record.next_change_km,
        }
        html_message = render_to_string('emails/tire_service_reminder.html', context)
        if _send_reminder(
            subject=f'Tire Service Due - {record.car.rego}',
            message=f'Vehicle {record.car.rego} is due for tire service.',
            recipient=record.car.assigned_user.email,
            html_message=html_message,
            context_label=f' for vehicle {record.car.rego}',
        ):
            sent += 1
        else:
            failed += 1

    logger.info('Tire schedule checks: %s sent, %s failed.', sent, failed)
    return {'sent': sent, 'failed': failed}


@shared_task
def send_retirement_task_reminders():
    """Send one auditable daily reminder per vehicle with unfinished tasks."""
    today = timezone.localdate()
    tasks_by_car = {}
    queryset = VehicleRetirementTask.objects.filter(
        completed=False,
        car__status__in=[Car.STATUS_SOLD, Car.STATUS_WRITTEN_OFF],
    ).select_related('car')
    for task in queryset:
        tasks_by_car.setdefault(task.car_id, {'car': task.car, 'tasks': []})[
            'tasks'
        ].append(task)

    sent = failed = 0
    for item in tasks_by_car.values():
        car = item['car']
        recipients = _fleet_recipients(AlertContact.CATEGORY_RETIREMENT)
        state_email = _state_recipient(
            car.state, AlertContact.CATEGORY_RETIREMENT
        )
        if state_email:
            recipients.add(state_email)
        message = '\n'.join([
            f'Vehicle {car.rego} still has retirement actions outstanding:',
            *[f'- {task.get_task_type_display()}' for task in item['tasks']],
        ])
        delivery, delivered = send_tracked_notification(
            event_type=AlertContact.CATEGORY_RETIREMENT,
            related_object=car.rego,
            recipients=recipients,
            subject=f'Retirement checklist outstanding: {car.rego}',
            message=message,
            deduplication_key=f'retirement-reminder:{car.pk}:{today}',
        )
        if delivered:
            sent += 1
        elif delivery is not None and delivery.status == delivery.STATUS_FAILED:
            failed += 1
    return {'vehicles': len(tasks_by_car), 'sent': sent, 'failed': failed}


@shared_task
def send_transfer_follow_up_reminders():
    """Remind responsible mailboxes about incomplete state-change tasks."""
    today = timezone.localdate()
    tasks = TransferFollowUpTask.objects.filter(completed=False).select_related(
        'batch', 'car', 'assigned_to'
    )
    sent = failed = total = 0
    for task in tasks:
        total += 1
        recipients = _fleet_recipients(AlertContact.CATEGORY_CONTROLLED_TRANSFER)
        state_email = _state_recipient(
            task.state, AlertContact.CATEGORY_CONTROLLED_TRANSFER
        )
        if state_email:
            recipients.add(state_email)
        if task.assigned_to and task.assigned_to.email:
            recipients.add(task.assigned_to.email)
        delivery, delivered = send_tracked_notification(
            event_type=AlertContact.CATEGORY_CONTROLLED_TRANSFER,
            related_object=str(task.batch.reference),
            recipients=recipients,
            subject=f'Transfer follow-up outstanding: {task.car.rego}',
            message=task.description,
            deduplication_key=f'transfer-follow-up:{task.pk}:{today}',
        )
        if delivered:
            sent += 1
        elif delivery is not None and delivery.status == delivery.STATUS_FAILED:
            failed += 1
    return {'tasks': total, 'sent': sent, 'failed': failed}


@shared_task
def send_special_maintenance_reminders():
    """Send tracked daily alerts for upcoming or overdue special work."""
    today = timezone.localdate()
    requirements = SpecialMaintenanceRequirement.objects.filter(
        active=True, car__status=Car.STATUS_IN_SERVICE
    ).select_related('car')
    due = sent = failed = 0
    for requirement in requirements:
        status = requirement.status
        if status not in {'upcoming', 'overdue'}:
            continue
        due += 1
        recipients = _fleet_recipients(AlertContact.CATEGORY_SPECIAL_MAINTENANCE)
        state_email = _state_recipient(
            requirement.car.state, AlertContact.CATEGORY_SPECIAL_MAINTENANCE
        )
        if state_email:
            recipients.add(state_email)
        delivery, delivered = send_tracked_notification(
            event_type=AlertContact.CATEGORY_SPECIAL_MAINTENANCE,
            related_object=f'{requirement.car.rego}: {requirement.title}',
            recipients=recipients,
            subject=f'{status.title()} special maintenance: {requirement.car.rego}',
            message=(
                f'{requirement.title} is {status} for {requirement.car.rego}. '
                f'Due date: {requirement.due_date or "not set"}; '
                f'due odometer: {requirement.due_odometer or "not set"}.'
            ),
            deduplication_key=f'special-maintenance:{requirement.pk}:{status}:{today}',
        )
        if delivered:
            sent += 1
        elif delivery is not None and delivery.status == delivery.STATUS_FAILED:
            failed += 1
    return {'due': due, 'sent': sent, 'failed': failed}


@shared_task
def send_weekly_odometer_reminders():
    """Remind custodians seven days after the last accepted reading."""
    today = timezone.localdate()
    fleet = Car.objects.active().filter(monthly_odometer_check=True).select_related(
        'assigned_user'
    ).prefetch_related(_LATEST_READINGS)
    overdue = sent = failed = 0
    for car in fleet:
        due_date = car.odometer_due_date()
        if due_date >= today or not car.assigned_user:
            continue
        overdue += 1
        recipients = set()
        if car.assigned_user.email:
            recipients.add(car.assigned_user.email)
        if (today - due_date).days >= 7:
            recipients.update(_fleet_recipients(AlertContact.CATEGORY_ODOMETER))
        delivery, delivered = send_tracked_notification(
            event_type=AlertContact.CATEGORY_ODOMETER,
            related_object=car.rego,
            recipients=recipients,
            subject=f'Weekly odometer reading overdue: {car.rego}',
            message=(
                f'The weekly odometer reading for {car.rego} was due on {due_date}. '
                'Scan the QR in the vehicle to submit the correct reading.'
            ),
            deduplication_key=f'weekly-odometer:{car.pk}:{today}',
        )
        if delivered:
            sent += 1
        elif delivery is not None and delivery.status == delivery.STATUS_FAILED:
            failed += 1
    return {'overdue': overdue, 'sent': sent, 'failed': failed}
