-- scripts/init_db.sql
-- Script para inicializar la base de datos completa del sistema POS

-- ============================================
-- PASO 1: Crear la base de datos
-- ============================================
-- NOTA: Ejecutar desde el usuario postgres FUERA de cualquier base de datos
-- Comando: psql -U postgres -f scripts/init_db.sql

-- Crear la base de datos si no existe
SELECT 'CREATE DATABASE pos_system_db'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'pos_system_db')\gexec

-- Mensaje de confirmación
\echo 'Base de datos pos_system_db verificada/creada'

-- ============================================
-- PASO 2: Conectarse a la base de datos creada
-- ============================================
\c pos_system_db

\echo 'Conectado a pos_system_db'

-- ============================================
-- PASO 3: Crear esquema pos_system
-- ============================================
CREATE SCHEMA IF NOT EXISTS pos_system;

-- Establecer search_path para esta sesión
SET search_path TO pos_system;

\echo 'Esquema pos_system creado'

-- ============================================
-- PASO 4: Crear tabla roles
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    CONSTRAINT chk_role_name CHECK (name IN ('admin', 'empleado'))
);

\echo 'Tabla roles creada'

-- ============================================
-- PASO 5: Crear tabla users
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role_id INT NOT NULL,
    CONSTRAINT fk_users_role FOREIGN KEY (role_id) 
        REFERENCES pos_system.roles(id) ON DELETE RESTRICT,
    CONSTRAINT chk_username_length CHECK (char_length(username) >= 3),
    CONSTRAINT chk_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

-- Crear índice para búsquedas rápidas
CREATE INDEX IF NOT EXISTS idx_users_username ON pos_system.users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON pos_system.users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON pos_system.users(role_id);

\echo 'Tabla users creada con índices'

-- ============================================
-- PASO 6: Crear tabla products
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.products (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    price DECIMAL(10,2) NOT NULL CHECK (price >= 0),
    stock INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
    code VARCHAR(100) UNIQUE,
    CONSTRAINT fk_products_user FOREIGN KEY (user_id) 
        REFERENCES pos_system.users(id) ON DELETE CASCADE,
    CONSTRAINT chk_product_name_length CHECK (char_length(name) >= 2)
);

-- Crear índices para búsquedas y reportes
CREATE INDEX IF NOT EXISTS idx_products_user ON pos_system.products(user_id);
CREATE INDEX IF NOT EXISTS idx_products_code ON pos_system.products(code);
CREATE INDEX IF NOT EXISTS idx_products_category ON pos_system.products(category);
CREATE INDEX IF NOT EXISTS idx_products_name ON pos_system.products(name);

\echo 'Tabla products creada con índices'

-- ============================================
-- PASO 7: Crear tabla sales
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.sales (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    date TIMESTAMP NOT NULL DEFAULT NOW(),
    total_price DECIMAL(10,2) NOT NULL CHECK (total_price >= 0),
    CONSTRAINT fk_sales_user FOREIGN KEY (user_id) 
        REFERENCES pos_system.users(id) ON DELETE CASCADE
);

-- Crear índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_sales_user_date ON pos_system.sales(user_id, date);
CREATE INDEX IF NOT EXISTS idx_sales_date ON pos_system.sales(date DESC);

\echo 'Tabla sales creada con índices'

-- ============================================
-- PASO 8: Crear tabla sale_items
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.sale_items (
    id SERIAL PRIMARY KEY,
    sale_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    price_unit DECIMAL(10,2) NOT NULL CHECK (price_unit >= 0),
    subtotal DECIMAL(10,2) NOT NULL CHECK (subtotal >= 0),
    CONSTRAINT fk_sale_items_sale FOREIGN KEY (sale_id) 
        REFERENCES pos_system.sales(id) ON DELETE CASCADE,
    CONSTRAINT fk_sale_items_product FOREIGN KEY (product_id) 
        REFERENCES pos_system.products(id) ON DELETE CASCADE,
    CONSTRAINT chk_subtotal_calculation CHECK (subtotal = price_unit * quantity)
);

-- Crear índices para joins frecuentes
CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON pos_system.sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_product ON pos_system.sale_items(product_id);

\echo 'Tabla sale_items creada con índices'

-- ============================================
-- PASO 9: Crear tabla inventory_movements
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.inventory_movements (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL,
    movement_type VARCHAR(20) NOT NULL CHECK (movement_type IN ('entrada', 'salida')),
    quantity INT NOT NULL CHECK (quantity > 0),
    date TIMESTAMP NOT NULL DEFAULT NOW(),
    note TEXT,
    CONSTRAINT fk_inventory_movements_product FOREIGN KEY (product_id) 
        REFERENCES pos_system.products(id) ON DELETE CASCADE
);

-- Crear índices para consultas de historial
CREATE INDEX IF NOT EXISTS idx_inventory_product_date ON pos_system.inventory_movements(product_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_date ON pos_system.inventory_movements(date DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_type ON pos_system.inventory_movements(movement_type);

\echo 'Tabla inventory_movements creada con índices'

-- ============================================
-- PASO 10: Crear tabla reports
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.reports (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    type VARCHAR(50) NOT NULL,
    generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    data JSONB NOT NULL,
    CONSTRAINT fk_reports_user FOREIGN KEY (user_id) 
        REFERENCES pos_system.users(id) ON DELETE CASCADE,
    CONSTRAINT chk_report_type CHECK (type IN ('ventas', 'inventario', 'productos', 'general'))
);

-- Crear índices para consultas de reportes
CREATE INDEX IF NOT EXISTS idx_reports_user ON pos_system.reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_type ON pos_system.reports(type);
CREATE INDEX IF NOT EXISTS idx_reports_date ON pos_system.reports(generated_at DESC);

-- Índice GIN para búsquedas en JSONB
CREATE INDEX IF NOT EXISTS idx_reports_data ON pos_system.reports USING GIN (data);

\echo 'Tabla reports creada con índices'

-- ============================================
-- PASO 11: Insertar datos iniciales - Roles
-- ============================================
INSERT INTO pos_system.roles (name, description) VALUES
    ('admin', 'Administrador con control total del sistema')
ON CONFLICT (name) DO NOTHING;

INSERT INTO pos_system.roles (name, description) VALUES
    ('empleado', 'Usuario con permisos de ventas e inventario')
ON CONFLICT (name) DO NOTHING;

\echo 'Roles iniciales insertados (admin, empleado)'

-- ============================================
-- PASO 12: Crear vistas útiles (OPCIONAL)
-- ============================================

-- Vista: Productos con bajo stock
CREATE OR REPLACE VIEW pos_system.v_productos_bajo_stock AS
SELECT 
    p.id,
    p.name,
    p.code,
    p.category,
    p.stock,
    p.price,
    u.username as propietario
FROM pos_system.products p
INNER JOIN pos_system.users u ON p.user_id = u.id
WHERE p.stock <= 10
ORDER BY p.stock ASC;

\echo 'Vista v_productos_bajo_stock creada'

-- Vista: Resumen de ventas por día
CREATE OR REPLACE VIEW pos_system.v_ventas_diarias AS
SELECT 
    DATE(s.date) as fecha,
    COUNT(s.id) as cantidad_ventas,
    SUM(s.total_price) as total_vendido,
    AVG(s.total_price) as promedio_venta
FROM pos_system.sales s
GROUP BY DATE(s.date)
ORDER BY fecha DESC;

\echo 'Vista v_ventas_diarias creada'

-- Vista: Productos más vendidos
CREATE OR REPLACE VIEW pos_system.v_productos_mas_vendidos AS
SELECT 
    p.id,
    p.name,
    p.code,
    p.category,
    SUM(si.quantity) as total_vendido,
    SUM(si.subtotal) as ingresos_totales,
    COUNT(DISTINCT si.sale_id) as numero_ventas
FROM pos_system.products p
INNER JOIN pos_system.sale_items si ON p.id = si.product_id
GROUP BY p.id, p.name, p.code, p.category
ORDER BY total_vendido DESC;

\echo 'Vista v_productos_mas_vendidos creada'

-- ============================================
-- PASO 13: Configurar permisos (OPCIONAL)
-- ============================================
-- Descomentar si necesitas configurar permisos para un usuario específico

-- GRANT ALL PRIVILEGES ON SCHEMA pos_system TO tu_usuario;
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA pos_system TO tu_usuario;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA pos_system TO tu_usuario;

-- ============================================
-- PASO 14: Resumen de la instalación
-- ============================================
\echo ''
\echo '=========================================='
\echo 'INSTALACIÓN COMPLETADA EXITOSAMENTE'
\echo '=========================================='
\echo ''
\echo 'Base de datos: pos_system_db'
\echo 'Esquema: pos_system'
\echo ''
\echo 'Tablas creadas:'
\echo '   1. roles (2 registros: admin, empleado)'
\echo '   2. users'
\echo '   3. products'
\echo '   4. sales'
\echo '   5. sale_items'
\echo '   6. inventory_movements'
\echo '   7. reports'
\echo ''
\echo 'Vistas creadas:'
\echo '   1. v_productos_bajo_stock'
\echo '   2. v_ventas_diarias'
\echo '   3. v_productos_mas_vendidos'
\echo ''
\echo 'Roles disponibles:'
\echo '   - admin: Control total del sistema'
\echo '   - empleado: Ventas e inventario'
\echo ''
\echo 'Próximos pasos:'
\echo '   1. Ejecutar: psql -U postgres -d pos_system_db -f scripts/update_db.sql'
\echo '   2. Configurar Django y ejecutar migraciones'
\echo '   3. Crear superusuario con: python manage.py setup_db'
\echo ''
\echo '=========================================='

-- ============================================
-- PASO 15: Verificar la instalación
-- ============================================
\echo ''
\echo 'Verificando instalación...'
\echo ''

-- Mostrar tablas creadas
\dt pos_system.*

\echo ''
\echo 'Conteo de registros iniciales:'

-- Contar roles
SELECT 'Roles: ' || COUNT(*) as info FROM pos_system.roles;

\echo ''
\echo 'Script completado. Base de datos lista para usar.'