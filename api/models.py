# api/models.py
# pylint: disable=no-member
"""
Modelos adaptados al esquema de base de datos existente
"""
from django.db import models
from decimal import Decimal
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin, Group, Permission
from django.core.validators import MinValueValidator
from typing import ClassVar


class Role(models.Model):
    """
    Roles del sistema: admin, empleado
    Tabla: roles
    """
    objects: ClassVar[models.Manager['Role']]
    
    name = models.CharField(max_length=50, unique=True, verbose_name='Nombre')
    description = models.TextField(blank=True, null=True, verbose_name='Descripción')
    
    class Meta:
        db_table = 'roles'
        managed = False
        verbose_name = 'Rol'
        verbose_name_plural = 'Roles'
    
    def __str__(self) -> str:
        return str(self.name)


class UserManager(BaseUserManager):
    """
    Manager personalizado para el modelo User
    """
    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError('El usuario debe tener un username')
        if not email:
            raise ValueError('El usuario debe tener un email')
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        # Asignar rol admin por defecto
        if 'role' not in extra_fields:
            try:
                admin_role = Role.objects.get(name='admin')
                extra_fields['role'] = admin_role
            except Role.DoesNotExist:
                raise ValueError('Debe existir el rol "admin" antes de crear un superusuario')
        
        return self.create_user(username, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Usuario adaptado al esquema existente
    Tabla: users
    """
    objects: ClassVar[UserManager]
    
    username = models.CharField(max_length=50, unique=True, verbose_name='Usuario')
    email = models.EmailField(max_length=100, unique=True, verbose_name='Email')
    role = models.ForeignKey(
        Role,
        on_delete=models.RESTRICT,
        db_column='role_id',
        related_name='users',
        verbose_name='Rol'
    )

    # Relación jerárquica
    manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='manager_id',
        related_name='employees',
        verbose_name='Jefe/Admin'
    )
    
    # Campos adicionales de Django (agregados con update_db.sql)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)
    
    # Deshabilitar grupos y permisos (usamos roles personalizados)
    groups = None
    user_permissions = None
    
    objects = UserManager()
    
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']
    
    class Meta:
        db_table = 'users'
        managed = False
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'
    
    def __str__(self) -> str:
        role_name = self.role.name if self.role else 'Sin rol'
        return f"{self.username} ({role_name})"
    
    @property
    def is_admin(self) -> bool:
        return self.role is not None and self.role.name == 'admin'
    
    @property
    def is_empleado(self) -> bool:
        return self.role is not None and self.role.name == 'empleado'
    
    # Sobrescribir métodos de PermissionsMixin para evitar errores
    def has_perm(self, perm, obj=None):
        """Permisos basados en rol, no en grupos"""
        return self.is_active and self.is_superuser
    
    def has_perms(self, perm_list, obj=None):
        """Permisos basados en rol, no en grupos"""
        return all(self.has_perm(perm, obj) for perm in perm_list)
    
    def has_module_perms(self, app_label):
        """Permisos basados en rol, no en grupos"""
        return self.is_active and (self.is_superuser or self.is_staff)


class Product(models.Model):
    """
    Productos del inventario
    Tabla: products
    """
    objects: ClassVar[models.Manager['Product']]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_column='user_id',
        related_name='products',
        verbose_name='Usuario Propietario'
    )
    name = models.CharField(max_length=100, verbose_name='Nombre')
    category = models.CharField(max_length=50, blank=True, null=True, verbose_name='Categoría')
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Precio'
    )
    stock = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Stock'
    )
    code = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        verbose_name='Código'
    )
    
    # Campos adicionales para rutas de archivos (agregados con update_db.sql)
    qr_code_path = models.CharField(max_length=255, blank=True, null=True)
    barcode_path = models.CharField(max_length=255, blank=True, null=True)
    
    class Meta:
        db_table = 'products'
        managed = False
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
    
    def __str__(self) -> str:
        code_display = self.code if self.code else 'Sin código'
        return f"{self.name} ({code_display})"


class Sale(models.Model):
    """
    Ventas realizadas
    Tabla: sales
    """
    objects: ClassVar[models.Manager['Sale']]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_column='user_id',
        related_name='sales',
        verbose_name='Usuario'
    )
    date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Precio Total'
    )
    
    # Nuevos campos para cancelación
    is_cancelled = models.BooleanField(default=False, verbose_name='Cancelada')
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de Cancelación')
    cancelled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='cancelled_by_id',
        related_name='cancelled_sales',
        verbose_name='Cancelada por'
    )
    
    class Meta:
        db_table = 'sales'
        managed = False
        verbose_name = 'Venta'
        verbose_name_plural = 'Ventas'
        ordering = ['-date']
    
    def __str__(self) -> str:
        sale_id = self.pk if self.pk else 'Nueva'
        status = ' (CANCELADA)' if self.is_cancelled else ''
        return f"Venta #{sale_id} - ${self.total_price}{status}"

class SaleItem(models.Model):
    """
    Items de una venta
    Tabla: sale_items
    """
    objects: ClassVar[models.Manager['SaleItem']]
    
    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        db_column='sale_id',
        related_name='items',
        verbose_name='Venta'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        db_column='product_id',
        related_name='sale_items',
        verbose_name='Producto'
    )
    quantity = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name='Cantidad'
    )
    price_unit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Precio Unitario'
    )
    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Subtotal'
    )
    
    class Meta:
        db_table = 'sale_items'
        managed = False
        verbose_name = 'Item de Venta'
        verbose_name_plural = 'Items de Venta'
    
    def __str__(self) -> str:
        return f"{self.product.name} x{self.quantity}"


class InventoryMovement(models.Model):
    """
    Movimientos de inventario
    Tabla: inventory_movements
    """
    objects: ClassVar[models.Manager['InventoryMovement']]
    
    MOVEMENT_TYPES = [
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
    ]
    
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        db_column='product_id',
        related_name='movements',
        verbose_name='Producto'
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MOVEMENT_TYPES,
        verbose_name='Tipo de Movimiento'
    )
    quantity = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name='Cantidad'
    )
    date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    note = models.TextField(blank=True, null=True, verbose_name='Nota')
    
    class Meta:
        db_table = 'inventory_movements'
        managed = False
        verbose_name = 'Movimiento de Inventario'
        verbose_name_plural = 'Movimientos de Inventario'
        ordering = ['-date']
    
    def __str__(self) -> str:
        return f"{self.product.name} - {self.movement_type} ({self.quantity})"


class Report(models.Model):
    """
    Reportes generados
    Tabla: reports
    """
    objects: ClassVar[models.Manager['Report']]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_column='user_id',
        related_name='reports',
        verbose_name='Usuario'
    )
    type = models.CharField(max_length=50, verbose_name='Tipo')
    generated_at = models.DateTimeField(auto_now_add=True, verbose_name='Generado en')
    data = models.JSONField(verbose_name='Datos')
    
    class Meta:
        db_table = 'reports'
        managed = False
        verbose_name = 'Reporte'
        verbose_name_plural = 'Reportes'
        ordering = ['-generated_at']
    
    def __str__(self) -> str:
        # Convertir DateTimeField a datetime antes de usar strftime
        fecha_str = self.generated_at.strftime('%Y-%m-%d') if self.generated_at else 'Sin fecha'
        return f"{self.type} - {fecha_str}"
    
class ActivityLog(models.Model):
    """
    Registro de actividad de usuarios
    Tabla: activity_logs
    """
    objects: ClassVar[models.Manager['ActivityLog']]
    
    ACTION_CHOICES = [
        ('create', 'Crear'),
        ('update', 'Actualizar'),
        ('delete', 'Eliminar'),
        ('sale', 'Venta'),
        ('cancel', 'Cancelar'),
        ('adjust_stock', 'Ajustar Stock'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_column='user_id',
        related_name='activity_logs',
        verbose_name='Usuario'
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, verbose_name='Acción')
    entity_type = models.CharField(max_length=50, verbose_name='Tipo de Entidad')
    entity_id = models.IntegerField(verbose_name='ID de Entidad')
    details = models.JSONField(null=True, blank=True, verbose_name='Detalles')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    
    class Meta:
        db_table = 'activity_logs'
        managed = False
        verbose_name = 'Log de Actividad'
        verbose_name_plural = 'Logs de Actividad'
        ordering = ['-created_at']
    
    def __str__(self) -> str:
        return f"{self.user.username} - {self.action} - {self.entity_type}#{self.entity_id}"