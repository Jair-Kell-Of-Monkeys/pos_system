# api/apps.py
from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'
    verbose_name = 'API POS'
    
    def ready(self):
        # Importar señales
        import api.signals