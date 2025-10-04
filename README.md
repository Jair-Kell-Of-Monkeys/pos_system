# Sistema POS - Guía de Instalación

## Requisitos previos

- Python 3.8 o superior
- PostgreSQL 12 o superior
- Git

## Instalación paso a paso

### 1. Clonar el repositorio

```bash
git clone <url-del-repositorio>
cd pos-system
```

### 2. Instalar PostgreSQL

**Windows:**
- Descargar de: https://www.postgresql.org/download/windows/
- Durante la instalación, recordar la contraseña del usuario `postgres`

**macOS:**
```bash
brew install postgresql@14
brew services start postgresql@14
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

### 3. Crear la base de datos

```bash
# Conectarse a PostgreSQL
psql -U postgres

# Dentro de psql, ejecutar:
CREATE DATABASE pos_system_db;
\q
```

### 4. Ejecutar el script de inicialización

```bash
psql -U postgres -d pos_system_db -f scripts/init_db.sql
```

Deberías ver mensajes de confirmación para cada tabla creada.

### 5. Configurar variables de entorno

```bash
# Copiar el archivo de ejemplo
cp .env.example .env

# Editar .env con tus credenciales
# Cambiar DB_PASSWORD por tu contraseña de PostgreSQL
```

Tu `.env` debe verse así:

```properties
SECRET_KEY=tu_secret_key_aqui
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,10.0.2.2

DB_NAME=pos_system_db
DB_USER=postgres
DB_PASSWORD=TU_CONTRASEÑA_POSTGRES
DB_HOST=localhost
DB_PORT=5432

CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000,http://10.0.2.2:8000
```

### 6. Crear entorno virtual e instalar dependencias

```bash
# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 7. Ejecutar migraciones de Django

```bash
# Esto sincroniza Django con la BD que ya creaste
python manage.py migrate --fake-initial
```

### 8. Crear superusuario (admin)

```bash
python manage.py createsuperuser
```

Ingresa:
- Username: admin (o el que prefieras)
- Email: tu@email.com
- Password: (contraseña segura)

### 9. Iniciar el servidor

```bash
python manage.py runserver 0.0.0.0:8000
```

### 10. Verificar instalación

Abre tu navegador en: http://localhost:8000/api/health/

Deberías ver:
```json
{
  "status": "healthy",
  "timestamp": "...",
  "components": {...}
}
```

## URLs para desarrollo

### React (frontend web)
```javascript
// src/services/api.js
const API_URL = 'http://localhost:8000/api';
```

### Flutter (frontend móvil)
```dart
// lib/services/api_service.dart
static const String baseUrl = 'http://10.0.2.2:8000/api';
```

## Endpoints principales

### Autenticación
```
POST /api/auth/login/      - Login
POST /api/auth/refresh/    - Refresh token
```

### Productos
```
GET  /api/products/        - Listar productos
POST /api/products/        - Crear producto
```

### Ventas
```
GET  /api/sales/           - Listar ventas
POST /api/sales/           - Crear venta
```

### Dashboard
```
GET  /api/dashboard/summary/  - Resumen general
```

## Solución de problemas comunes

### Error: "role 'postgres' does not exist"
```bash
# Crear el rol postgres
createuser -s postgres
```

### Error: "database 'pos_system_db' does not exist"
```bash
# Crear la base de datos manualmente
psql -U postgres -c "CREATE DATABASE pos_system_db;"
```

### Error: "password authentication failed"
- Verifica que la contraseña en `.env` sea correcta
- En PostgreSQL 14+, puede que necesites configurar `pg_hba.conf`

### Error: "No module named 'psycopg2'"
```bash
pip install psycopg2-binary
```

## Estructura del proyecto

```
pos-system/
├── backend/
│   ├── settings.py      # Configuración Django
│   ├── urls.py          # URLs principales
│   └── wsgi.py
├── api/
│   ├── models.py        # Modelos de datos
│   ├── views.py         # Lógica de endpoints
│   ├── serializers.py   # Serialización
│   └── urls.py          # URLs de la API
├── scripts/
│   └── init_db.sql      # Script de inicialización
├── .env.example         # Plantilla de variables
├── requirements.txt     # Dependencias Python
└── README.md            # Este archivo
```

## Comandos útiles

```bash
# Ver tablas en PostgreSQL
psql -U postgres -d pos_system_db -c "\dt pos_system.*"

# Reiniciar base de datos (¡CUIDADO! Borra todo)
psql -U postgres -c "DROP DATABASE pos_system_db;"
psql -U postgres -c "CREATE DATABASE pos_system_db;"
psql -U postgres -d pos_system_db -f scripts/init_db.sql

# Ver logs del servidor
python manage.py runserver 0.0.0.0:8000 --verbosity 2
```

## Contacto

Si tienes problemas con la instalación, contacta al equipo en [canal de comunicación].