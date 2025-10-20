from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    RoleViewSet, UserViewSet, ProductViewSet,
    SaleViewSet, InventoryMovementViewSet, ReportViewSet,
    DashboardViewSet, SystemViewSet,
    register_user,
    CustomTokenObtainPairView
)

router = DefaultRouter()
router.register(r'roles', RoleViewSet, basename='role')
router.register(r'users', UserViewSet, basename='user')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'sales', SaleViewSet, basename='sale')
router.register(r'inventory-movements', InventoryMovementViewSet, basename='inventory-movement')
router.register(r'reports', ReportViewSet, basename='report')
router.register(r'dashboard', DashboardViewSet, basename='dashboard')
router.register(r'system', SystemViewSet, basename='system')

urlpatterns = [
    # Autenticación JWT
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/register/', register_user, name='register'),
    
    # Health check (sin autenticación)
    path('health/', SystemViewSet.as_view({'get': 'health_check'}), name='health'),
    
    # Backup
    path('backup/', SystemViewSet.as_view({'post': 'backup'}), name='backup'),
    
    # Endpoints de la API
    path('', include(router.urls)),
]