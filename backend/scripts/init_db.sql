-- ============================================================================
-- 目标检测数据与算法评测平台 — 全量 DDL（16 张表）
-- PostgreSQL 16+
--
-- 外键删除策略：
--   owner_id  / reviewer_id → ON DELETE SET NULL（数据保留，所有权清空）
--   created_by / user_id     → ON DELETE RESTRICT（审计需要，有关联记录的用户禁止硬删除）
--   主删除机制为软删除（users.is_active = false）
--
-- annotations 追加写策略：
--   UNIQUE (task_id, resource_id, version)，每次保存 INSERT 新行保留完整历史
-- ============================================================================

-- ════════════════════════════════════════════════════════════════════════════
-- P0: 核心表（Day 1 必须完成）
-- ════════════════════════════════════════════════════════════════════════════

-- (1) users 用户表
CREATE TABLE users (
    user_id         SERIAL          PRIMARY KEY,
    username        VARCHAR(50)     UNIQUE NOT NULL,
    password_hash   VARCHAR(255)    NOT NULL,
    email           VARCHAR(100)    UNIQUE NOT NULL,
    role            VARCHAR(20)     NOT NULL DEFAULT 'normal'
                                    CHECK (role IN ('admin', 'reviewer', 'normal')),
    is_active       BOOLEAN         NOT NULL DEFAULT true,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_users_role       ON users (role);
CREATE INDEX idx_users_is_active  ON users (is_active);

-- (2) data_resources 数据资源表
CREATE TABLE data_resources (
    resource_id      SERIAL          PRIMARY KEY,
    name             VARCHAR(255)    NOT NULL,
    owner_id         INTEGER         REFERENCES users(user_id)
                                     ON DELETE SET NULL,
    modality         VARCHAR(20)     NOT NULL
                                     CHECK (modality IN ('visible', 'infrared', 'mmwave', 'lidar')),
    file_path        VARCHAR(500)    NOT NULL,
    metadata         JSONB           NOT NULL DEFAULT '{}',
    version          INTEGER         NOT NULL DEFAULT 1,
    annotation_status VARCHAR(20)    NOT NULL DEFAULT 'unannotated'
                                     CHECK (annotation_status IN ('unannotated', 'annotated')),
    status           VARCHAR(20)     NOT NULL DEFAULT 'active'
                                     CHECK (status IN ('active', 'archived')),
    created_at       TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dr_owner             ON data_resources (owner_id);
CREATE INDEX idx_dr_modality          ON data_resources (modality);
CREATE INDEX idx_dr_annotation_status ON data_resources (annotation_status);
CREATE INDEX idx_dr_status            ON data_resources (status);
CREATE INDEX idx_dr_metadata_scene    ON data_resources ((metadata->>'scene'));
CREATE INDEX idx_dr_metadata_batch    ON data_resources ((metadata->>'batch_id'));

-- (8) datasets 数据集表
CREATE TABLE datasets (
    dataset_id      SERIAL          PRIMARY KEY,
    name            VARCHAR(200)    NOT NULL,
    description     TEXT,
    owner_id        INTEGER         REFERENCES users(user_id)
                                    ON DELETE SET NULL,
    filters         JSONB,
    split_config    JSONB,
    version         VARCHAR(20)     NOT NULL DEFAULT 'v1.0',
    status          VARCHAR(20)     NOT NULL DEFAULT 'draft'
                                    CHECK (status IN ('draft', 'frozen', 'published')),
    archive_status  VARCHAR(20)     NOT NULL DEFAULT 'active'
                                    CHECK (archive_status IN ('active', 'archived')),
    visibility      VARCHAR(20)     NOT NULL DEFAULT 'private'
                                    CHECK (visibility IN ('private', 'public')),
    review_status   VARCHAR(20)     NOT NULL DEFAULT 'not_submitted'
                                    CHECK (review_status IN ('not_submitted', 'submitted', 'reviewing', 'approved', 'rejected')),
    reviewer_id     INTEGER         REFERENCES users(user_id)
                                    ON DELETE SET NULL,
    review_notes    JSONB,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ds_owner         ON datasets (owner_id);
CREATE INDEX idx_ds_status        ON datasets (status);
CREATE INDEX idx_ds_visibility    ON datasets (visibility);
CREATE INDEX idx_ds_review_status ON datasets (review_status);

-- (9) dataset_items 数据集条目表
CREATE TABLE dataset_items (
    item_id         SERIAL          PRIMARY KEY,
    dataset_id      INTEGER         NOT NULL REFERENCES datasets(dataset_id)
                                    ON DELETE CASCADE,
    resource_id     INTEGER         NOT NULL REFERENCES data_resources(resource_id)
                                    ON DELETE CASCADE,
    subset          VARCHAR(10)     NOT NULL
                                    CHECK (subset IN ('train', 'val', 'test')),
    added_at        TIMESTAMP       NOT NULL DEFAULT NOW(),
    UNIQUE (dataset_id, resource_id)
);
CREATE INDEX idx_di_dataset_subset ON dataset_items (dataset_id, subset);

-- ════════════════════════════════════════════════════════════════════════════
-- P1: 数据与标注相关（Day 2 上午）
-- ════════════════════════════════════════════════════════════════════════════

-- (3) data_versions 数据版本表
CREATE TABLE data_versions (
    version_id       SERIAL          PRIMARY KEY,
    resource_id      INTEGER         NOT NULL REFERENCES data_resources(resource_id)
                                     ON DELETE CASCADE,
    version_number   INTEGER         NOT NULL,
    file_path        VARCHAR(500)    NOT NULL,
    metadata_snapshot JSONB          NOT NULL,
    change_note      TEXT,
    created_by       INTEGER         NOT NULL REFERENCES users(user_id)
                                     ON DELETE RESTRICT,
    created_at       TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dv_resource        ON data_versions (resource_id);
CREATE INDEX idx_dv_version_number  ON data_versions (version_number);
CREATE INDEX idx_dv_created_at      ON data_versions (created_at);

-- (4) data_sources 数据源配置表
CREATE TABLE data_sources (
    source_id       SERIAL          PRIMARY KEY,
    name            VARCHAR(100)    NOT NULL,
    source_type     VARCHAR(20)     NOT NULL
                                    CHECK (source_type IN ('oss_bucket', 'local_dir', 's3')),
    connection_info JSONB           NOT NULL,
    modality        VARCHAR(20)     NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'inactive'
                                    CHECK (status IN ('active', 'inactive')),
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dsrc_name ON data_sources (name);

-- (5) label_schemas 标签体系表
CREATE TABLE label_schemas (
    schema_id       SERIAL          PRIMARY KEY,
    name            VARCHAR(100)    NOT NULL,
    categories      JSONB           NOT NULL,
    version         INTEGER         NOT NULL DEFAULT 1,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);

-- (6) annotation_tasks 标注任务表
CREATE TABLE annotation_tasks (
    task_id         SERIAL          PRIMARY KEY,
    name            VARCHAR(200)    NOT NULL,
    data_range      JSONB           NOT NULL,
    schema_id       INTEGER         NOT NULL REFERENCES label_schemas(schema_id)
                                    ON DELETE RESTRICT,
    assignee_ids    JSONB           NOT NULL,
    reviewer_id     INTEGER         REFERENCES users(user_id)
                                    ON DELETE SET NULL,
    skip_review     BOOLEAN         NOT NULL DEFAULT false,
    status          VARCHAR(20)     NOT NULL DEFAULT 'draft'
                                    CHECK (status IN ('draft', 'in_progress', 'submitted', 'reviewing', 'completed')),
    deadline        TIMESTAMP,
    created_by      INTEGER         NOT NULL REFERENCES users(user_id)
                                    ON DELETE RESTRICT,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_at_status      ON annotation_tasks (status);
CREATE INDEX idx_at_assignees   ON annotation_tasks USING GIN (assignee_ids);
CREATE INDEX idx_at_reviewer    ON annotation_tasks (reviewer_id);
CREATE INDEX idx_at_created_by  ON annotation_tasks (created_by);

-- (7) annotations 标注结果表
-- 追加写策略：UNIQUE (task_id, resource_id, version)，每次保存 INSERT 新行
CREATE TABLE annotations (
    annotation_id   SERIAL          PRIMARY KEY,
    task_id         INTEGER         NOT NULL REFERENCES annotation_tasks(task_id)
                                    ON DELETE CASCADE,
    resource_id     INTEGER         NOT NULL REFERENCES data_resources(resource_id)
                                    ON DELETE CASCADE,
    bboxes          JSONB           NOT NULL DEFAULT '[]',
    version         INTEGER         NOT NULL DEFAULT 1,
    review_status   VARCHAR(20)     NOT NULL DEFAULT 'pending'
                                    CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reject_reasons  JSONB,
    created_by      INTEGER         NOT NULL REFERENCES users(user_id)
                                    ON DELETE RESTRICT,
    updated_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    UNIQUE (task_id, resource_id, version)
);
CREATE INDEX idx_ann_task_id     ON annotations (task_id);
CREATE INDEX idx_ann_resource_id ON annotations (resource_id);
CREATE INDEX idx_ann_created_by  ON annotations (created_by);

-- ════════════════════════════════════════════════════════════════════════════
-- P2: 模型与评测相关（Day 2 下午）
-- ════════════════════════════════════════════════════════════════════════════

-- (10) models 模型注册表
CREATE TABLE models (
    model_id        SERIAL          PRIMARY KEY,
    name            VARCHAR(200)    NOT NULL,
    owner_id        INTEGER         REFERENCES users(user_id)
                                    ON DELETE SET NULL,
    framework       VARCHAR(20)     NOT NULL
                                    CHECK (framework IN ('pytorch', 'tensorflow', 'onnx')),
    file_path       VARCHAR(500)    NOT NULL,
    metadata        JSONB           NOT NULL,
    is_baseline     BOOLEAN         NOT NULL DEFAULT false,
    is_public       BOOLEAN         NOT NULL DEFAULT true,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'available', 'deprecated')),
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_m_owner       ON models (owner_id);
CREATE INDEX idx_m_status      ON models (status);
CREATE INDEX idx_m_is_baseline ON models (is_baseline);

-- (11) model_versions 模型版本表
CREATE TABLE model_versions (
    version_id                  SERIAL          PRIMARY KEY,
    model_id                    INTEGER         NOT NULL REFERENCES models(model_id)
                                                ON DELETE CASCADE,
    version_number              VARCHAR(20)     NOT NULL,
    file_path                   VARCHAR(500)    NOT NULL,
    trained_on_dataset_id       INTEGER         REFERENCES datasets(dataset_id)
                                                ON DELETE SET NULL,
    trained_on_dataset_version  VARCHAR(20),
    metrics_snapshot            JSONB,
    change_note                 TEXT,
    created_at                  TIMESTAMP       NOT NULL DEFAULT NOW(),
    UNIQUE (model_id, version_number)
);
CREATE INDEX idx_mv_model_id ON model_versions (model_id);

-- (12) train_tasks 训练任务表
-- config 允许 {}，Service 层在启动训练时校验必填字段
CREATE TABLE train_tasks (
    task_id           SERIAL          PRIMARY KEY,
    model_id          INTEGER         NOT NULL REFERENCES models(model_id)
                                      ON DELETE CASCADE,
    model_version_id  INTEGER         REFERENCES model_versions(version_id)
                                      ON DELETE SET NULL,
    dataset_id        INTEGER         NOT NULL REFERENCES datasets(dataset_id)
                                      ON DELETE RESTRICT,
    config            JSONB           NOT NULL DEFAULT '{}',
    gpu_config        JSONB           NOT NULL DEFAULT '{}',
    status            VARCHAR(20)     NOT NULL DEFAULT 'pending_approval'
                                      CHECK (status IN ('pending_approval', 'approved', 'queued', 'running', 'completed', 'failed', 'stopped')),
    progress          JSONB,
    started_at        TIMESTAMP,
    finished_at       TIMESTAMP,
    error_log         TEXT,
    created_by        INTEGER         NOT NULL REFERENCES users(user_id)
                                      ON DELETE RESTRICT,
    created_at        TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_tt_model_id   ON train_tasks (model_id);
CREATE INDEX idx_tt_dataset_id ON train_tasks (dataset_id);
CREATE INDEX idx_tt_status     ON train_tasks (status);
CREATE INDEX idx_tt_created_by ON train_tasks (created_by);

-- (13) infer_tasks 推理任务表
CREATE TABLE infer_tasks (
    task_id         SERIAL          PRIMARY KEY,
    model_id        INTEGER         NOT NULL REFERENCES models(model_id)
                                    ON DELETE CASCADE,
    dataset_id      INTEGER         REFERENCES datasets(dataset_id)
                                    ON DELETE SET NULL,
    image_id        INTEGER         REFERENCES data_resources(resource_id)
                                    ON DELETE SET NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'queued'
                                    CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    results         JSONB,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    created_by      INTEGER         NOT NULL REFERENCES users(user_id)
                                    ON DELETE RESTRICT,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_it_model_id   ON infer_tasks (model_id);
CREATE INDEX idx_it_status     ON infer_tasks (status);
CREATE INDEX idx_it_created_by ON infer_tasks (created_by);

-- (14) eval_tasks 评测任务表
CREATE TABLE eval_tasks (
    task_id           SERIAL          PRIMARY KEY,
    model_id          INTEGER         NOT NULL REFERENCES models(model_id)
                                      ON DELETE CASCADE,
    model_version_id  INTEGER         REFERENCES model_versions(version_id)
                                      ON DELETE SET NULL,
    dataset_id        INTEGER         NOT NULL REFERENCES datasets(dataset_id)
                                      ON DELETE RESTRICT,
    metric_config     JSONB           NOT NULL,
    status            VARCHAR(20)     NOT NULL DEFAULT 'queued'
                                      CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    started_at        TIMESTAMP,
    finished_at       TIMESTAMP,
    created_by        INTEGER         NOT NULL REFERENCES users(user_id)
                                      ON DELETE RESTRICT,
    created_at        TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_et_model_dataset ON eval_tasks (model_id, dataset_id);
CREATE INDEX idx_et_status        ON eval_tasks (status);
CREATE INDEX idx_et_created_by    ON eval_tasks (created_by);

-- (15) eval_results 评测结果表
CREATE TABLE eval_results (
    result_id         SERIAL          PRIMARY KEY,
    task_id           INTEGER         NOT NULL REFERENCES eval_tasks(task_id)
                                      ON DELETE CASCADE,
    model_id          INTEGER         NOT NULL REFERENCES models(model_id)
                                      ON DELETE CASCADE,
    dataset_id        INTEGER         NOT NULL REFERENCES datasets(dataset_id)
                                      ON DELETE CASCADE,
    overall_metrics   JSONB           NOT NULL,
    per_class_metrics JSONB,
    per_size_metrics  JSONB,
    per_scene_metrics JSONB,
    pr_curve_data     JSONB,
    confusion_matrix  JSONB,
    error_samples     JSONB,
    is_public         BOOLEAN         NOT NULL DEFAULT false,
    created_at        TIMESTAMP       NOT NULL DEFAULT NOW(),
    UNIQUE (task_id)
);
CREATE INDEX idx_er_model_dataset ON eval_results (model_id, dataset_id);
CREATE INDEX idx_er_is_public     ON eval_results (is_public);

-- (16) audit_logs 审计日志表
CREATE TABLE audit_logs (
    log_id          SERIAL          PRIMARY KEY,
    user_id         INTEGER         NOT NULL REFERENCES users(user_id)
                                    ON DELETE RESTRICT,
    action          VARCHAR(50)     NOT NULL,
    target_type     VARCHAR(50)     NOT NULL,
    target_id       INTEGER         NOT NULL,
    before_state    JSONB,
    after_state     JSONB,
    ip_address      VARCHAR(50),
    user_agent      TEXT,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_al_user_id     ON audit_logs (user_id);
CREATE INDEX idx_al_action      ON audit_logs (action);
CREATE INDEX idx_al_target_type ON audit_logs (target_type);
CREATE INDEX idx_al_created_at  ON audit_logs (created_at);
