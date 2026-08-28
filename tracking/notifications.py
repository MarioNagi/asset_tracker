from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from .models import AlertContact, Car, TransferBatch
from .mixins import get_user_state
from .notification_service import (
    alert_recipient_emails, primary_state_manager_email,
    send_tracked_notification,
)
import logging

logger = logging.getLogger(__name__)


def _fleet_recipients(category):
    recipients = set(alert_recipient_emails(
        AlertContact.ROLE_FLEET_MANAGER, category
    ))
    fallback = getattr(settings, 'FLEET_MANAGER_EMAIL', '').strip()
    if fallback:
        recipients.add(fallback)
    return recipients


def _state_recipient(state, category):
    if not state:
        return None
    configured = primary_state_manager_email(state, category)
    if configured:
        return configured
    manager = User.objects.filter(
        profile__access_level='Manager', profile__state__startswith=state,
        is_active=True,
    ).exclude(email='').order_by('pk').first()
    return manager.email if manager else None


def send_service_reminder_email(car, recipient_email=None, warning_km=1000):
    """
    Send email notification when car service is approaching or due
    """
    try:
        # Determine recipient email
        if not recipient_email:
            if car.assigned_user and car.assigned_user.email:
                recipient_email = car.assigned_user.email
            else:
                # Fall back to admin emails
                admin_users = User.objects.filter(is_superuser=True, email__isnull=False)
                if admin_users.exists():
                    recipient_email = admin_users.first().email
                else:
                    logger.warning(f"No email recipient found for car {car.rego}")
                    return False

        # Determine if service is due or approaching
        km_until_service = car.km_until_service()
        is_overdue = car.is_service_due_by_km()
        is_approaching = car.is_service_approaching(warning_km)
        
        if is_overdue:
            subject = f"🚨 URGENT: Service Overdue for {car.make} {car.model} ({car.rego})"
            template_name = 'emails/service_overdue.html'
        elif is_approaching:
            subject = f"⚠️ Service Due Soon for {car.make} {car.model} ({car.rego})"
            template_name = 'emails/service_reminder.html'
        else:
            return False  # No notification needed

        # Prepare context for email template
        context = {
            'car': car,
            'km_until_service': km_until_service,
            'is_overdue': is_overdue,
            'is_approaching': is_approaching,
            'current_odometer': car.current_odometer,
            'service_odometer': car.service_odometer,
            'warning_km': warning_km,
            'user_name': car.assigned_user.get_full_name() if car.assigned_user else 'Team',
        }

        # Render email content
        plain_content = render_to_string(template_name.replace('.html', '.txt'), context)

        recipients = _fleet_recipients(AlertContact.CATEGORY_VEHICLE_SERVICE)
        recipients.add(recipient_email)
        _, sent = send_tracked_notification(
            event_type=AlertContact.CATEGORY_VEHICLE_SERVICE,
            related_object=car.rego,
            recipients=recipients,
            subject=subject,
            message=plain_content,
            deduplication_key=(
                f'vehicle-service:{car.pk}:{timezone.localdate().isoformat()}:'
                f'{"overdue" if is_overdue else "approaching"}'
            ),
        )
        if sent:
            logger.info('Tracked service reminder sent for car %s.', car.rego)
        return sent

    except Exception as e:
        logger.error(f"Failed to send service reminder email for car {car.rego}: {str(e)}")
        return False


def check_and_send_service_reminders(warning_km=1000):
    """
    Check all cars and send service reminders for those that need them
    """
    cars_needing_service = []
    cars_approaching_service = []
    total_sent = 0
    
    for car in Car.objects.active().filter(
        assigned_user__isnull=False
    ).select_related('assigned_user'):
        if car.is_service_due_by_km():
            cars_needing_service.append(car)
            total_sent += int(send_service_reminder_email(car, warning_km=warning_km))
        elif car.is_service_approaching(warning_km):
            cars_approaching_service.append(car)
            total_sent += int(send_service_reminder_email(car, warning_km=warning_km))
    
    logger.info(f"Service reminders checked: {len(cars_needing_service)} overdue, {len(cars_approaching_service)} approaching")
    
    return {
        'overdue': cars_needing_service,
        'approaching': cars_approaching_service,
        'total_sent': total_sent,
    }


def send_odometer_update_notification(car, old_odometer, new_odometer, updated_by):
    """
    Send notification when odometer is updated
    """
    try:
        # Send to assigned user and managers
        recipients = []
        
        if car.assigned_user and car.assigned_user.email:
            recipients.append(car.assigned_user.email)
        
        recipients.extend(_fleet_recipients(AlertContact.CATEGORY_ODOMETER))
        state_recipient = _state_recipient(car.state, AlertContact.CATEGORY_ODOMETER)
        if state_recipient:
            recipients.append(state_recipient)
        
        if not recipients:
            return False

        subject = f"Odometer Updated for {car.make} {car.model} ({car.rego})"
        
        context = {
            'car': car,
            'old_odometer': old_odometer,
            'new_odometer': new_odometer,
            'updated_by': updated_by,
            'km_until_service': car.km_until_service(),
            'service_due_soon': car.is_service_approaching(),
            'service_overdue': car.is_service_due_by_km(),
        }

        plain_content = render_to_string('emails/odometer_update.txt', context)
        _, sent = send_tracked_notification(
            event_type=AlertContact.CATEGORY_ODOMETER,
            related_object=car.rego,
            recipients=recipients,
            subject=subject,
            message=plain_content,
            deduplication_key=(
                f'odometer:{car.pk}:{new_odometer}:{updated_by.pk}:'
                f'{timezone.localdate().isoformat()}'
            ),
        )
        return sent

    except Exception as e:
        logger.error(f"Failed to send odometer update notification for car {car.rego}: {str(e)}")
        return False


def send_vehicle_retirement_notification(car):
    """Notify fleet and matching state managers after a vehicle is retired."""
    try:
        category = (
            AlertContact.CATEGORY_WRITTEN_OFF
            if car.status == Car.STATUS_WRITTEN_OFF
            else AlertContact.CATEGORY_RETIREMENT
        )
        recipients = _fleet_recipients(category)
        state_recipient = _state_recipient(car.state, category)
        if state_recipient:
            recipients.add(state_recipient)
        if car.status == Car.STATUS_WRITTEN_OFF:
            recipients.update(alert_recipient_emails(
                AlertContact.ROLE_ADMIN_ALERTS, category
            ))

        if not recipients:
            logger.warning('No retirement email recipient found for car %s', car.rego)
            return False

        message = render_to_string('emails/vehicle_retired.txt', {
            'car': car,
            'task_names': [label for _, label in car.retirement_tasks.model.TASK_CHOICES],
        })
        _, sent = send_tracked_notification(
            event_type=category,
            related_object=car.rego,
            recipients=recipients,
            subject=f'Vehicle retired: {car.rego}',
            message=message,
            deduplication_key=(
                f'retirement:{car.pk}:{car.status}:{car.retired_at}'
            ),
        )
        return sent
    except Exception as exc:
        logger.error('Failed to send retirement notification for %s: %s', car.rego, exc)
        return False


def send_transfer_notification(batch_id):
    """Notify fleet and state managers of a cross-state vehicle transfer."""
    try:
        batch = TransferBatch.objects.prefetch_related(
            'entries__tool', 'entries__car', 'follow_up_tasks'
        ).select_related(
            'from_user__profile', 'to_user__profile',
            'from_location', 'to_location', 'created_by',
        ).get(pk=batch_id)
        entries = list(batch.entries.all())
        follow_up = batch.follow_up_tasks.first()
        destination_state = follow_up.state if follow_up else None
        controlled_entries = [
            entry for entry in entries
            if entry.tool_id and entry.tool and entry.tool.is_controlled
        ]
        if not controlled_entries and not follow_up:
            return True  # Ordinary same-state transfers are ledger-only.

        category = AlertContact.CATEGORY_CONTROLLED_TRANSFER
        recipients = _fleet_recipients(category)
        for affected_user in (batch.from_user, batch.to_user):
            if affected_user and affected_user.email:
                recipients.add(affected_user.email)

        origin_state = (
            get_user_state(batch.from_user)
            if batch.from_user else batch.from_location.state
        )
        destination_state = destination_state or (
            get_user_state(batch.to_user)
            if batch.to_user else batch.to_location.state
        )
        for state in {origin_state, destination_state}:
            state_email = _state_recipient(state, category)
            if state_email:
                recipients.add(state_email)
        recipients.update(alert_recipient_emails(
            AlertContact.ROLE_ADMIN_ALERTS, category
        ))
        if not recipients:
            return False
        _, sent = send_tracked_notification(
            event_type=category,
            related_object=str(batch.reference),
            recipients=recipients,
            subject=f'Asset transfer {str(batch.reference)[:8]}',
            message=render_to_string('emails/transfer_notification.txt', {
                'batch': batch, 'entries': entries,
                'destination_state': destination_state,
                'has_registration_task': bool(follow_up),
            }),
            deduplication_key=f'transfer:{batch.pk}',
        )
        return sent
    except Exception as exc:
        logger.error('Failed to send transfer notification for batch %s: %s', batch_id, exc)
        return False
