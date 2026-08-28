from django.conf import settings
from django.shortcuts import redirect

from allauth.mfa.utils import is_mfa_enabled

from .mixins import get_user_role


class SecurityHeadersMiddleware:
    """Add response policies not supplied by Django's SecurityMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault(
            'Content-Security-Policy', settings.CONTENT_SECURITY_POLICY
        )
        response.setdefault(
            'Permissions-Policy',
            'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
        )
        return response


class RequiredMFAMiddleware:
    """Require selected application roles to enroll in authenticator-app 2FA."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        required_roles = getattr(settings, 'ASSET_TRACKER_MFA_REQUIRED_ROLES', set())

        if (
            user
            and user.is_authenticated
            and user.is_active
            and get_user_role(user) in required_roles
            and not is_mfa_enabled(user)
            and not self._is_enrollment_path(request.path)
        ):
            return redirect('mfa_activate_totp')

        return self.get_response(request)

    @staticmethod
    def _is_enrollment_path(path):
        """Allow account/MFA pages and assets needed to complete enrollment."""
        allowed_prefixes = (
            '/accounts/',
            settings.STATIC_URL,
        )
        return any(path.startswith(prefix) for prefix in allowed_prefixes if prefix)
