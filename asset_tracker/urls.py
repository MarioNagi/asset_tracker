# asset_tracker/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from .health import live, ready

urlpatterns = [
    path('health/live/', live, name='health_live'),
    path('health/ready/', ready, name='health_ready'),
    path('admin/', admin.site.urls),
    path('', include('tracking.urls')),
    path('accounts/', include('allauth.urls')),  # For authentication
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
