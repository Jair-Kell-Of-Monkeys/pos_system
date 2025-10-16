# pylint: disable=no-member

"""
Vistas y ViewSets para la API REST
"""
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from django.db.models import Sum, Count
from django.utils import timezone
from django.db import transaction, models
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from django.conf import settings
from django.utils.timezone import make_aware
from datetime import timedelta
from decimal import Decimal

from .models import Role, User, Product, Sale, SaleItem, InventoryMovement, Report, ActivityLog
from .serializers import (
    RoleSerializer, UserSerializer, ProductSerializer,
    SaleSerializer, InventoryMovementSerializer, ReportSerializer, StockAdjustmentSerializer, ActivityLogSerializer
)
from .permissions import (
    IsAdmin, ProductPermission, SalePermission,
    UserManagementPermission, IsEmpleadoOrAdmin
)
from django.http import FileResponse, Http404
import os

class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para consultar roles (solo lectura)
    """
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]


class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestión de usuarios (solo admin)
    """
    queryset = User.objects.select_related('role').all()
    serializer_class = UserSerializer
    permission_classes = [UserManagementPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'email']
    ordering_fields = ['date_joined', 'username']
    ordering = ['-date_joined']
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def me(self, request):
        """
        Obtener información del usuario actual
        GET /api/users/me/
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        """
        Crear usuario. Si es admin creando empleado, asignar relación.
        POST /api/users/
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Si el admin está creando un empleado, asignar automáticamente
        if request.user.is_admin:
            role_id = request.data.get('role')
            if role_id == 2:  # Empleado
                serializer.validated_data['manager'] = request.user
        
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    def partial_update(self, request, *args, **kwargs):
        """
        PATCH /api/users/{id}/
        Actualizar datos del usuario (rol, contraseña, etc.)
        """
        instance = self.get_object()
        
        # Solo admin o el propio usuario pueden actualizar
        if not request.user.is_admin and request.user.id != instance.id:
            return Response(
                {'error': 'No tienes permiso para actualizar este usuario'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Si se está cambiando el rol, solo admin puede hacerlo
        if 'role' in request.data and not request.user.is_admin:
            return Response(
                {'error': 'Solo administradores pueden cambiar roles'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        # Registrar actividad
        ActivityLog.objects.create(
            user=request.user,
            action='update',
            entity_type='user',
            entity_id=instance.id,
            details={'changes': request.data}
        )
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'], url_path='activity')
    def user_activity(self, request, pk=None):
        """
        GET /api/users/{id}/activity/
        Histórico de actividad de un usuario
        """
        user = self.get_object()
        
        # Solo admin o el propio usuario pueden ver su actividad
        if not request.user.is_admin and request.user.id != user.id:
            return Response(
                {'error': 'No tienes permiso para ver esta actividad'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Ventas realizadas
        sales = Sale.objects.filter(user=user, is_cancelled=False).order_by('-date')[:10]
        sales_count = Sale.objects.filter(user=user, is_cancelled=False).count()
        total_sales = Sale.objects.filter(user=user, is_cancelled=False).aggregate(
            total=Sum('total_price')
        )['total'] or 0
        
        # Productos creados (solo si es admin)
        products_created = Product.objects.filter(user=user).count() if user.is_admin else 0
        
        # Logs de actividad recientes
        activity_logs = ActivityLog.objects.filter(user=user).order_by('-created_at')[:20]
        
        data = {
            'sales_count': sales_count,
            'total_sales_amount': float(total_sales),
            'products_created': products_created,
            'recent_sales': SaleSerializer(sales, many=True, context={'request': request}).data,
            'recent_activity': ActivityLogSerializer(activity_logs, many=True).data
        }
        
        return Response(data)

class ProductViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestión de productos
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [ProductPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code', 'category']
    ordering_fields = ['name', 'price', 'stock']
    ordering = ['name']
    
    def get_queryset(self):
        """
        Filtrar productos según el rol del usuario:
        - Admin: ve sus propios productos
        - Empleado: ve los productos de su admin/jefe
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        if user.is_admin:
            # Admin ve solo sus productos
            queryset = queryset.filter(user=user)
        elif user.is_empleado:
            # Empleado ve productos de su jefe
            if user.manager:
                queryset = queryset.filter(user=user.manager)
            else:
                # Si no tiene jefe asignado, no ve nada
                queryset = queryset.none()
        
        # Filtrar por stock bajo
        low_stock = self.request.query_params.get('low_stock', None)
        if low_stock:
            queryset = queryset.filter(stock__lte=10)
        
        # Filtrar por categoría
        category = self.request.query_params.get('category', None)
        if category:
            queryset = queryset.filter(category=category)
        
        # Filtrar por rango de precio
        min_price = self.request.query_params.get('min_price', None)
        max_price = self.request.query_params.get('max_price', None)
        if min_price:
            queryset = queryset.filter(price__gte=min_price)
        if max_price:
            queryset = queryset.filter(price__lte=max_price)
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def stock_history(self, request, pk=None):
        """
        Obtener historial de movimientos de un producto
        """
        product = self.get_object()
        movements = InventoryMovement.objects.filter(product=product)
        serializer = InventoryMovementSerializer(movements, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'], url_path='qrcode')
    def get_qr_code(self, request, pk=None):
        """
        Obtener imagen del código QR del producto
        GET /api/products/{id}/qrcode/
        """
        product = self.get_object()
        
        if not product.qr_code_path:
            return Response(
                {'error': 'Este producto no tiene código QR generado'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        file_path = os.path.join(settings.MEDIA_ROOT, product.qr_code_path)
        
        if not os.path.exists(file_path):
            return Response(
                {'error': 'Archivo de código QR no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return FileResponse(open(file_path, 'rb'), content_type='image/png')
    
    @action(detail=True, methods=['get'], url_path='barcode')
    def get_barcode(self, request, pk=None):
        """
        Obtener imagen del código de barras del producto
        GET /api/products/{id}/barcode/
        """
        product = self.get_object()
        
        if not product.barcode_path:
            return Response(
                {'error': 'Este producto no tiene código de barras generado'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        file_path = os.path.join(settings.MEDIA_ROOT, product.barcode_path)
        
        if not os.path.exists(file_path):
            return Response(
                {'error': 'Archivo de código de barras no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return FileResponse(open(file_path, 'rb'), content_type='image/png')
    
    @action(detail=True, methods=['patch'], url_path='adjust-stock')
    def adjust_stock(self, request, pk=None):
        """
        PATCH /api/products/{id}/adjust-stock/
        Ajuste manual de inventario
        Solo admin
        """
        product = self.get_object()
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        adjustment = serializer.validated_data['adjustment']
        reason = serializer.validated_data['reason']
        
        # Validar que no resulte en stock negativo
        new_stock = product.stock + adjustment
        if new_stock < 0:
            return Response(
                {'error': f'El ajuste resultaría en stock negativo. Stock actual: {product.stock}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Actualizar stock
        old_stock = product.stock
        product.stock = new_stock
        product.save()
        
        # Crear movimiento de inventario
        movement_type = 'entrada' if adjustment > 0 else 'salida'
        InventoryMovement.objects.create(
            product=product,
            movement_type=movement_type,
            quantity=abs(adjustment),
            note=f"Ajuste manual: {reason}"
        )
        
        # Registrar actividad
        ActivityLog.objects.create(
            user=request.user,
            action='adjust_stock',
            entity_type='product',
            entity_id=product.id,
            details={
                'old_stock': old_stock,
                'new_stock': new_stock,
                'adjustment': adjustment,
                'reason': reason
            }
        )
        
        return Response({
            'message': 'Stock ajustado correctamente',
            'product': ProductSerializer(product, context={'request': request}).data,
            'old_stock': old_stock,
            'new_stock': new_stock,
            'adjustment': adjustment
        })
    
    @action(detail=False, methods=['post'], url_path='scan', permission_classes=[IsAuthenticated])
    def scan_product(self, request):
        """
        POST /api/products/scan/
        
        Endpoint principal para escanear códigos QR o de barras desde Flutter.
        Usado por empleados en el punto de venta para identificar productos.
        
        REQUEST:
        {
            "code": "ABC123",           # Código escaneado (requerido)
            "code_type": "qr"           # Tipo: "qr" o "barcode" (opcional)
        }
        
        RESPONSE EXITOSO (200):
        {
            "success": true,
            "product": {
                "id": 1,
                "code": "ABC123",
                "name": "Tornillo 1/2 pulgada",
                "description": "Tornillo galvanizado",
                "price": 2.50,
                "stock": 150,
                "stock_status": "available",
                "category": "Ferretería",
                "available": true,
                "qr_code_url": "http://servidor.com/api/products/1/qrcode/",
                "barcode_url": "http://servidor.com/api/products/1/barcode/"
            }
        }
        
        RESPONSE ERROR (404):
        {
            "success": false,
            "error": "No se encontró ningún producto con el código: ABC123",
            "error_code": "PRODUCT_NOT_FOUND"
        }
        """
        
        # Obtener y validar datos
        code = request.data.get('code')
        code_type = request.data.get('code_type', 'qr')
        
        if not code:
            return Response(
                {
                    'success': False,
                    'error': 'El campo "code" es requerido',
                    'error_code': 'MISSING_CODE'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if code_type not in ['qr', 'barcode']:
            return Response(
                {
                    'success': False,
                    'error': 'El campo "code_type" debe ser "qr" o "barcode"',
                    'error_code': 'INVALID_CODE_TYPE'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Normalizar código (eliminar espacios, convertir a mayúsculas)
        code_cleaned = code.strip().upper()
        
        try:
            # Buscar producto
            product = Product.objects.select_related('user').get(code=code_cleaned)
            
            # Verificar permisos según rol
            user = request.user
            
            if user.is_admin:
                # Admin solo puede escanear sus propios productos
                if product.user_id != user.id:
                    return Response(
                        {
                            'success': False,
                            'error': 'Este producto no pertenece a tu inventario',
                            'error_code': 'PRODUCT_NOT_AUTHORIZED'
                        },
                        status=status.HTTP_403_FORBIDDEN
                    )
            
            elif user.is_empleado:
                # Empleado puede escanear productos de su jefe
                if not user.manager or product.user_id != user.manager.id:
                    return Response(
                        {
                            'success': False,
                            'error': 'Este producto no pertenece al inventario de tu negocio',
                            'error_code': 'PRODUCT_NOT_AUTHORIZED'
                        },
                        status=status.HTTP_403_FORBIDDEN
                    )
            
            # Determinar estado del stock
            if product.stock > 10:
                stock_status = 'available'
            elif product.stock > 0:
                stock_status = 'low'
            else:
                stock_status = 'out_of_stock'
            
            available = product.stock > 0
            
            # Construir URLs para imágenes
            qr_code_url = None
            barcode_url = None
            
            if product.qr_code_path:
                qr_code_url = request.build_absolute_uri(
                    f'/api/products/{product.id}/qrcode/'
                )
            
            if product.barcode_path:
                barcode_url = request.build_absolute_uri(
                    f'/api/products/{product.id}/barcode/'
                )
            
            # Registrar log de escaneo
            ActivityLog.objects.create(
                user=request.user,
                action='scan',
                entity_type='product',
                entity_id=product.id,
                details={
                    'code': code_cleaned,
                    'code_type': code_type,
                    'stock_at_scan': product.stock
                }
            )
            
            # Respuesta exitosa
            return Response({
                'success': True,
                'product': {
                    'id': product.id,
                    'code': product.code if product.code else '',
                    'name': product.name,
                    'price': float(product.price),
                    'stock': product.stock,
                    'stock_status': stock_status,
                    'category': product.category if product.category else 'Sin categoría',
                    'available': available,
                    'qr_code_url': qr_code_url,
                    'barcode_url': barcode_url,
                    'user_id': product.user_id
                }
            }, status=status.HTTP_200_OK)
        
        except Product.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'error': f'No se encontró ningún producto con el código: {code_cleaned}',
                    'error_code': 'PRODUCT_NOT_FOUND',
                    'scanned_code': code_cleaned
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        except Exception as e:
            return Response(
                {
                    'success': False,
                    'error': 'Error al procesar el escaneo',
                    'error_code': 'INTERNAL_ERROR',
                    'details': str(e) if settings.DEBUG else None
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


    @action(detail=False, methods=['post'], url_path='validate-products', permission_classes=[IsAuthenticated])
    def validate_products(self, request):
        """
        POST /api/products/validate-products/
        
        Valida múltiples productos antes de crear una venta.
        El empleado escanea productos y antes de confirmar la venta,
        valida que todos tengan stock suficiente.
        
        REQUEST:
        {
            "items": [
                {"product_id": 1, "quantity": 2},
                {"product_id": 5, "quantity": 1},
                {"product_id": 12, "quantity": 3}
            ]
        }
        
        RESPONSE (200):
        {
            "success": true,
            "valid": true,
            "items": [
                {
                    "product_id": 1,
                    "name": "Tornillo 1/2",
                    "price": 2.50,
                    "quantity": 2,
                    "subtotal": 5.00,
                    "stock_available": 150,
                    "valid": true
                },
                {
                    "product_id": 5,
                    "name": "Clavo 3 pulgadas",
                    "price": 1.00,
                    "quantity": 1,
                    "subtotal": 1.00,
                    "stock_available": 200,
                    "valid": true
                }
            ],
            "summary": {
                "total_items": 3,
                "total_amount": 6.00,
                "all_valid": true
            },
            "errors": []
        }
        
        RESPONSE CON ERRORES (200):
        {
            "success": true,
            "valid": false,
            "items": [...],
            "summary": {...},
            "errors": [
                {
                    "product_id": 12,
                    "error": "Stock insuficiente",
                    "requested": 3,
                    "available": 1
                }
            ]
        }
        """
        
        items_data = request.data.get('items', [])
        
        if not items_data or not isinstance(items_data, list):
            return Response(
                {
                    'success': False,
                    'error': 'Se requiere un array de items con formato: [{"product_id": 1, "quantity": 2}]',
                    'error_code': 'INVALID_FORMAT'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user = request.user
        validated_items = []
        errors = []
        total_amount = Decimal('0.00')
        total_items = 0
        all_valid = True
        
        for item_data in items_data:
            product_id = item_data.get('product_id')
            quantity = item_data.get('quantity', 1)
            
            # Validaciones básicas
            if not product_id:
                errors.append({
                    'error': 'product_id es requerido',
                    'item': item_data
                })
                all_valid = False
                continue
            
            if not isinstance(quantity, int) or quantity <= 0:
                errors.append({
                    'product_id': product_id,
                    'error': 'Cantidad debe ser un número entero positivo',
                    'quantity': quantity
                })
                all_valid = False
                continue
            
            try:
                product = Product.objects.get(id=product_id)
                
                # Verificar permisos
                if user.is_admin and product.user_id != user.id:
                    errors.append({
                        'product_id': product_id,
                        'error': 'No tienes permiso para vender este producto'
                    })
                    all_valid = False
                    continue
                
                if user.is_empleado and (not user.manager or product.user_id != user.manager.id):
                    errors.append({
                        'product_id': product_id,
                        'error': 'Este producto no pertenece a tu negocio'
                    })
                    all_valid = False
                    continue
                
                # Verificar stock
                stock_valid = product.stock >= quantity
                if not stock_valid:
                    errors.append({
                        'product_id': product_id,
                        'name': product.name,
                        'error': 'Stock insuficiente',
                        'requested': quantity,
                        'available': product.stock
                    })
                    all_valid = False
                
                # Calcular subtotal
                subtotal = product.price * quantity
                
                validated_items.append({
                    'product_id': product.id,
                    'code': product.code,
                    'name': product.name,
                    'price': float(product.price),
                    'quantity': quantity,
                    'subtotal': float(subtotal),
                    'stock_available': product.stock,
                    'valid': stock_valid
                })
                
                if stock_valid:
                    total_amount += subtotal
                    total_items += quantity
            
            except Product.DoesNotExist:
                errors.append({
                    'product_id': product_id,
                    'error': 'Producto no encontrado'
                })
                all_valid = False
        
        return Response({
            'success': True,
            'valid': all_valid,
            'items': validated_items,
            'summary': {
                'total_items': total_items,
                'total_amount': float(total_amount),
                'all_valid': all_valid,
                'items_count': len(validated_items)
            },
            'errors': errors
        })
    
    @action(detail=False, methods=['get'], url_path='quick-search', permission_classes=[IsAuthenticated])
    def quick_search(self, request):
        """
        GET /api/products/quick-search/?q=tornillo
        
        Búsqueda rápida de productos por nombre o código.
        Útil para cuando el escaneo falla o el producto no tiene código.
        
        RESPONSE:
        {
            "success": true,
            "count": 3,
            "products": [
                {
                    "id": 1,
                    "code": "ABC123",
                    "name": "Tornillo 1/2 pulgada",
                    "price": 2.50,
                    "stock": 150,
                    "available": true,
                    "category": "Ferretería"
                },
                ...
            ]
        }
        """
        query = request.query_params.get('q', '').strip()
        
        if not query or len(query) < 2:
            return Response(
                {
                    'success': False,
                    'error': 'Se requiere un término de búsqueda de al menos 2 caracteres',
                    'error_code': 'QUERY_TOO_SHORT'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user = request.user
        
        # Filtrar productos según permisos
        if user.is_admin:
            products = Product.objects.filter(user=user)
        elif user.is_empleado and user.manager:
            products = Product.objects.filter(user=user.manager)
        else:
            products = Product.objects.none()
        
        # Buscar por nombre o código
        products = products.filter(
            models.Q(name__icontains=query) | models.Q(code__icontains=query)
        )[:20]  # Limitar a 20 resultados
        
        results = []
        for product in products:
            results.append({
                'id': product.id,
                'code': product.code,
                'name': product.name,
                'price': float(product.price),
                'stock': product.stock,
                'available': product.stock > 0,
                'category': product.category or 'Sin categoría'
            })
        
        return Response({
            'success': True,
            'count': len(results),
            'products': results
        })



class SaleViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestión de ventas
    """
    queryset = Sale.objects.select_related('user').prefetch_related('items__product').all()
    serializer_class = SaleSerializer
    permission_classes = [SalePermission]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['date', 'total_price']
    ordering = ['-date']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filtros de fecha
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        if user.is_admin:
            # Admin ve sus ventas y las de sus empleados
            employee_ids = user.employees.values_list('id', flat=True)
            queryset = queryset.filter(user__in=[user.id] + list(employee_ids))
        elif user.is_empleado:
            # Empleado solo ve sus propias ventas
            queryset = queryset.filter(user=user)
        
        return queryset
    
    @action(detail=False, methods=['get'], url_path='my-sales')
    def my_sales(self, request):
        """
        Ver historial de ventas del usuario actual
        GET /api/sales/my-sales/
        """
        sales = Sale.objects.filter(user=request.user).select_related('user').prefetch_related('items__product')
        
        # Aplicar paginación
        page = self.paginate_queryset(sales)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(sales, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Resumen de ventas
        """
        queryset = self.get_queryset()
        
        summary = queryset.aggregate(
            total_sales=Sum('total_price'),
            count_sales=Count('id')
        )
        
        if summary['total_sales'] and summary['count_sales']:
            summary['average_sale'] = float(summary['total_sales']) / summary['count_sales']
        else:
            summary['average_sale'] = 0
        
        return Response(summary)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAdmin])
    def by_period(self, request):
        """
        Ventas agrupadas por período
        """
        period = request.query_params.get('period', 'day')
        
        now = timezone.now()
        if period == 'day':
            start_date = now - timedelta(days=7)
        elif period == 'week':
            start_date = now - timedelta(weeks=4)
        elif period == 'month':
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=30)
        
        sales = Sale.objects.filter(date__gte=start_date).order_by('date')
        
        from collections import defaultdict
        grouped = defaultdict(lambda: {'total': 0, 'count': 0})
        
        for sale in sales:
            if period == 'day':
                key = sale.date.strftime('%Y-%m-%d')
            elif period == 'week':
                key = sale.date.strftime('%Y-W%U')
            else:
                key = sale.date.strftime('%Y-%m')
            
            grouped[key]['total'] += float(sale.total_price)
            grouped[key]['count'] += 1
        
        result = [
            {'period': k, 'total': v['total'], 'count': v['count']}
            for k, v in sorted(grouped.items())
        ]
        
        return Response(result)
    
    @action(detail=False, methods=['get'], url_path='by-user/(?P<user_id>[^/.]+)')
    def sales_by_user(self, request, user_id=None):
        """
        GET /api/sales/by-user/{user_id}/
        """
        # Validar permisos
        if not request.user.is_admin and str(request.user.id) != str(user_id):
            return Response(
                {'error': 'No tienes permiso para ver ventas de otros usuarios'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'Usuario no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Si es admin verificando empleado
        if request.user.is_admin and target_user.is_empleado:
            if target_user.manager_id != request.user.id:
                return Response(
                    {'error': 'Este empleado no pertenece a tu organización'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        sales = Sale.objects.filter(user_id=user_id).select_related('user').prefetch_related('items__product')
        
        # Filtros opcionales
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        if start_date:
            sales = sales.filter(date__gte=start_date)
        if end_date:
            sales = sales.filter(date__lte=end_date)
        
        page = self.paginate_queryset(sales)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(sales, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='cancel')
    @transaction.atomic
    def cancel_sale(self, request, pk=None):
        """POST /api/sales/{id}/cancel/"""
        sale = self.get_object()
        
        if sale.is_cancelled:
            return Response(
                {'error': 'Esta venta ya está cancelada'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Devolver stock
        for item in sale.items.all():
            product = item.product
            product.stock += item.quantity
            product.save()
            
            InventoryMovement.objects.create(
                product=product,
                movement_type='entrada',
                quantity=item.quantity,
                note=f"Devolución por cancelación de venta #{sale.id}"
            )
        
        # Marcar como cancelada
        sale.is_cancelled = True
        sale.cancelled_at = timezone.now()
        sale.cancelled_by = request.user
        sale.save()
        
        # Log
        ActivityLog.objects.create(
            user=request.user,
            action='cancel',
            entity_type='sale',
            entity_id=sale.id,
            details={
                'original_total': float(sale.total_price),
                'items_count': sale.items.count()
            }
        )
        
        return Response({
            'message': 'Venta cancelada exitosamente',
            'sale': SaleSerializer(sale, context={'request': request}).data
        })
    
    @action(detail=False, methods=['post'], url_path='create-from-scan', permission_classes=[IsAuthenticated])
    @transaction.atomic
    def create_from_scan(self, request):
        """
        POST /api/sales/create-from-scan/
        
        Crea una venta directamente desde productos escaneados en Flutter.
        Este es el endpoint principal que usará la app móvil para registrar ventas.
        
        REQUEST:
        {
            "items": [
                {"product_id": 1, "quantity": 2},
                {"product_id": 5, "quantity": 1}
            ],
            "payment_method": "efectivo",    # efectivo, tarjeta, transferencia
            "notes": "Cliente frecuente"      # Opcional
        }
        
        RESPONSE EXITOSO (201):
        {
            "success": true,
            "sale": {
                "id": 45,
                "date": "2025-01-15T14:30:00Z",
                "total_price": 6.00,
                "payment_method": "efectivo",
                "user": {
                    "id": 3,
                    "username": "empleado1"
                },
                "items": [
                    {
                        "product": {
                            "id": 1,
                            "code": "ABC123",
                            "name": "Tornillo 1/2"
                        },
                        "quantity": 2,
                        "price": 2.50,
                        "subtotal": 5.00
                    },
                    {
                        "product": {
                            "id": 5,
                            "code": "XYZ789",
                            "name": "Clavo 3 pulgadas"
                        },
                        "quantity": 1,
                        "price": 1.00,
                        "subtotal": 1.00
                    }
                ]
            },
            "message": "Venta registrada exitosamente",
            "stock_updated": true
        }
        
        RESPONSE ERROR (400):
        {
            "success": false,
            "error": "Stock insuficiente para algunos productos",
            "errors": [
                {
                    "product_id": 1,
                    "name": "Tornillo 1/2",
                    "requested": 5,
                    "available": 2
                }
            ]
        }
        """
        
        # Validar datos de entrada
        items_data = request.data.get('items', [])
        payment_method = request.data.get('payment_method', 'efectivo')
        notes = request.data.get('notes', '')
        
        if not items_data or not isinstance(items_data, list) or len(items_data) == 0:
            return Response(
                {
                    'success': False,
                    'error': 'Se requiere al menos un producto para crear una venta',
                    'error_code': 'NO_ITEMS'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if payment_method not in ['efectivo', 'tarjeta', 'transferencia']:
            return Response(
                {
                    'success': False,
                    'error': 'Método de pago inválido. Opciones: efectivo, tarjeta, transferencia',
                    'error_code': 'INVALID_PAYMENT_METHOD'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user = request.user
        total_price = Decimal('0.00')
        sale_items = []
        errors = []
        
        # Validar todos los productos antes de crear la venta
        for item_data in items_data:
            product_id = item_data.get('product_id')
            quantity = item_data.get('quantity', 1)
            
            if not product_id or not isinstance(quantity, int) or quantity <= 0:
                return Response(
                    {
                        'success': False,
                        'error': 'Formato inválido en items. Se requiere product_id (int) y quantity (int > 0)',
                        'error_code': 'INVALID_ITEM_FORMAT'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                product = Product.objects.select_for_update().get(id=product_id)
                
                # Verificar permisos
                if user.is_admin and product.user_id != user.id:
                    errors.append({
                        'product_id': product_id,
                        'error': 'No tienes permiso para vender este producto'
                    })
                    continue
                
                if user.is_empleado and (not user.manager or product.user_id != user.manager.id):
                    errors.append({
                        'product_id': product_id,
                        'error': 'Este producto no pertenece a tu negocio'
                    })
                    continue
                
                # Verificar stock suficiente
                if product.stock < quantity:
                    errors.append({
                        'product_id': product_id,
                        'name': product.name,
                        'code': product.code,
                        'error': 'Stock insuficiente',
                        'requested': quantity,
                        'available': product.stock
                    })
                    continue
                
                # Agregar a la lista de items válidos
                subtotal = product.price * quantity
                total_price += subtotal
                
                sale_items.append({
                    'product': product,
                    'quantity': quantity,
                    'price': product.price,
                    'subtotal': subtotal
                })
            
            except Product.DoesNotExist:
                errors.append({
                    'product_id': product_id,
                    'error': 'Producto no encontrado'
                })
        
        # Si hay errores, no crear la venta
        if errors:
            return Response(
                {
                    'success': False,
                    'error': 'No se pudo completar la venta',
                    'errors': errors,
                    'error_code': 'VALIDATION_FAILED'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Crear la venta
        sale = Sale.objects.create(
            user=request.user,
            total_price=total_price,
            payment_method=payment_method
        )
        
        # Crear items de venta y actualizar stock
        for item_data in sale_items:
            product = item_data['product']
            quantity = item_data['quantity']
            price = item_data['price']
            subtotal = item_data['subtotal']
            
            # Crear item de venta
            SaleItem.objects.create(
                sale=sale,
                product=product,
                quantity=quantity,
                price=price,
                subtotal=subtotal
            )
            
            # Actualizar stock
            product.stock -= quantity
            product.save()
            
            # Registrar movimiento de inventario
            InventoryMovement.objects.create(
                product=product,
                movement_type='salida',
                quantity=quantity,
                note=f'Venta #{sale.id} - {request.user.username}'
            )
        
        # Registrar actividad
        ActivityLog.objects.create(
            user=request.user,
            action='create',
            entity_type='sale',
            entity_id=sale.id,
            details={
                'total_price': float(total_price),
                'items_count': len(sale_items),
                'payment_method': payment_method,
                'created_from': 'flutter_scan'
            }
        )
        
        # Preparar respuesta
        sale_data = {
            'id': sale.id,
            'date': sale.date.isoformat(),
            'total_price': float(sale.total_price),
            'payment_method': payment_method,
            'notes': notes,
            'user': {
                'id': request.user.id,
                'username': request.user.username
            },
            'items': []
        }
        
        # Agregar items a la respuesta
        for sale_item in sale.items.all():
            sale_data['items'].append({
                'product': {
                    'id': sale_item.product.id,
                    'code': sale_item.product.code,
                    'name': sale_item.product.name
                },
                'quantity': sale_item.quantity,
                'price': float(sale_item.price),
                'subtotal': float(sale_item.subtotal)
            })
        
        return Response({
            'success': True,
            'sale': sale_data,
            'message': 'Venta registrada exitosamente',
            'stock_updated': True
        }, status=status.HTTP_201_CREATED)



class InventoryMovementViewSet(viewsets.ModelViewSet):
    """
    ViewSet para movimientos de inventario
    """
    queryset = InventoryMovement.objects.select_related('product').all()
    serializer_class = InventoryMovementSerializer
    permission_classes = [IsEmpleadoOrAdmin]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['date']
    ordering = ['-date']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtrar por producto
        product_id = self.request.query_params.get('product', None)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        # Filtrar por tipo de movimiento
        movement_type = self.request.query_params.get('type', None)
        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)
        
        # Filtrar por rango de fechas
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        return queryset
    
    def get_permissions(self):
        """
        Solo admin puede crear/editar/eliminar movimientos manuales
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdmin()]
        return [IsEmpleadoOrAdmin()]
    
    @action(detail=False, methods=['get'], url_path='low-stock')
    def low_stock_alert(self, request):
        """
        Obtener productos con bajo stock (<=10)
        GET /api/inventory-movements/low-stock/
        """
        # Umbral de stock bajo (configurable)
        threshold = int(request.query_params.get('threshold', 10))
        
        low_stock_products = Product.objects.filter(stock__lte=threshold).select_related('user')
        
        # Si no es admin, solo mostrar sus productos
        if not request.user.is_admin:
            low_stock_products = low_stock_products.filter(user=request.user)
        
        products_data = []
        for product in low_stock_products:
            products_data.append({
                'id': product.id,
                'name': product.name,
                'code': product.code,
                'category': product.category,
                'current_stock': product.stock,
                'price': float(product.price),
                'user': product.user.username,
                'status': 'critical' if product.stock <= 5 else 'low'
            })
        
        return Response({
            'count': len(products_data),
            'threshold': threshold,
            'products': products_data
        })


class ReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet para reportes (solo admin)
    """
    queryset = Report.objects.select_related('user').all()
    serializer_class = ReportSerializer
    permission_classes = [IsAdmin]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['generated_at']
    ordering = ['-generated_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtrar por tipo
        report_type = self.request.query_params.get('type', None)
        if report_type:
            queryset = queryset.filter(type=report_type)
        
        return queryset
    
    def _convert_to_json_serializable(self, obj):
        """
        Convierte objetos Decimal a float para serialización JSON
        """
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._convert_to_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_to_json_serializable(item) for item in obj]
        return obj
    
    @action(detail=False, methods=['post'])
    def generate_sales_report(self, request):
        """
        Generar reporte de ventas
        """
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        
        if not start_date or not end_date:
            return Response(
                {'error': 'Se requieren start_date y end_date'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Asegurar que las fechas son timezone-aware
        from django.utils.dateparse import parse_datetime, parse_date
        
        # Intentar parsear como datetime primero, luego como date
        start = parse_datetime(start_date)
        if start is None:
            start = parse_date(start_date)
            if start:
                start = timezone.make_aware(timezone.datetime.combine(start, timezone.datetime.min.time()))
        
        end = parse_datetime(end_date)
        if end is None:
            end = parse_date(end_date)
            if end:
                end = timezone.make_aware(timezone.datetime.combine(end, timezone.datetime.max.time()))
        
        if not start or not end:
            return Response(
                {'error': 'Formato de fecha inválido. Use YYYY-MM-DD o ISO 8601'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Consultar ventas
        sales = Sale.objects.filter(
            date__gte=start,
            date__lte=end
        ).select_related('user').prefetch_related('items__product')
        
        # Calcular datos
        total_sales = sales.aggregate(total=Sum('total_price'))['total'] or 0
        count_sales = sales.count()
        
        # Productos más vendidos
        from django.db.models import Sum as DbSum
        top_products = SaleItem.objects.filter(
            sale__date__gte=start,
            sale__date__lte=end
        ).values('product__name').annotate(
            total_quantity=DbSum('quantity'),
            total_amount=DbSum('subtotal')
        ).order_by('-total_quantity')[:10]
        
        # Convertir QuerySet a lista y procesar Decimals
        top_products_list = []
        for item in top_products:
            top_products_list.append({
                'product__name': item['product__name'],
                'total_quantity': int(item['total_quantity']) if item['total_quantity'] else 0,
                'total_amount': float(item['total_amount']) if item['total_amount'] else 0.0
            })
        
        report_data = {
            'period': {
                'start': start.isoformat(),
                'end': end.isoformat()
            },
            'summary': {
                'total_sales': float(total_sales) if total_sales else 0.0,
                'count_sales': count_sales,
                'average_sale': float(total_sales / count_sales) if count_sales > 0 else 0.0
            },
            'top_products': top_products_list
        }
        
        # Crear el reporte
        report = Report(
            user=request.user,
            type='ventas',
            data=report_data
        )
        report.save()
        
        serializer = self.get_serializer(report)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['post'])
    def generate_inventory_report(self, request):
        """
        Generar reporte de inventario
        """
        products = Product.objects.all()
        
        # Calcular datos
        total_products = products.count()
        total_stock_value = sum(float(p.price * p.stock) for p in products)
        low_stock_products = products.filter(stock__lte=10).count()
        
        products_data = [
            {
                'name': p.name,
                'code': p.code,
                'category': p.category,
                'stock': p.stock,
                'price': float(p.price),
                'value': float(p.price * p.stock)
            }
            for p in products
        ]
        
        report_data = {
            'generated_at': timezone.now().isoformat(),
            'summary': {
                'total_products': total_products,
                'total_stock_value': total_stock_value,
                'low_stock_products': low_stock_products
            },
            'products': products_data
        }
        
        # Crear el reporte
        report = Report(
            user=request.user,
            type='inventario',
            data=report_data
        )
        report.save()
        
        serializer = self.get_serializer(report)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['get'], url_path='sales/daily')
    def daily_sales_report(self, request):
        """
        Reporte de ventas del día actual
        GET /api/reports/sales/daily/
        """
        from django.utils.timezone import now, make_aware
        import datetime
        
        today = now().date()
        start_datetime = make_aware(datetime.datetime.combine(today, datetime.time.min))
        end_datetime = make_aware(datetime.datetime.combine(today, datetime.time.max))
        
        sales = Sale.objects.filter(
            date__gte=start_datetime,
            date__lte=end_datetime
        )
        
        # Filtrar por usuario si no es admin
        if not request.user.is_admin:
            sales = sales.filter(user=request.user)
        
        total_sales = sales.aggregate(total=Sum('total_price'))['total'] or 0
        count_sales = sales.count()
        
        return Response({
            'date': today.isoformat(),
            'total_sales': float(total_sales),
            'count_sales': count_sales,
            'average_sale': float(total_sales / count_sales) if count_sales > 0 else 0.0
        })
    
    @action(detail=False, methods=['get'], url_path='sales/weekly')
    def weekly_sales_report(self, request):
        """
        Reporte de ventas de la semana actual
        GET /api/reports/sales/weekly/
        """
        from django.utils.timezone import now
        import datetime
        
        today = now().date()
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)
        
        start_datetime = make_aware(datetime.datetime.combine(start_of_week, datetime.time.min))
        end_datetime = make_aware(datetime.datetime.combine(end_of_week, datetime.time.max))
        
        sales = Sale.objects.filter(
            date__gte=start_datetime,
            date__lte=end_datetime
        )
        
        if not request.user.is_admin:
            sales = sales.filter(user=request.user)
        
        total_sales = sales.aggregate(total=Sum('total_price'))['total'] or 0
        count_sales = sales.count()
        
        # Agrupar por día
        from collections import defaultdict
        daily_breakdown = defaultdict(lambda: {'total': 0, 'count': 0})
        
        for sale in sales:
            day_key = sale.date.strftime('%Y-%m-%d')
            daily_breakdown[day_key]['total'] += float(sale.total_price)
            daily_breakdown[day_key]['count'] += 1
        
        return Response({
            'week_start': start_of_week.isoformat(),
            'week_end': end_of_week.isoformat(),
            'total_sales': float(total_sales),
            'count_sales': count_sales,
            'average_sale': float(total_sales / count_sales) if count_sales > 0 else 0.0,
            'daily_breakdown': dict(daily_breakdown)
        })
    
    @action(detail=False, methods=['get'], url_path='sales/monthly')
    def monthly_sales_report(self, request):
        """
        Reporte de ventas del mes actual
        GET /api/reports/sales/monthly/
        """
        from django.utils.timezone import now
        import datetime
        
        today = now().date()
        start_of_month = today.replace(day=1)
        
        # Último día del mes
        if today.month == 12:
            end_of_month = today.replace(day=31)
        else:
            end_of_month = (start_of_month.replace(month=start_of_month.month + 1) - datetime.timedelta(days=1))
        
        start_datetime = make_aware(datetime.datetime.combine(start_of_month, datetime.time.min))
        end_datetime = make_aware(datetime.datetime.combine(end_of_month, datetime.time.max))
        
        sales = Sale.objects.filter(
            date__gte=start_datetime,
            date__lte=end_datetime
        )
        
        if not request.user.is_admin:
            sales = sales.filter(user=request.user)
        
        total_sales = sales.aggregate(total=Sum('total_price'))['total'] or 0
        count_sales = sales.count()
        
        return Response({
            'month': start_of_month.strftime('%Y-%m'),
            'month_start': start_of_month.isoformat(),
            'month_end': end_of_month.isoformat(),
            'total_sales': float(total_sales),
            'count_sales': count_sales,
            'average_sale': float(total_sales / count_sales) if count_sales > 0 else 0.0
        })
    
    @action(detail=False, methods=['get'], url_path='sales/top-products')
    def top_products_report(self, request):
        """
        Productos más vendidos (últimos 30 días por defecto)
        GET /api/reports/sales/top-products/?days=30
        """
        from django.utils.timezone import now
        import datetime
        
        days = int(request.query_params.get('days', 30))
        start_date = now() - datetime.timedelta(days=days)
        
        top_products = SaleItem.objects.filter(
            sale__date__gte=start_date
        ).values('product__name', 'product__code', 'product__category').annotate(
            total_quantity=Sum('quantity'),
            total_amount=Sum('subtotal'),
            times_sold=Count('id')
        ).order_by('-total_quantity')[:20]
        
        products_list = []
        for item in top_products:
            products_list.append({
                'product_name': item['product__name'],
                'product_code': item['product__code'],
                'category': item['product__category'],
                'total_quantity': int(item['total_quantity']),
                'total_amount': float(item['total_amount']),
                'times_sold': item['times_sold']
            })
        
        return Response({
            'period_days': days,
            'start_date': start_date.date().isoformat(),
            'products': products_list
        })
    
@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """
    Registro público de nuevos usuarios
    POST /api/auth/register/
    """
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')

    # FORZAR rol empleado
    role_id = 2  # Siempre empleado
    
    # Validaciones básicas
    if not username or not email or not password:
        return Response(
            {'error': 'Se requieren username, email y password'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verificar si el usuario ya existe
    if User.objects.filter(username=username).exists():
        return Response(
            {'error': 'El nombre de usuario ya está en uso'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if User.objects.filter(email=email).exists():
        return Response(
            {'error': 'El email ya está registrado'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Obtener rol
    try:
        role = Role.objects.get(id=role_id)
    except Role.DoesNotExist:
        return Response(
            {'error': 'Rol inválido'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Crear usuario
    try:
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=role,
            is_active=True
        )
        
        return Response({
            'message': 'Usuario creado exitosamente',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': role.name
            }
        }, status=status.HTTP_201_CREATED)
    
    except Exception as e:
        return Response(
            {'error': f'Error al crear usuario: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

class DashboardViewSet(viewsets.ViewSet):
    """
    ViewSet para dashboard y resúmenes
    Funciona para Admin y Empleados con datos adaptados a cada rol
    """
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        """
        GET /api/dashboard/summary/
        
        Resumen global del dashboard adaptado según el rol del usuario.
        
        ADMIN ve:
        - Sus ventas + ventas de sus empleados
        - Sus productos
        - Ventas por empleado
        - Top productos
        - Stock bajo
        
        EMPLEADO ve:
        - Solo sus propias ventas
        - Productos de su manager
        - Sus estadísticas personales
        - Top productos que ha vendido
        - Stock bajo de productos de su manager
        """
        from django.utils.timezone import now
        import datetime
        
        user = request.user
        today = now().date()
        start_datetime = make_aware(datetime.datetime.combine(today, datetime.time.min))
        end_datetime = make_aware(datetime.datetime.combine(today, datetime.time.max))
        
        # ============================================
        # DETERMINAR DATOS SEGÚN ROL
        # ============================================
        
        if user.is_admin:
            # ===== ADMIN =====
            # Ve sus datos + de sus empleados
            employee_ids = list(user.employees.values_list('id', flat=True))
            user_ids = [user.id] + employee_ids
            products_queryset = Product.objects.filter(user=user)
            
            # Información del rol
            role_info = {
                'role': 'admin',
                'can_manage_products': True,
                'can_manage_employees': True,
                'employees_count': len(employee_ids)
            }
            
        elif user.is_empleado:
            # ===== EMPLEADO =====
            # Solo ve sus propios datos
            user_ids = [user.id]
            
            # Productos de su manager
            if user.manager:
                products_queryset = Product.objects.filter(user=user.manager)
            else:
                products_queryset = Product.objects.none()
            
            # Información del rol
            role_info = {
                'role': 'empleado',
                'can_manage_products': False,
                'can_manage_employees': False,
                'manager': {
                    'id': user.manager.id if user.manager else None,
                    'username': user.manager.username if user.manager else None
                } if user.manager else None
            }
        else:
            # Usuario sin rol definido
            return Response(
                {'error': 'Usuario sin rol asignado'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # ============================================
        # 1. VENTAS DE HOY
        # ============================================
        
        today_sales = Sale.objects.filter(
            user_id__in=user_ids,
            date__gte=start_datetime,
            date__lte=end_datetime,
            is_cancelled=False
        )
        
        today_sales_data = {
            'count': today_sales.count(),
            'total': float(today_sales.aggregate(total=Sum('total_price'))['total'] or 0)
        }
        
        # ============================================
        # 2. VENTAS DE LA SEMANA
        # ============================================
        
        start_of_week = today - datetime.timedelta(days=today.weekday())
        week_start_datetime = make_aware(datetime.datetime.combine(start_of_week, datetime.time.min))
        
        week_sales = Sale.objects.filter(
            user_id__in=user_ids,
            date__gte=week_start_datetime,
            date__lte=end_datetime,
            is_cancelled=False
        )
        
        week_sales_data = {
            'count': week_sales.count(),
            'total': float(week_sales.aggregate(total=Sum('total_price'))['total'] or 0)
        }
        
        # ============================================
        # 3. VENTAS DEL MES
        # ============================================
        
        start_of_month = today.replace(day=1)
        month_start_datetime = make_aware(datetime.datetime.combine(start_of_month, datetime.time.min))
        
        month_sales = Sale.objects.filter(
            user_id__in=user_ids,
            date__gte=month_start_datetime,
            date__lte=end_datetime,
            is_cancelled=False
        )
        
        month_sales_data = {
            'count': month_sales.count(),
            'total': float(month_sales.aggregate(total=Sum('total_price'))['total'] or 0)
        }
        
        # ============================================
        # 4. TOP PRODUCTOS (Últimos 30 días)
        # ============================================
        
        thirty_days_ago = now() - datetime.timedelta(days=30)
        
        # Top 5 productos más vendidos
        top_products = SaleItem.objects.filter(
            sale__date__gte=thirty_days_ago,
            sale__user_id__in=user_ids,
            sale__is_cancelled=False
        ).values('product__id', 'product__name', 'product__code').annotate(
            total_quantity=Sum('quantity'),
            total_amount=Sum('subtotal')
        ).order_by('-total_quantity')[:5]
        
        top_products_data = []
        for item in top_products:
            top_products_data.append({
                'product_id': item['product__id'],
                'product_name': item['product__name'],
                'product_code': item['product__code'],
                'quantity_sold': int(item['total_quantity']),
                'total_amount': float(item['total_amount'])
            })
        
        # ============================================
        # 5. STOCK BAJO (Productos con stock <= 10)
        # ============================================
        
        low_stock_products = products_queryset.filter(stock__lte=10).order_by('stock')
        
        low_stock_data = []
        for p in low_stock_products[:5]:  # Solo mostrar los 5 más críticos
            low_stock_data.append({
                'id': p.id,
                'name': p.name,
                'code': p.code if p.code else '',
                'stock': p.stock,
                'category': p.category if p.category else 'Sin categoría',
                'status': 'critical' if p.stock <= 5 else 'low',
                'price': float(p.price)
            })
        
        # ============================================
        # 6. VALOR TOTAL DEL INVENTARIO
        # ============================================
        
        total_inventory_value = sum(float(p.price * p.stock) for p in products_queryset)
        total_products_count = products_queryset.count()
        
        inventory_summary = {
            'total_value': total_inventory_value,
            'total_products': total_products_count,
            'low_stock_count': low_stock_products.count()
        }
        
        # ============================================
        # 7. VENTAS POR EMPLEADO (Solo para Admin)
        # ============================================
        
        sales_by_employee = []
        
        if user.is_admin and len(employee_ids) > 0:
            for emp_id in employee_ids:
                try:
                    emp = User.objects.get(id=emp_id)
                    
                    # Ventas del día del empleado
                    emp_today_sales = Sale.objects.filter(
                        user_id=emp_id,
                        date__gte=start_datetime,
                        date__lte=end_datetime,
                        is_cancelled=False
                    )
                    
                    # Ventas del mes del empleado
                    emp_month_sales = Sale.objects.filter(
                        user_id=emp_id,
                        date__gte=month_start_datetime,
                        date__lte=end_datetime,
                        is_cancelled=False
                    )
                    
                    sales_by_employee.append({
                        'employee_id': emp.id,
                        'employee_name': emp.username,
                        'employee_email': emp.email,
                        'today': {
                            'count': emp_today_sales.count(),
                            'total': float(emp_today_sales.aggregate(total=Sum('total_price'))['total'] or 0)
                        },
                        'month': {
                            'count': emp_month_sales.count(),
                            'total': float(emp_month_sales.aggregate(total=Sum('total_price'))['total'] or 0)
                        }
                    })
                except User.DoesNotExist:
                    continue
        
        # ============================================
        # 8. ESTADÍSTICAS PERSONALES DEL USUARIO
        # ============================================
        
        # Ventas personales del usuario actual (últimos 30 días)
        user_personal_sales = Sale.objects.filter(
            user=user,
            date__gte=thirty_days_ago,
            is_cancelled=False
        )
        
        personal_stats = {
            'sales_last_30_days': user_personal_sales.count(),
            'total_last_30_days': float(user_personal_sales.aggregate(total=Sum('total_price'))['total'] or 0),
            'average_sale': 0
        }
        
        if personal_stats['sales_last_30_days'] > 0:
            personal_stats['average_sale'] = personal_stats['total_last_30_days'] / personal_stats['sales_last_30_days']
        
        # ============================================
        # 9. VENTAS RECIENTES (Últimas 5 ventas)
        # ============================================
        
        recent_sales = Sale.objects.filter(
            user_id__in=user_ids,
            is_cancelled=False
        ).select_related('user').order_by('-date')[:5]
        
        recent_sales_data = []
        for sale in recent_sales:
            recent_sales_data.append({
                'id': sale.id,
                'date': sale.date.isoformat(),
                'total_price': float(sale.total_price),
                'user': {
                    'id': sale.user.id,
                    'username': sale.user.username
                },
                'items_count': sale.items.count()
            })
        
        # ============================================
        # 10. COMPARACIÓN CON PERÍODO ANTERIOR
        # ============================================
        
        # Ventas del mes anterior
        if start_of_month.month == 1:
            previous_month_start = start_of_month.replace(year=start_of_month.year - 1, month=12, day=1)
        else:
            previous_month_start = start_of_month.replace(month=start_of_month.month - 1, day=1)
        
        # Último día del mes anterior
        previous_month_end = start_of_month - datetime.timedelta(days=1)
        
        previous_month_start_datetime = make_aware(datetime.datetime.combine(previous_month_start, datetime.time.min))
        previous_month_end_datetime = make_aware(datetime.datetime.combine(previous_month_end, datetime.time.max))
        
        previous_month_sales = Sale.objects.filter(
            user_id__in=user_ids,
            date__gte=previous_month_start_datetime,
            date__lte=previous_month_end_datetime,
            is_cancelled=False
        )
        
        previous_month_total = float(previous_month_sales.aggregate(total=Sum('total_price'))['total'] or 0)
        current_month_total = month_sales_data['total']
        
        # Calcular porcentaje de cambio
        if previous_month_total > 0:
            percentage_change = ((current_month_total - previous_month_total) / previous_month_total) * 100
        else:
            percentage_change = 100 if current_month_total > 0 else 0
        
        comparison_data = {
            'current_month_total': current_month_total,
            'previous_month_total': previous_month_total,
            'percentage_change': round(percentage_change, 2),
            'trend': 'up' if percentage_change > 0 else ('down' if percentage_change < 0 else 'stable')
        }
        
        # ============================================
        # CONSTRUIR RESPUESTA FINAL
        # ============================================
        
        response_data = {
            'user_info': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': role_info
            },
            'today_sales': today_sales_data,
            'week_sales': week_sales_data,
            'month_sales': month_sales_data,
            'top_products': top_products_data,
            'low_stock': {
                'count': low_stock_products.count(),
                'products': low_stock_data
            },
            'inventory_summary': inventory_summary,
            'personal_stats': personal_stats,
            'recent_sales': recent_sales_data,
            'comparison': comparison_data,
            'timestamp': now().isoformat()
        }
        
        # Agregar ventas por empleado solo si es admin
        if user.is_admin:
            response_data['sales_by_employee'] = sales_by_employee
        
        return Response(response_data)
    
    @action(detail=False, methods=['get'], url_path='quick-stats')
    def quick_stats(self, request):
        """
        GET /api/dashboard/quick-stats/
        
        Estadísticas rápidas y ligeras para la vista inicial
        Ideal para cargar rápidamente en Flutter
        """
        from django.utils.timezone import now
        import datetime
        
        user = request.user
        today = now().date()
        start_datetime = make_aware(datetime.datetime.combine(today, datetime.time.min))
        end_datetime = make_aware(datetime.datetime.combine(today, datetime.time.max))
        
        # Determinar user_ids según rol
        if user.is_admin:
            employee_ids = list(user.employees.values_list('id', flat=True))
            user_ids = [user.id] + employee_ids
        else:
            user_ids = [user.id]
        
        # Solo 4 datos esenciales
        today_sales = Sale.objects.filter(
            user_id__in=user_ids,
            date__gte=start_datetime,
            date__lte=end_datetime,
            is_cancelled=False
        ).aggregate(
            count=Count('id'),
            total=Sum('total_price')
        )
        
        return Response({
            'today_sales_count': today_sales['count'] or 0,
            'today_sales_total': float(today_sales['total'] or 0),
            'timestamp': now().isoformat()
        })
    
    @action(detail=False, methods=['get'], url_path='sales-chart')
    def sales_chart(self, request):
        """
        GET /api/dashboard/sales-chart/?period=week
        
        Datos para gráficos de ventas
        Parámetros:
        - period: day (últimos 7 días), week (últimas 4 semanas), month (últimos 12 meses)
        """
        from django.utils.timezone import now
        import datetime
        from collections import defaultdict
        
        user = request.user
        period = request.query_params.get('period', 'day')
        
        # Determinar user_ids según rol
        if user.is_admin:
            employee_ids = list(user.employees.values_list('id', flat=True))
            user_ids = [user.id] + employee_ids
        else:
            user_ids = [user.id]
        
        # Determinar rango de fechas
        now_time = now()
        if period == 'day':
            start_date = now_time - datetime.timedelta(days=7)
            date_format = '%Y-%m-%d'
        elif period == 'week':
            start_date = now_time - datetime.timedelta(weeks=4)
            date_format = '%Y-W%U'
        elif period == 'month':
            start_date = now_time - datetime.timedelta(days=365)
            date_format = '%Y-%m'
        else:
            start_date = now_time - datetime.timedelta(days=30)
            date_format = '%Y-%m-%d'
        
        # Obtener ventas
        sales = Sale.objects.filter(
            user_id__in=user_ids,
            date__gte=start_date,
            is_cancelled=False
        ).order_by('date')
        
        # Agrupar por período
        grouped = defaultdict(lambda: {'total': 0, 'count': 0})
        
        for sale in sales:
            key = sale.date.strftime(date_format)
            grouped[key]['total'] += float(sale.total_price)
            grouped[key]['count'] += 1
        
        # Convertir a lista ordenada
        chart_data = [
            {
                'period': k,
                'total': v['total'],
                'count': v['count'],
                'average': v['total'] / v['count'] if v['count'] > 0 else 0
            }
            for k, v in sorted(grouped.items())
        ]
        
        return Response({
            'period_type': period,
            'start_date': start_date.date().isoformat(),
            'data': chart_data
        })
class SystemViewSet(viewsets.ViewSet):
    """ViewSet para operaciones del sistema"""
    permission_classes = [IsAdmin]  # Por defecto admin
    
    @action(detail=False, methods=['post'], url_path='backup')
    def backup(self, request):
        """POST /api/backup/"""
        import subprocess
        import os
        from django.conf import settings
        
        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(backup_dir, f'pos_backup_{timestamp}.sql')
        
        try:
            db_settings = settings.DATABASES['default']
            command = [
                'pg_dump',
                '-h', db_settings['HOST'],
                '-p', str(db_settings['PORT']),
                '-U', db_settings['USER'],
                '-d', db_settings['NAME'],
                '-n', 'pos_system',
                '-f', backup_file
            ]
            
            env = os.environ.copy()
            env['PGPASSWORD'] = db_settings['PASSWORD']
            
            subprocess.run(command, env=env, check=True)
            
            ActivityLog.objects.create(
                user=request.user,
                action='create',
                entity_type='backup',
                entity_id=0,
                details={'file': backup_file}
            )
            
            return Response({
                'message': 'Respaldo creado exitosamente',
                'file': backup_file,
                'timestamp': timestamp
            })
        
        except subprocess.CalledProcessError as e:
            return Response(
                {'error': f'Error al crear respaldo: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'], url_path='health', permission_classes=[])
    def health_check(self, request):
        """GET /api/health/ - Sin autenticación"""
        from django.db import connection
        import os
        from django.conf import settings
        
        status_data = {
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'components': {}
        }
        
        # Verificar base de datos
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            status_data['components']['database'] = 'healthy'
        except Exception as e:
            status_data['status'] = 'unhealthy'
            status_data['components']['database'] = f'error: {str(e)}'
        
        # Verificar directorios media
        media_dirs = ['qr_codes', 'barcodes']
        for dir_name in media_dirs:
            dir_path = os.path.join(settings.MEDIA_ROOT, dir_name)
            if os.path.exists(dir_path) and os.access(dir_path, os.W_OK):
                status_data['components'][f'media_{dir_name}'] = 'healthy'
            else:
                status_data['status'] = 'degraded'
                status_data['components'][f'media_{dir_name}'] = 'not_writable'
        
        http_status = status.HTTP_200_OK if status_data['status'] == 'healthy' else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(status_data, status=http_status)