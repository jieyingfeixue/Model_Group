-- 种子数据集：标签体系 + 数据集 + 条目
-- 执行：docker exec -i pg-local psql -U postgres -d detection_platform < scripts/seed_dataset.sql

-- 1. 标签体系
INSERT INTO label_schemas (name, categories, version, created_by)
VALUES (
    '低空障碍物检测',
    '[
        {"category_id": "cat_001", "name": "行人", "shortcut": "1", "depth_required": true, "occlusion_required": true, "truncation_required": false, "status": "active"},
        {"category_id": "cat_002", "name": "车辆", "shortcut": "2", "depth_required": true, "occlusion_required": true, "truncation_required": false, "status": "active"},
        {"category_id": "cat_003", "name": "非机动车", "shortcut": "3", "depth_required": false, "occlusion_required": true, "truncation_required": false, "status": "active"},
        {"category_id": "cat_004", "name": "建筑物", "shortcut": "4", "depth_required": false, "occlusion_required": false, "truncation_required": false, "status": "active"},
        {"category_id": "cat_005", "name": "电线杆", "shortcut": "5", "depth_required": true, "occlusion_required": false, "truncation_required": true, "status": "active"}
    ]'::jsonb,
    1,
    5
);

-- 2. 数据集1：多模态
INSERT INTO datasets (name, description, owner_id, filters, status, visibility, review_status, version, created_at, updated_at)
VALUES (
    '多模态低空场景数据集',
    '可见光5265张 + 红外1286张 + 激光雷达7帧，海康双相机+USB红外+AT360',
    5,
    '{"modality": ["visible", "infrared", "lidar"]}'::jsonb,
    'published',
    'public',
    'approved',
    1,
    NOW(),
    NOW()
);

INSERT INTO dataset_items (dataset_id, resource_id, subset)
SELECT 1, resource_id,
    CASE
        WHEN row_number() OVER (ORDER BY resource_id) % 10 < 7 THEN 'train'
        WHEN row_number() OVER (ORDER BY resource_id) % 10 < 9 THEN 'val'
        ELSE 'test'
    END
FROM data_resources
WHERE owner_id = 5
LIMIT 500;

-- 3. 数据集2：红外专属
INSERT INTO datasets (name, description, owner_id, filters, status, visibility, review_status, version, created_at, updated_at)
VALUES (
    '红外低空障碍物数据集',
    '红外传感器1286张，适用于夜间/低光照场景检测',
    5,
    '{"modality": ["infrared"]}'::jsonb,
    'published',
    'public',
    'approved',
    1,
    NOW(),
    NOW()
);

INSERT INTO dataset_items (dataset_id, resource_id, subset)
SELECT 2, resource_id,
    CASE
        WHEN row_number() OVER (ORDER BY resource_id) % 10 < 7 THEN 'train'
        WHEN row_number() OVER (ORDER BY resource_id) % 10 < 9 THEN 'val'
        ELSE 'test'
    END
FROM data_resources
WHERE modality = 'infrared' AND owner_id = 5;
