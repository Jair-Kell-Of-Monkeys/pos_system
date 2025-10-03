# api/serializers.py
"""
Serializadores para la API REST
"""
from rest_framework import serializers
from .models import Role, User, Product, Sale, SaleItem, InventoryMovement, Report, ActivityLog
from django.db import transaction
from decimal import Decimal


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'name', 'description']
        read_only_fields = ['id']


class UserSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.name', read_only=True)
    manager_name = serializers.CharField(source='manager.username', read_only=True)
    password = serializers.CharField(write_only=True, required=False)
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'role_name',
            'manager', 'manager_name', 'password', 'is_active', 'date_joined'
        ]
        read_only_fields = ['id', 'date_joined']
        extra_kwargs = {
            'password': {'write_only': True}
        }
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)

        request_user = self.context['request'].user
        if request_user.is_admin and validated_data.get('role').name == 'empleado':
            validated_data['manager'] = request_user

        user = User(**validated_data)
        if password:
            user.set_password(password)
        user.save()
        return user
    
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class ProductSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    qr_code_url = serializers.SerializerMethodField()
    barcode_url = serializers.SerializerMethodField()
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = Product
        fields = [
            'id', 'user', 'user_name', 'name', 'category', 
            'price', 'stock', 'code', 'qr_code_url', 'barcode_url'
        ]
        read_only_fields = ['id', 'code', 'user', 'user_name']  # Hacer 'code' de solo lectura
    
    def get_qr_code_url(self, obj):
        if obj.qr_code_path:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(f'/media/{obj.qr_code_path}')
        return None
    
    def get_barcode_url(self, obj):
        if obj.barcode_path:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(f'/media/{obj.barcode_path}')
        return None
    
    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("El precio no puede ser negativo")
        return value
    
    def validate_stock(self, value):
        if value < 0:
            raise serializers.ValidationError("El stock no puede ser negativo")
        return value
    
    def create(self, validated_data):
        # Asignar usuario actual si no se proporciona
        if 'user' not in validated_data:
            validated_data['user'] = self.context['request'].user
        
        # Generar código automáticamente
        validated_data['code'] = self._generate_product_code(validated_data)
        
        product = Product(**validated_data)
        product.save()
        return product
    
    def _generate_product_code(self, data):
        """
        Genera un código único basado en nombre y categoría
        Formato: CAT-NAME-ID (ej: ELEC-LAPTOP-001)
        """
        import re
        from django.utils.text import slugify
        
        # Obtener categoría (primeras 4 letras en mayúsculas)
        category = data.get('category', 'GEN')
        category_code = re.sub(r'[^A-Za-z]', '', category)[:4].upper()
        if not category_code:
            category_code = 'GEN'
        
        # Obtener nombre (primeras 2 palabras)
        name = data.get('name', 'PRODUCT')
        name_parts = name.split()[:2]
        name_code = '-'.join([re.sub(r'[^A-Za-z]', '', part)[:4].upper() for part in name_parts])
        if not name_code:
            name_code = 'PROD'
        
        # Obtener siguiente número secuencial
        last_product = Product.objects.filter(
            code__startswith=f"{category_code}-{name_code}"
        ).order_by('-id').first()
        
        if last_product and last_product.code:
            # Extraer número del último código
            try:
                last_num = int(last_product.code.split('-')[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1
        
        # Generar código final
        code = f"{category_code}-{name_code}-{next_num:03d}"
        
        # Verificar que sea único
        while Product.objects.filter(code=code).exists():
            next_num += 1
            code = f"{category_code}-{name_code}-{next_num:03d}"
        
        return code

class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    
    class Meta:
        model = SaleItem
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'quantity', 'price_unit', 'subtotal'
        ]
        read_only_fields = ['id', 'price_unit', 'subtotal']
    
    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a 0")
        return value


class SaleSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True)
    user_name = serializers.CharField(source='user.username', read_only=True)
    cancelled_by_name = serializers.CharField(source='cancelled_by.username', read_only=True)
    
    class Meta:
        model = Sale
        fields = [
            'id', 'user', 'user_name', 'date', 'total_price', 'items',
            'is_cancelled', 'cancelled_at', 'cancelled_by', 'cancelled_by_name'
        ]
        read_only_fields = ['id', 'user', 'date', 'total_price', 'is_cancelled', 'cancelled_at', 'cancelled_by']
    
    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("La venta debe tener al menos un item")
        return value
    
    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        user = self.context['request'].user
        
        # Calcular total y validar stock
        total_price = Decimal('0.00')
        sale_items = []
        
        for item_data in items_data:
            product = item_data['product']
            quantity = item_data['quantity']
            
            # Validar stock disponible
            if product.stock < quantity:
                raise serializers.ValidationError(
                    f"Stock insuficiente para {product.name}. "
                    f"Disponible: {product.stock}, Solicitado: {quantity}"
                )
            
            # Calcular subtotal
            price_unit = product.price
            subtotal = price_unit * quantity
            total_price += subtotal
            
            sale_items.append({
                'product': product,
                'quantity': quantity,
                'price_unit': price_unit,
                'subtotal': subtotal
            })
        
        # Crear la venta
        sale = Sale(user=user, total_price=total_price)
        sale.save()
        
        # Crear items y actualizar inventario
        for item_info in sale_items:
            product = item_info['product']
            quantity = item_info['quantity']
            
            # Crear SaleItem
            sale_item = SaleItem(
                sale=sale,
                product=product,
                quantity=quantity,
                price_unit=item_info['price_unit'],
                subtotal=item_info['subtotal']
            )
            sale_item.save()
            
            # Descontar stock
            product.stock -= quantity
            product.save()
            
            # Crear movimiento de inventario (salida)
            movement = InventoryMovement(
                product=product,
                movement_type='salida',
                quantity=quantity,
                note=f"Venta #{sale.pk}"
            )
            movement.save()
        
        return sale


class InventoryMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    
    class Meta:
        model = InventoryMovement
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'movement_type', 'movement_type_display', 'quantity',
            'date', 'note'
        ]
        read_only_fields = ['id', 'date']
    
    @transaction.atomic
    def create(self, validated_data):
        product = validated_data['product']
        quantity = validated_data['quantity']
        movement_type = validated_data['movement_type']
        
        # Actualizar stock según tipo de movimiento
        if movement_type == 'entrada':
            product.stock += quantity
        elif movement_type == 'salida':
            if product.stock < quantity:
                raise serializers.ValidationError(
                    f"Stock insuficiente. Disponible: {product.stock}, Solicitado: {quantity}"
                )
            product.stock -= quantity
        
        product.save()
        
        # Crear el movimiento
        movement = InventoryMovement(**validated_data)
        movement.save()
        return movement


class ReportSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = Report
        fields = [
            'id', 'user', 'user_name', 'type', 
            'generated_at', 'data'
        ]
        read_only_fields = ['id', 'user', 'generated_at']
    
    def create(self, validated_data):
        user = self.context['request'].user
        report = Report(user=user, **validated_data)
        report.save()
        return report
    
class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = ActivityLog
        fields = ['id', 'user', 'user_name', 'action', 'entity_type', 'entity_id', 'details', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class UserActivitySerializer(serializers.Serializer):
    """
    Serializer para historial de actividad de usuario
    """
    sales_count = serializers.IntegerField()
    total_sales_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    products_created = serializers.IntegerField()
    recent_sales = SaleSerializer(many=True)
    recent_activity = ActivityLogSerializer(many=True)


class StockAdjustmentSerializer(serializers.Serializer):
    """
    Serializer para ajuste manual de stock
    """
    adjustment = serializers.IntegerField(required=True, help_text="Cantidad a ajustar (positivo o negativo)")
    reason = serializers.CharField(required=True, max_length=255, help_text="Motivo del ajuste")
    
    def validate_adjustment(self, value):
        if value == 0:
            raise serializers.ValidationError("El ajuste no puede ser 0")
        return value


class DashboardSummarySerializer(serializers.Serializer):
    """
    Serializer para resumen del dashboard
    """
    today_sales = serializers.DictField()
    top_product = serializers.DictField()
    low_stock_count = serializers.IntegerField()
    low_stock_products = serializers.ListField()
    sales_by_employee = serializers.ListField()
    total_inventory_value = serializers.DecimalField(max_digits=12, decimal_places=2)