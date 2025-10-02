# api/admin.py
"""
Configuración del panel de administración
"""
from django.contrib import admin
from .models import Role, User, Product, Sale, SaleItem, InventoryMovement, Report


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'description']
    search_fields = ['name']


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['id', 'username', 'email', 'role', 'is_active', 'is_staff']
    list_filter = ['role', 'is_active', 'is_staff']
    search_fields = ['username', 'email']
    readonly_fields = ['date_joined', 'last_login']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'code', 'category', 'price', 'stock', 'user']
    list_filter = ['category']
    search_fields = ['name', 'code']
    readonly_fields = ['qr_code_path', 'barcode_path']


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    readonly_fields = ['price_unit', 'subtotal']


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'date', 'total_price']
    list_filter = ['date']
    search_fields = ['user__username']
    readonly_fields = ['date', 'total_price']
    inlines = [SaleItemInline]


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ['id', 'product', 'movement_type', 'quantity', 'date']
    list_filter = ['movement_type', 'date']
    search_fields = ['product__name']
    readonly_fields = ['date']


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'user', 'generated_at']
    list_filter = ['type', 'generated_at']
    search_fields = ['type', 'user__username']
    readonly_fields = ['generated_at']