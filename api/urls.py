# api/urls.py
"""
URLs de la API
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from .views import (
    RoleViewSet, UserViewSet, ProductViewSet,
    SaleViewSet, InventoryMovementViewSet, ReportViewSet
)

router = DefaultRouter()
router.register(r'roles', RoleViewSet, basename='role')
router.register(r'users', UserViewSet, basename='user')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'sales', SaleViewSet, basename='sale')
router.register(r'inventory-movements', InventoryMovementViewSet, basename='inventory-movement')
router.register(r'reports', ReportViewSet, basename='report')

urlpatterns = [
    # Autenticación JWT
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # Endpoints de la API
    path('', include(router.urls)),
]