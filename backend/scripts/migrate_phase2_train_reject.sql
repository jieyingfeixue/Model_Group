-- Phase2 B1：训练任务增加 rejected 状态（管理员拒绝）
-- 用法：
--   Get-Content backend\scripts\migrate_phase2_train_reject.sql -Raw -Encoding UTF8 |
--     docker exec -i pg-local psql -U postgres -d detection_platform

ALTER TABLE train_tasks DROP CONSTRAINT IF EXISTS train_tasks_status_check;

ALTER TABLE train_tasks ADD CONSTRAINT train_tasks_status_check
    CHECK (status IN (
        'pending_approval', 'approved', 'queued',
        'running', 'completed', 'failed', 'stopped', 'rejected'
    ));
