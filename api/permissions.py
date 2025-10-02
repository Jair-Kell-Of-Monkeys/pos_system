# api/permissions.py
"""
Permisos personalizados por rol
"""
from rest_framework import permissions


class IsAdmin(permissions.BasePermission):
    """
    Permite acceso solo a usuarios con rol admin
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'role') and
            request.user.role and
            request.user.role.name == 'admin'
        )


class IsEmpleadoOrAdmin(permissions.BasePermission):
    """
    Permite acceso a empleados y admins
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'role') and
            request.user.role and
            request.user.role.name in ['admin', 'empleado']
        )


class ProductPermission(permissions.BasePermission):
    """
    - Admin: CRUD completo
    - Empleado: Solo lectura (GET)
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if not hasattr(request.user, 'role') or not request.user.role:
            return False
        
        # Admin puede todo
        if request.user.role.name == 'admin':
            return True
        
        # Empleado solo puede leer
        if request.user.role.name == 'empleado':
            return request.method in permissions.SAFE_METHODS
        
        return False


class SalePermission(permissions.BasePermission):
    """
    - Admin y Empleado: pueden crear y ver ventas
    - Solo Admin puede eliminar ventas
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if not hasattr(request.user, 'role') or not request.user.role:
            return False
        
        # Ambos roles pueden crear y leer
        if request.method in ['GET', 'POST']:
            return request.user.role.name in ['admin', 'empleado']
        
        # Solo admin puede eliminar
        if request.method == 'DELETE':
            return request.user.role.name == 'admin'
        
        return False


class UserManagementPermission(permissions.BasePermission):
    """
    Solo admin puede gestionar usuarios
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'role') and
            request.user.role and
            request.user.role.name == 'admin'
        )