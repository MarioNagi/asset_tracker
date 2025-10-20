from django.contrib.auth.mixins import AccessMixin
from django.shortcuts import redirect
from django.urls import reverse

class UserRequiredMixin(AccessMixin):
    """Allows only 'User' role"""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.profile.access_level.lower() != 'user':
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)


class ManagerRequiredMixin(AccessMixin):
    """Allows only 'Manager' role"""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.profile.access_level.lower() != 'manager':
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(AccessMixin):
    """Allows only 'Admin' role"""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.profile.access_level.lower() != 'admin':
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)


class AdminManagerRequiredMixin(AccessMixin):
    """Allows only 'Admin' and 'Manager' roles"""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.profile.access_level.lower() not in ['admin', 'manager']:
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)
