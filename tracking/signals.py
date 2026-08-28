# tracking/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Profile

@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, **kwargs):
    """Ensure every user has a profile, including legacy/imported users."""
    Profile.objects.get_or_create(user=instance)
