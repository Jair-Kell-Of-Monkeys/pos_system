-- scripts/update_db.sql
-- Agregar campos necesarios para Django

\c pos_system_db;
SET search_path TO pos_system;

-- Agregar campos para Django User
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_staff BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superuser BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS date_joined TIMESTAMP DEFAULT NOW();
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP NULL;

-- Agregar campos para QR y códigos de barras
ALTER TABLE products ADD COLUMN IF NOT EXISTS qr_code_path VARCHAR(255);
ALTER TABLE products ADD COLUMN IF NOT EXISTS barcode_path VARCHAR(255);

-- Comentarios
COMMENT ON COLUMN users.is_active IS 'Usuario activo en el sistema';
COMMENT ON COLUMN users.is_staff IS 'Acceso al panel de administración';
COMMENT ON COLUMN users.is_superuser IS 'Permisos de superusuario';
COMMENT ON COLUMN products.qr_code_path IS 'Ruta del archivo QR generado';
COMMENT ON COLUMN products.barcode_path IS 'Ruta del código de barras generado';