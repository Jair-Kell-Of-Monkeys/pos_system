"""
Vistas y ViewSets para la API REST
"""
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count
from django.utils import timezone
from django.conf import settings
from django.utils.timezone import make_aware
from datetime import timedelta
from decimal import Decimal

from .models import Role, User, Product, Sale, SaleItem, InventoryMovement, Report
from .serializers import (
    RoleSerializer, UserSerializer, ProductSerializer,
    SaleSerializer, InventoryMovementSerializer, ReportSerializer
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
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


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
        queryset = super().get_queryset()

        # Si NO es admin, solo mostrar sus propios productos
        if not self.request.user.is_admin:
            queryset = queryset.filter(user=self.request.user)
        
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
        
        # Filtrar por rango de fechas
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        # Nuevo: Filtro opcional por usuario específico (solo admin)
        user_id = self.request.query_params.get('user_id', None)
        if user_id and self.request.user.is_admin:
            queryset = queryset.filter(user_id=user_id)
        
        # Empleados solo ven sus propias ventas (a menos que usen my-sales)
        # Admin puede ver todas con /api/sales/ o específicas con ?user_id=X
        if not self.request.user.is_admin and not user_id:
            queryset = queryset.filter(user=self.request.user)
        
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