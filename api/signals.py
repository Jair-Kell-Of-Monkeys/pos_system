# api/signals.py
"""
Señales para generar QR y código de barras automáticamente
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import Product
import qrcode
import barcode
from barcode.writer import ImageWriter
import os


@receiver(post_save, sender=Product)
def generate_product_codes(sender, instance, created, **kwargs):
    """
    Genera código QR y código de barras para el producto
    """
    # Evitar recursión infinita
    if kwargs.get('raw', False):
        return
    
    # Solo generar si el producto tiene un código
    if not instance.code:
        return
    
    updated = False
    
    # Directorios para guardar archivos
    qr_dir = os.path.join(settings.MEDIA_ROOT, 'qr_codes')
    barcode_dir = os.path.join(settings.MEDIA_ROOT, 'barcodes')
    
    # Crear directorios si no existen
    os.makedirs(qr_dir, exist_ok=True)
    os.makedirs(barcode_dir, exist_ok=True)
    
    # Generar código QR si no existe
    if not instance.qr_code_path:
        try:
            qr_data = f"Product:{instance.id}|Code:{instance.code}|Name:{instance.name}|Price:{instance.price}"
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Guardar archivo
            filename = f"qr_{instance.code}.png"
            filepath = os.path.join(qr_dir, filename)
            img.save(filepath)
            
            # Guardar ruta relativa
            instance.qr_code_path = f"qr_codes/{filename}"
            updated = True
        except Exception as e:
            print(f"Error generando código QR: {e}")
    
    # Generar código de barras si no existe
    if not instance.barcode_path:
        try:
            # Limpiar código para barcode (solo alfanuméricos)
            clean_code = ''.join(c for c in instance.code if c.isalnum())
            
            if clean_code:
                CODE128 = barcode.get_barcode_class('code128')
                code128 = CODE128(clean_code, writer=ImageWriter())
                
                # Guardar archivo
                filename = f"barcode_{instance.code}"
                filepath = os.path.join(barcode_dir, filename)
                code128.save(filepath)  # Se agrega .png automáticamente
                
                # Guardar ruta relativa
                instance.barcode_path = f"barcodes/{filename}.png"
                updated = True
        except Exception as e:
            print(f"Error generando código de barras: {e}")
    
    # Guardar solo si hubo cambios
    if updated:
        # Usar queryset.update para evitar recursión
        Product.objects.filter(pk=instance.pk).update(
            qr_code_path=instance.qr_code_path,
            barcode_path=instance.barcode_path
        )