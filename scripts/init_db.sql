-- scripts/init_db.sql
-- Script completo para inicializar la base de datos del Sistema POS
-- Incluye todas las modificaciones realizadas durante el desarrollo

-- ============================================
-- INSTRUCCIONES DE USO
-- ============================================
-- PASO 1: Crear la base de datos (ejecutar desde psql como postgres)
--   psql -U postgres
--   CREATE DATABASE pos_system_db;
--   \q
--
-- PASO 2: Ejecutar este script
--   psql -U postgres -d pos_system_db -f scripts/init_db.sql
--
-- ALTERNATIVA: Ejecutar todo en una línea
--   psql -U postgres -c "CREATE DATABASE pos_system_db;" && psql -U postgres -d pos_system_db -f scripts/init_db.sql
-- ============================================

\echo '============================================'
\echo 'Iniciando configuración de base de datos...'
\echo '============================================'
\echo ''

-- ============================================
-- PASO 1: Crear esquema
-- ============================================
CREATE SCHEMA IF NOT EXISTS pos_system;
SET search_path TO pos_system;

\echo '✓ Esquema pos_system creado'

-- ============================================
-- PASO 2: Crear tabla roles
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    CONSTRAINT chk_role_name CHECK (name IN ('admin', 'empleado'))
);

\echo '✓ Tabla roles creada'

-- ============================================
-- PASO 3: Crear tabla users
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role_id INT NOT NULL,
    manager_id INT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_staff BOOLEAN DEFAULT FALSE,
    is_superuser BOOLEAN DEFAULT FALSE,
    date_joined TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP NULL,
    CONSTRAINT fk_users_role FOREIGN KEY (role_id) 
        REFERENCES pos_system.roles(id) ON DELETE RESTRICT,
    CONSTRAINT fk_users_manager FOREIGN KEY (manager_id) 
        REFERENCES pos_system.users(id) ON DELETE SET NULL,
    CONSTRAINT chk_username_length CHECK (char_length(username) >= 3),
    CONSTRAINT chk_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE INDEX IF NOT EXISTS idx_users_username ON pos_system.users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON pos_system.users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON pos_system.users(role_id);
CREATE INDEX IF NOT EXISTS idx_users_manager ON pos_system.users(manager_id);

\echo '✓ Tabla users creada con índices'

-- ============================================
-- PASO 4: Crear tabla products
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.products (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    price DECIMAL(10,2) NOT NULL CHECK (price >= 0),
    stock INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
    code VARCHAR(100) UNIQUE,
    qr_code_path VARCHAR(255),
    barcode_path VARCHAR(255),
    CONSTRAINT fk_products_user FOREIGN KEY (user_id) 
        REFERENCES pos_system.users(id) ON DELETE CASCADE,
    CONSTRAINT chk_product_name_length CHECK (char_length(name) >= 2)
);

CREATE INDEX IF NOT EXISTS idx_products_user ON pos_system.products(user_id);
CREATE INDEX IF NOT EXISTS idx_products_code ON pos_system.products(code);
CREATE INDEX IF NOT EXISTS idx_products_category ON pos_system.products(category);
CREATE INDEX IF NOT EXISTS idx_products_name ON pos_system.products(name);

\echo '✓ Tabla products creada con índices'

-- ============================================
-- PASO 5: Crear tabla sales
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.sales (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    date TIMESTAMP NOT NULL DEFAULT NOW(),
    total_price DECIMAL(10,2) NOT NULL CHECK (total_price >= 0),
    is_cancelled BOOLEAN DEFAULT FALSE,
    cancelled_at TIMESTAMP NULL,
    cancelled_by_id INT NULL,
    CONSTRAINT fk_sales_user FOREIGN KEY (user_id) 
        REFERENCES pos_system.users(id) ON DELETE CASCADE,
    CONSTRAINT fk_sales_cancelled_by FOREIGN KEY (cancelled_by_id) 
        REFERENCES pos_system.users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_user_date ON pos_system.sales(user_id, date);
CREATE INDEX IF NOT EXISTS idx_sales_date ON pos_system.sales(date DESC);
CREATE INDEX IF NOT EXISTS idx_sales_cancelled ON pos_system.sales(is_cancelled);

\echo '✓ Tabla sales creada con índices'

-- ============================================
-- PASO 6: Crear tabla sale_items
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

CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON pos_system.sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_product ON pos_system.sale_items(product_id);

\echo '✓ Tabla sale_items creada con índices'

-- ============================================
-- PASO 7: Crear tabla inventory_movements
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

CREATE INDEX IF NOT EXISTS idx_inventory_product_date ON pos_system.inventory_movements(product_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_date ON pos_system.inventory_movements(date DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_type ON pos_system.inventory_movements(movement_type);

\echo '✓ Tabla inventory_movements creada con índices'

-- ============================================
-- PASO 8: Crear tabla reports
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

CREATE INDEX IF NOT EXISTS idx_reports_user ON pos_system.reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_type ON pos_system.reports(type);
CREATE INDEX IF NOT EXISTS idx_reports_date ON pos_system.reports(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_data ON pos_system.reports USING GIN (data);

\echo '✓ Tabla reports creada con índices'

-- ============================================
-- PASO 9: Crear tabla activity_logs
-- ============================================
CREATE TABLE IF NOT EXISTS pos_system.activity_logs (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    action VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INT NOT NULL,
    details JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_activity_logs_user FOREIGN KEY (user_id) 
        REFERENCES pos_system.users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_activity_logs_user ON pos_system.activity_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_created ON pos_system.activity_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_logs_entity ON pos_system.activity_logs(entity_type, entity_id);

\echo '✓ Tabla activity_logs creada con índices'

-- ============================================
-- PASO 10: Insertar datos iniciales - Roles
-- ============================================
INSERT INTO pos_system.roles (name, description) VALUES
    ('admin', 'Administrador con control total del sistema')
ON CONFLICT (name) DO NOTHING;

INSERT INTO pos_system.roles (name, description) VALUES
    ('empleado', 'Usuario con permisos de ventas e inventario')
ON CONFLICT (name) DO NOTHING;

\echo '✓ Roles iniciales insertados (admin, empleado)'

-- ============================================
-- PASO 11: Crear vistas útiles
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

-- Vista: Resumen de ventas por día
CREATE OR REPLACE VIEW pos_system.v_ventas_diarias AS
SELECT 
    DATE(s.date) as fecha,
    COUNT(s.id) as cantidad_ventas,
    SUM(s.total_price) as total_vendido,
    AVG(s.total_price) as promedio_venta,
    COUNT(CASE WHEN s.is_cancelled = true THEN 1 END) as ventas_canceladas
FROM pos_system.sales s
GROUP BY DATE(s.date)
ORDER BY fecha DESC;

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
INNER JOIN pos_system.sales s ON si.sale_id = s.id
WHERE s.is_cancelled = false
GROUP BY p.id, p.name, p.code, p.category
ORDER BY total_vendido DESC;

-- Vista: Actividad reciente de usuarios
CREATE OR REPLACE VIEW pos_system.v_actividad_usuarios AS
SELECT 
    u.id as user_id,
    u.username,
    r.name as rol,
    COUNT(DISTINCT s.id) as total_ventas,
    COALESCE(SUM(s.total_price), 0) as monto_total_ventas,
    COUNT(DISTINCT al.id) as total_acciones,
    MAX(al.created_at) as ultima_actividad
FROM pos_system.users u
LEFT JOIN pos_system.roles r ON u.role_id = r.id
LEFT JOIN pos_system.sales s ON u.id = s.user_id AND s.is_cancelled = false
LEFT JOIN pos_system.activity_logs al ON u.id = al.user_id
GROUP BY u.id, u.username, r.name
ORDER BY ultima_actividad DESC NULLS LAST;

\echo '✓ Vistas creadas'

-- ============================================
-- PASO 12: Comentarios en tablas
-- ============================================
COMMENT ON TABLE pos_system.roles IS 'Roles del sistema (admin, empleado)';
COMMENT ON TABLE pos_system.users IS 'Usuarios del sistema con jerarquía admin-empleado';
COMMENT ON TABLE pos_system.products IS 'Productos del inventario con QR y códigos de barras';
COMMENT ON TABLE pos_system.sales IS 'Ventas realizadas con opción de cancelación';
COMMENT ON TABLE pos_system.sale_items IS 'Detalles de items vendidos en cada venta';
COMMENT ON TABLE pos_system.inventory_movements IS 'Historial de movimientos de inventario';
COMMENT ON TABLE pos_system.reports IS 'Reportes generados por el sistema';
COMMENT ON TABLE pos_system.activity_logs IS 'Registro de actividad de usuarios para auditoría';

COMMENT ON COLUMN pos_system.users.manager_id IS 'ID del admin que gestiona a este empleado';
COMMENT ON COLUMN pos_system.products.qr_code_path IS 'Ruta del archivo QR generado';
COMMENT ON COLUMN pos_system.products.barcode_path IS 'Ruta del código de barras generado';
COMMENT ON COLUMN pos_system.sales.is_cancelled IS 'Indica si la venta fue cancelada';
COMMENT ON COLUMN pos_system.sales.cancelled_by_id IS 'Usuario que canceló la venta';

\echo '✓ Comentarios agregados'

-- ============================================
-- RESUMEN DE LA INSTALACIÓN
-- ============================================
\echo ''
\echo '=========================================='
\echo '✓ INSTALACIÓN COMPLETADA EXITOSAMENTE'
\echo '=========================================='
\echo ''
\echo 'Base de datos: pos_system_db'
\echo 'Esquema: pos_system'
\echo ''
\echo 'Tablas creadas:'
\echo '  1. roles (2 registros)'
\echo '  2. users'
\echo '  3. products'
\echo '  4. sales'
\echo '  5. sale_items'
\echo '  6. inventory_movements'
\echo '  7. reports'
\echo '  8. activity_logs'
\echo ''
\echo 'Vistas creadas:'
\echo '  1. v_productos_bajo_stock'
\echo '  2. v_ventas_diarias'
\echo '  3. v_productos_mas_vendidos'
\echo '  4. v_actividad_usuarios'
\echo ''
\echo 'Próximos pasos:'
\echo '  1. Copiar .env.example a .env'
\echo '  2. Configurar credenciales en .env'
\echo '  3. pip install -r requirements.txt'
\echo '  4. python manage.py migrate --fake-initial'
\echo '  5. python manage.py createsuperuser (o usar setup_db)'
\echo '  6. python manage.py runserver 0.0.0.0:8000'
\echo ''
\echo '=========================================='

-- ============================================
-- PASO 16: Verificación
-- ============================================
\echo ''
\echo '🔍 Verificando instalación...'
\echo ''

\dt pos_system.*

\echo ''
\echo '📊 Conteo de registros iniciales:'

SELECT 'Roles: ' || COUNT(*) as info FROM pos_system.roles;

\echo ''
\echo '✅ Script completado. Base de datos lista para usar.'
\echo 'Ejecuta: python manage.py setup_db para crear el superusuario admin.'