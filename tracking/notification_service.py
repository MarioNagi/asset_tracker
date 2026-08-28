import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import AlertContact, NotificationDelivery


logger = logging.getLogger(__name__)


def alert_recipient_emails(responsibility, category, state=None):
    """Resolve enabled configured mailboxes for one responsibility/category."""
    contacts = AlertContact.objects.filter(
        responsibility=responsibility,
        enabled=True,
    )
    if responsibility == AlertContact.ROLE_STATE_MANAGER:
        contacts = contacts.filter(state=state)
    else:
        contacts = contacts.filter(state__isnull=True)
    return sorted({
        contact.email.strip().lower()
        for contact in contacts
        if category in contact.categories and contact.email.strip()
    })


def primary_state_manager_email(state, category):
    contact = AlertContact.objects.filter(
        responsibility=AlertContact.ROLE_STATE_MANAGER,
        state=state,
        is_primary=True,
        enabled=True,
    ).first()
    if contact and category in contact.categories:
        return contact.email.strip().lower()
    return None


def _attempt_delivery(delivery):
    delivery.attempt_count += 1
    delivery.last_attempt_at = timezone.now()
    delivery.status = NotificationDelivery.STATUS_PENDING
    delivery.failure_reason = ''
    delivery.save(update_fields=[
        'attempt_count', 'last_attempt_at', 'status', 'failure_reason', 'updated_at',
    ])
    try:
        send_mail(
            subject=delivery.subject,
            message=delivery.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=delivery.recipients,
            fail_silently=False,
        )
    except Exception as exc:
        delivery.status = NotificationDelivery.STATUS_FAILED
        delivery.failure_reason = str(exc)[:2000]
        delivery.save(update_fields=['status', 'failure_reason', 'updated_at'])
        logger.error('Notification delivery %s failed: %s', delivery.pk, exc)
        return False

    delivery.status = NotificationDelivery.STATUS_SENT
    delivery.sent_at = timezone.now()
    delivery.save(update_fields=['status', 'sent_at', 'updated_at'])
    return True


def send_tracked_notification(
    *, event_type, related_object, recipients, subject, message, deduplication_key
):
    """Create one auditable delivery and send it once for a deduplication key."""
    normalized_recipients = sorted({
        email.strip().lower() for email in recipients if email and email.strip()
    })
    if not normalized_recipients:
        return None, False
    delivery, created = NotificationDelivery.objects.get_or_create(
        deduplication_key=deduplication_key,
        defaults={
            'event_type': event_type,
            'related_object': related_object,
            'recipients': normalized_recipients,
            'subject': subject,
            'message': message,
        },
    )
    if not created:
        return delivery, False
    return delivery, _attempt_delivery(delivery)


def retry_failed_notification(delivery):
    if delivery.status != NotificationDelivery.STATUS_FAILED:
        return False
    return _attempt_delivery(delivery)
