# backend/urls.py
"""
URLs principales del proyecto
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    
    # Documentación (Borrar esos 2 cuando ya no estemos en desarollo)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

# Solo agregar docs si DEBUG=True
#if settings.DEBUG:
#    urlpatterns += [
#        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
#        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
#    ]