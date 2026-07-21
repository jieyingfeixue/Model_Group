-- Phase2 Step1：种子基线模型（可重复执行）
-- 类别名使用 ASCII，避免 PowerShell Get-Content 管道破坏 UTF-8 中文。
-- 用法：
--   Get-Content backend\scripts\seed_baseline_models.sql -Raw -Encoding UTF8 |
--     docker exec -i pg-local psql -U postgres -d detection_platform

INSERT INTO models (
    name, owner_id, framework, file_path, metadata,
    is_baseline, is_public, status
)
SELECT
    'baseline-yolo-visible',
    NULL,
    'onnx',
    'baselines/yolo-visible/v1.0.0/placeholder.onnx',
    '{"input_size":[640,640],"modalities":["visible"],"categories":["pole","bridge"],"note":"platform baseline placeholder"}'::jsonb,
    true,
    true,
    'available'
WHERE NOT EXISTS (
    SELECT 1 FROM models WHERE name = 'baseline-yolo-visible' AND is_baseline = true
);

INSERT INTO models (
    name, owner_id, framework, file_path, metadata,
    is_baseline, is_public, status
)
SELECT
    'baseline-yolo-infrared',
    NULL,
    'onnx',
    'baselines/yolo-infrared/v1.0.0/placeholder.onnx',
    '{"input_size":[640,640],"modalities":["infrared"],"categories":["pole","bridge"],"note":"platform baseline placeholder"}'::jsonb,
    true,
    true,
    'available'
WHERE NOT EXISTS (
    SELECT 1 FROM models WHERE name = 'baseline-yolo-infrared' AND is_baseline = true
);

-- 为尚无版本记录的基线补初始版本
INSERT INTO model_versions (
    model_id, version_number, file_path, parent_version_id,
    change_note
)
SELECT
    m.model_id,
    'v1.0.0',
    m.file_path,
    NULL,
    'baseline seed'
FROM models m
WHERE m.is_baseline = true
  AND NOT EXISTS (
      SELECT 1 FROM model_versions mv WHERE mv.model_id = m.model_id
  );
