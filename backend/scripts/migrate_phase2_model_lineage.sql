-- Phase2 Step1：为已有库补齐模型版本血缘字段
-- 用法（PowerShell）：
--   Get-Content backend\scripts\migrate_phase2_model_lineage.sql -Raw |
--     docker exec -i pg-local psql -U postgres -d detection_platform

ALTER TABLE model_versions
    ADD COLUMN IF NOT EXISTS parent_version_id INTEGER
        REFERENCES model_versions(version_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_mv_parent_version_id
    ON model_versions (parent_version_id);

-- 历史版本：按 version_id 顺序把「上一版」补成父版本（仅当 parent 为空）
UPDATE model_versions AS child
SET parent_version_id = parent.version_id
FROM model_versions AS parent
WHERE child.parent_version_id IS NULL
  AND parent.model_id = child.model_id
  AND parent.version_id = (
      SELECT MAX(v2.version_id)
      FROM model_versions AS v2
      WHERE v2.model_id = child.model_id
        AND v2.version_id < child.version_id
  );
