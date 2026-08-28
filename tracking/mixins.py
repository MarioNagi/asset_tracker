from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.core.exceptions import PermissionDenied


def get_user_role(user):
    """Return a normalized application role without assuming a profile exists."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'admin'
    profile = getattr(user, 'profile', None)
    return profile.access_level.lower() if profile and profile.access_level else None


def get_user_state(user):
    """Map profile subdivisions to the state codes used by cars and tools."""
    profile = getattr(user, 'profile', None)
    state = profile.state if profile else None
    if state and state.startswith('NSW-'):
        return 'NSW'
    return state


class RoleRequiredMixin(LoginRequiredMixin, AccessMixin):
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if get_user_role(request.user) not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class UserRequiredMixin(RoleRequiredMixin):
    """Allow only users with the User role."""
    allowed_roles = ('user',)


class ManagerRequiredMixin(RoleRequiredMixin):
    """Allow only users with the Manager role."""
    allowed_roles = ('manager',)


class AdminRequiredMixin(RoleRequiredMixin):
    """Allow administrators and Django superusers."""
    allowed_roles = ('admin',)


class AdminManagerRequiredMixin(RoleRequiredMixin):
    """Allow administrators, Django superusers, and managers."""
    allowed_roles = ('admin', 'manager')
