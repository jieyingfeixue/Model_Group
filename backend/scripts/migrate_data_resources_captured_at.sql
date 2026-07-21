-- 旧库补齐 data_resources.captured_at（与 init_db.sql / ORM 对齐）
-- PowerShell:
--   Get-Content backend\scripts\migrate_data_resources_captured_at.sql -Raw -Encoding UTF8 |
--     docker exec -i pg-local psql -U postgres -d detection_platform

ALTER TABLE data_resources
    ADD COLUMN IF NOT EXISTS captured_at DOUBLE PRECISION;
