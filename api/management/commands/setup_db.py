# api/management/commands/setup_db.py
# pylint: disable=no-member
"""
Comando para configurar la base de datos y crear superusuario
"""
from django.core.management.base import BaseCommand
from api.models import Role, User


class Command(BaseCommand):
    help = 'Configura la base de datos y crea el superusuario inicial'
    
    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('\n Configurando base de datos...\n'))
        
        # Verificar que los roles existan
        try:
            admin_role = Role.objects.get(name='admin')
            Role.objects.get(name='empleado')  # Verificar que existe
            self.stdout.write(self.style.SUCCESS('BIEN Roles encontrados en la base de datos'))
        except Role.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                'QUE MAL Error: Los roles no existen. Ejecuta primero init_db.sql'
            ))
            return
        
        # Crear superusuario si no existe
        if not User.objects.filter(username='admin').exists():
            try:
                admin = User.objects.create_superuser(
                    username='admin',
                    email='admin@pos.com',
                    password='admin123',
                    role=admin_role
                )
                self.stdout.write(self.style.SUCCESS(
                    f'BIEN Superusuario creado: {admin.username}'
                ))
                self.stdout.write(self.style.WARNING(
                    '   Usuario: admin'
                ))
                self.stdout.write(self.style.WARNING(
                    '   Contraseña: admin123'
                ))
                self.stdout.write(self.style.WARNING(
                    '   OH NO  Cambia la contraseña en producción!'
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'QUE MAL Error creando superusuario: {e}'))
        else:
            self.stdout.write(self.style.WARNING('OH NO  El superusuario "admin" ya existe'))
        
        self.stdout.write(self.style.SUCCESS('\n BIEN Configuración completada\n'))