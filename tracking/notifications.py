from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.auth.models import User
from .models import Car
import logging

logger = logging.getLogger(__name__)


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
        html_content = render_to_string(template_name, context)
        plain_content = render_to_string(template_name.replace('.html', '.txt'), context)

        # Send email
        send_mail(
            subject=subject,
            message=plain_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_content,
            fail_silently=False,
        )

        logger.info(f"Service reminder email sent for car {car.rego} to {recipient_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send service reminder email for car {car.rego}: {str(e)}")
        return False


def check_and_send_service_reminders(warning_km=1000):
    """
    Check all cars and send service reminders for those that need them
    """
    cars_needing_service = []
    cars_approaching_service = []
    
    for car in Car.objects.filter(assigned_user__isnull=False):
        if car.is_service_due_by_km():
            cars_needing_service.append(car)
            send_service_reminder_email(car, warning_km=warning_km)
        elif car.is_service_approaching(warning_km):
            cars_approaching_service.append(car)
            send_service_reminder_email(car, warning_km=warning_km)
    
    logger.info(f"Service reminders checked: {len(cars_needing_service)} overdue, {len(cars_approaching_service)} approaching")
    
    return {
        'overdue': cars_needing_service,
        'approaching': cars_approaching_service,
        'total_sent': len(cars_needing_service) + len(cars_approaching_service)
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
        
        # Add managers/admins
        managers = User.objects.filter(
            profile__access_level__in=['Manager', 'Admin'],
            email__isnull=False
        )
        recipients.extend([user.email for user in managers])
        
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

        html_content = render_to_string('emails/odometer_update.html', context)
        plain_content = render_to_string('emails/odometer_update.txt', context)

        send_mail(
            subject=subject,
            message=plain_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            html_message=html_content,
            fail_silently=False,
        )

        logger.info(f"Odometer update notification sent for car {car.rego}")
        return True

    except Exception as e:
        logger.error(f"Failed to send odometer update notification for car {car.rego}: {str(e)}")
        return False