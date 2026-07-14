# 第一、二阶段系统功能清单

**负责人**：杨子杰（数据底座与轻量化资产流水线）
**范围**：用户鉴权 / 数据资源管理 / 多模态对齐 / 标签体系 / 在线标注 / 数据集审核 / 标注审核
**状态**：✅ 全部交付，集成测试 50/50 通过

---

## 一、基础设施

| 组件 | 技术选型 | 端口 | 说明 |
|------|---------|------|------|
| 数据库 | PostgreSQL 16 | 5432 | 20 张业务表 |
| 缓存 | Redis 7 | 6379 | Token 黑名单 + （Phase 3 扩展） |
| 对象存储 | MinIO | 9000/9001 | 图片与模型文件 |
| 后端框架 | FastAPI | 8000 | 自动生成 Swagger `/docs` + ReDoc `/redoc` |
| 数据库迁移 | Alembic | — | 增量迁移，autogenerate |
| 容器化 | Docker Compose | — | 一键启动全部中间件 |

**队友对接**：

```bash
# 1. 启动所有基础设施
docker-compose up -d

# 2. 初始化数据库
docker exec -i pg-local psql -U postgres -d detection_platform < backend/scripts/init_db.sql

# 3. 启动后端
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 4. 访问 API 文档
http://localhost:8000/docs
```

---

## 二、用户鉴权（Phase 1）

| 功能 | 说明 |
|------|------|
| 注册 | `POST /api/auth/register` — bcrypt 哈希 + 密码强度校验（8-20位，至少三类字符） |
| 登录 | `POST /api/auth/login` — 签发双 Token（Access Token 24h + Refresh Token 7d） |
| 刷新 | `POST /api/auth/refresh` — Refresh Token 换新 Token 对 |
| 登出 | `POST /api/auth/logout` — Token 入 Redis 黑名单 |
| 个人信息 | `GET /api/users/me` / `PUT /api/users/me` — 查/改个人信息 |
| 操作历史 | `GET /api/users/me/history` — 审计日志分页查询 |
| JWT 鉴权 | `get_current_user` — 自动从 Bearer Token 提取用户，校验 is_active |
| RBAC | `require_role(*roles)` — 角色拦截（admin / reviewer / normal），403 拒绝 |

**三种角色**：

| 角色 | 权限 |
|------|------|
| admin | 全部权限（用户管理、标签体系、算力调度） |
| reviewer | 数据集审核 + 标注审核 + 访问审核工作台 |
| normal | 上传数据、标注、构建数据集、提交公开申请 |

---

## 三、数据资源管理（Phase 1 + 2）

### 3.1 数据上传

```
POST /api/data/upload   (multipart/form-data, JWT)
  files:       图片文件（支持批量）
  name:        文件名
  modality:    visible / infrared / mmwave / lidar
  meta_info:   JSON 字符串 {scene, weather, device, ...}
  captured_at: Unix 时间戳（可选，Phase 2 新增）
  annotation_file: 标注文件（可选，Phase 2 新增，支持 COCO/VOC/YOLO）
  format:      coco / voc / yolo
  task_id:     关联标注任务（可选）
```

**自动处理**：
- Pillow 提取图片宽/高/通道数/文件大小
- 上传至 MinIO，数据库仅存 `file_path`

### 3.2 数据查询

```
GET /api/data   (JWT, 分页)
  modality / scene / annotation_status / status / start_time / end_time
```

返回当前用户的数据资源列表，支持多条件组合筛选 + 时间范围。

### 3.3 带标注导入（Phase 2 新增）

上传图片时附带标注文件，自动解析并写入 annotations 表。

| 格式 | 文件类型 | 转换 |
|------|---------|------|
| COCO JSON | 单文件 | images[]/annotations[]/categories[] → 归一化坐标 |
| VOC XML | ZIP 包（多个 XML） | `<size>/<object>/<bndbox>` → 归一化坐标 |
| YOLO TXT | ZIP 包（多个 TXT） | `class_id cx cy w h` 已是归一化 |

**自动处理**：类别名按 label_schema 活跃类别自动匹配；不传 task_id 时自动创建任务。

---

## 四、多模态时间戳对齐（Phase 2 新增）

三种策略实现（`app/utils/alignment.py`）：

| 策略 | 算法 | 复杂度 | 参数 |
|------|------|--------|------|
| nearest_neighbor | 最近邻时间窗 | O(n+m) | time_window_ms: 50（默认） |
| downsample | 降采样统一帧率 | O(n) | target_fps: auto（最低帧率） |
| interpolate | 插值补齐 | O(n×m) | strategy: nearest / linear |

```
POST /api/data/align   (JWT)
  Body: { resource_ids: [1,2,...], strategy: "nearest_neighbor", params: {...} }
  → Response: { group_id, pairs_count, report: {...} }
```

**对齐结果**：存储于 `alignment_groups` + `alignment_group_items` 表，支持历史追溯。

---

## 五、标签体系管理（Phase 2 新增）

全平台公用的障碍物类别标签库，管理员维护。

| 端点 | 鉴权 | 说明 |
|------|------|------|
| `POST /api/admin/schemas` | admin | 创建标签体系 |
| `POST /api/admin/schemas/{id}/categories` | admin | 新增类别（自动生成 cat_001 ID） |
| `PUT /api/admin/schemas/{id}/categories/{cid}` | admin | 修改类别属性 |
| `DELETE /api/admin/schemas/{id}/categories/{cid}` | admin | 废弃类别（记录原因 + 替代类别） |
| `GET /api/admin/schemas/{id}/export` | admin | 导出 JSON |
| `POST /api/admin/schemas/import` | admin | Pydantic 校验导入 JSON |
| `GET /api/schemas/{id}/categories` | JWT | 活跃类别列表（标注员查询） |

**类别结构**：`{id, name, shortcut, depth_required, occlusion_required, truncation_required, status}`

---

## 六、在线标注（Phase 2 新增）

### 6.1 标注任务管理

```
POST /api/annotation/tasks   (JWT)
  Body: { name, data_range, schema_id, assignee_ids, reviewer_id?, skip_review, deadline? }
```

### 6.2 标注保存（追加写模式）

```
PUT /api/annotation/images/{resource_id}/save?task_id=N   (JWT, 需是 assignee)
  Body: { bboxes: [{ x, y, w, h (0~1归一化), category_id, depth?, occlusion?(0-3), truncation?(0-3) }] }
```

- 每次保存 INSERT 新行，version 递增
- rejected 后可重新编辑（自动重置 review_status）
- submitted / approved 后锁定

### 6.3 标注历史

```
GET /api/annotation/images/{resource_id}/history?task_id=N
```

按版本号降序返回所有历史版本。

### 6.4 提交审核

```
POST /api/annotation/images/{resource_id}/submit?task_id=N
```

- skip_review 任务直接 approved
- 提交后任务 status → submitted

### 6.5 进度统计

```
GET /api/annotation/tasks/{id}/progress
  → { total(匹配资源数), annotated, reviewed, approved, rejected }
```

---

## 七、数据集审核（Phase 2 新增）

审核员认领 → 15 项检查清单 → 裁决。

| 端点 | 说明 |
|------|------|
| `GET /api/review/datasets` | 待审核数据集列表 |
| `POST /api/review/datasets/{id}/claim` | 认领（锁定，不可审自己的） |
| `POST /api/review/datasets/{id}/unclaim` | 放弃认领 |
| `GET /api/review/datasets/{id}/checklist` | 15 项检查清单（7 项系统自动检测） |
| `POST /api/review/datasets/{id}/verdict` | 审核裁决（approved → 自动发布 / rejected） |

**7 项自动检测**：A1 文件格式 / A5 数据去重 / A6 标签合法性 / A7 标注框规范 / A8 深度值合理性 / A9 元信息完整性 / A11 命名规范

**安全规则**：不可审自己的数据集、不可抢他人认领、只有 reviewing 状态可裁决。

---

## 八、标注审核（Phase 2 新增）

审核员认领标注任务 → 抽检 → 逐张审核 → 结束。

| 端点 | 说明 |
|------|------|
| `GET /api/review/annotation-tasks` | 待审核标注任务池 |
| `POST /api/review/annotation-tasks/{id}/claim` | 认领（不可审自己标的图） |
| `POST /api/review/annotation-tasks/{id}/sample` | 配置抽检（random 随机/manual 手动，10%-100%，默认 20%） |
| `POST /api/review/annotations/{id}/verdict` | 逐张审核（rejected 时必选 T01-T10） |
| `GET /api/review/annotation-tasks/{id}/summary` | 抽检结果摘要（通过率 + 驳回分布） |
| `POST /api/review/annotation-tasks/{id}/finalize` | 结束审核（dismiss_only/expand/reject_all） |

**T01-T10 驳回模板**：10 类标准化驳回原因（框偏移/尺寸不准/类别错误/漏标/多标/深度偏差/遮挡/截断/越界/图片质量）

---

## 九、质量检查辅助 + 绩效统计（Phase 2 新增）

| 端点 | 说明 |
|------|------|
| `GET /api/review/annotation-tasks/{id}/quality-check` | 规则引擎 5 项自动扫描（越界/面积异常/宽高比/重复框/深度值） |
| `GET /api/review/stats` | 审核员绩效统计（数据集审核 + 标注审核双维度） |

---

## 十、数据库表结构（20 张表）

### Phase 1 建表（16 张）

| 表名 | 说明 |
|------|------|
| `users` | 用户表（username/email/role/is_active） |
| `data_resources` | 数据资源表（file_path/captured_at/modality/annotation_status） |
| `data_versions` | 数据版本快照 |
| `data_sources` | 数据源配置（oss_bucket/local_dir/s3） |
| `label_schemas` | 标签体系（categories JSONB） |
| `annotation_tasks` | 标注任务 |
| `annotations` | 标注结果（追加写，version 递增） |
| `datasets` | 数据集 |
| `dataset_items` | 数据集条目（train/val/test） |
| `models` | 模型注册 |
| `model_versions` | 模型版本 |
| `train_tasks` | 训练任务 |
| `infer_tasks` | 推理任务 |
| `eval_tasks` | 评测任务 |
| `eval_results` | 评测结果（mAP/P-R/混淆矩阵） |
| `audit_logs` | 审计日志 |

### Phase 2 新增（2 张表 + 3 列）

| 变更 | 说明 |
|------|------|
| `alignment_groups` 表 | 对齐任务组（strategy/params/report） |
| `alignment_group_items` 表 | 对齐配对明细（group_id/resource_id/sensor_type/is_primary） |
| `data_resources.captured_at` 列 | Unix 时间戳（DOUBLE PRECISION） |
| `annotation_tasks.review_info` 列 | 审核信息 JSONB（sample_ids/ratio/mode） |
| `annotations.review_status` CHECK 约束 | 增加 `'submitted'` 值 |

---

## 十一、API 端点总览

| 模块 | 数量 | 说明 |
|------|:---:|------|
| 鉴权 | 7 | register/login/refresh/logout/me/update/history |
| 数据资源 | 3 | upload（含标注导入）/list/align |
| 标签体系 | 7 | CRUD + 导入导出 + 活跃类别查询 |
| 标注 | 6 | 任务创建/列表/保存/历史/提交/进度 |
| 数据集审核 | 5 | 待审核/认领/放弃/检查清单/裁决 |
| 标注审核 | 6 | 待审核/认领/抽检/逐张裁决/摘要/结束审核 |
| 质量+统计 | 2 | quality-check/stats |
| 系统 | 1 | /api/health |
| **合计** | **37** | |

---

## 十二、前端对接关键信息

### JWT 认证流程

```
1. POST /api/auth/login { username, password }
   → { access_token, refresh_token, token_type: "bearer", role }

2. 所有业务请求 Header:
   Authorization: Bearer <access_token>

3. Token 过期后:
   POST /api/auth/refresh { refresh_token }
   → 新 Token 对

4. 登出:
   POST /api/auth/logout
   Header: Authorization: Bearer <access_token>
   Query:  refresh_token=<refresh_token>
```

### BBox 坐标格式

```json
{
  "x": 0.5,         // 中心点 x（归一化 0~1）
  "y": 0.5,         // 中心点 y（归一化 0~1）
  "w": 0.2,         // 宽度（归一化 0~1）
  "h": 0.3,         // 高度（归一化 0~1）
  "category_id": "cat_001",
  "depth": 15.0,    // 深度（米），可选
  "occlusion": 0,   // 0-3，可选
  "truncation": 0   // 0-3，可选
}
```

### Swagger 文档

启动后端后访问：`http://localhost:8000/docs`（交互式 API 调试）/ `http://localhost:8000/redoc`
