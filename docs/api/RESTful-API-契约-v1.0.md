# 后端 RESTful API 契约文档 v1.0

> **负责人**：张胤萌（模型组 · MLOps / 评测引擎）  
> **适用阶段**：第一阶段（Day1–Day4）及后续联调  
> **依据**：《模型组-概要设计报告 v4.0》路由层 + Service 层  
> **对照实现**：`backend/app/`（杨子杰第一阶段已落地部分）+ 前端 `frontend/src/api/*`  
> **最后更新**：2026-07-14

---

## 1. 文档目标

本契约是前后端、组内三人并行开发的**唯一接口标准**：

| 角色 | 如何使用本契约 |
|------|----------------|
| 赵善奇（前端） | 按路径与 JSON Schema 对接 / Mock，不等后端写完 |
| 杨子杰（数据后端） | 已实现接口以「✅ 已实现」为准；未实现接口补齐时不得改路径字段名 |
| 张胤萌（评测后端） | 按「⏳ 计划中」接口实现 M4/M5 + Celery 入队 |

**第一阶段交付要求（设计报告）：**  
> 全组统一、可直接在线调用的接口契约规范及 Mock 服务端。

---

## 2. 通用约定

### 2.1 Base URL

| 环境 | Base URL |
|------|----------|
| 本地开发 | `http://127.0.0.1:8000` |
| Vite 代理 | `frontend` 中 `baseURL: '/api'` → 代理到 `8000` |
| OpenAPI | `http://127.0.0.1:8000/docs` |

所有业务路径均以 `/api` 为前缀。

### 2.2 鉴权

| 项 | 约定 |
|----|------|
| Header | `Authorization: Bearer <access_token>` |
| Access Token | 有效期 **24h** |
| Refresh Token | 有效期 **7d**，存 Redis 黑名单以支持吊销 |
| 未登录 / Token 失效 | `401` |
| 角色不足 | `403` |

角色枚举：`admin` | `reviewer` | `normal`

### 2.3 统一响应

**成功分页列表：**

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "size": 20
}
```

**错误响应（FastAPI 标准）：**

```json
{
  "detail": "错误说明文字"
}
```

可选扩展字段（后续可加）：`error_code`

### 2.4 时间与分页

| 字段 | 约定 |
|------|------|
| 时间 | ISO 8601 字符串，如 `2024-03-01T08:00:00` |
| `page` | 从 **1** 开始 |
| `size` | 默认 20，最大 100（评测错题本等特殊接口可另规定） |

### 2.5 异步任务状态机（训练 / 推理 / 评测通用）

| status | 含义 |
|--------|------|
| `pending_approval` | 待管理员审批（仅训练） |
| `approved` | 审批通过，待入队（仅训练） |
| `queued` | 已进入 Celery 队列 |
| `running` | Worker 执行中 |
| `completed` | 成功 |
| `failed` | 失败（见 `error_log`） |
| `stopped` | 用户/管理强制终止（仅训练） |

创建异步任务后，HTTP **立即返回** `task_id` + `status`，耗时计算在 Celery Worker 中完成。

### 2.6 实现状态图例

| 标记 | 含义 |
|------|------|
| ✅ | 杨子杰第一阶段已实现，字段以当前代码为准 |
| ⏳ | 契约已定，第二/三阶段由张胤萌实现 |
| 📋 | 契约已定，主要责任在杨子杰，第二阶段实现 |

---

## 3. 系统

### `GET /api/health` ✅

无需鉴权。

**响应：**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## 4. 鉴权与用户（杨子杰）

### `POST /api/auth/register` ✅

**请求：**

```json
{
  "username": "alice",
  "password": "Abc123!@",
  "email": "alice@example.com"
}
```

| 字段 | 约束 |
|------|------|
| username | 3–50 字符，唯一 |
| password | 8–20 位；大写/小写/数字/特殊字符至少三类 |
| email | 合法邮箱，唯一 |

**响应 `201`：** `UserResponse`（见下）

### `POST /api/auth/login` ✅

**请求：** `{ "username": "...", "password": "..." }`

**响应：**

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "role": "normal"
}
```

### `POST /api/auth/refresh` ✅

**请求：** `{ "refresh_token": "..." }`  
**响应：** 同 `TokenResponse`

### `POST /api/auth/logout` ✅

需 Access Token；可选 Query：`refresh_token`。  
**响应：** `204 No Content`

### `GET /api/users/me` ✅

**响应 `UserResponse`：**

```json
{
  "user_id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "role": "normal",
  "is_active": true,
  "created_at": "2024-03-01T08:00:00"
}
```

### `PUT /api/users/me` ✅

**请求（字段均可选）：**

```json
{
  "email": "new@example.com",
  "old_password": "Abc123!@",
  "new_password": "Def456!@"
}
```

### `GET /api/users/me/history` ✅

Query：`page`, `size`, `action`（可选）

**响应：** 标准分页；第一阶段可能返回空 `items`（审计日志尚未写入）。

---

## 5. 数据资源（杨子杰）

### `POST /api/data/upload` ✅

`multipart/form-data`

| 字段 | 类型 | 说明 |
|------|------|------|
| files | file[] | 图片，可多文件 |
| name | form | 文件名 |
| modality | form | `visible` \| `infrared` \| `mmwave` \| `lidar`，默认 `visible` |
| meta_info | form | JSON 字符串，附加场景等 |

**响应 `201`：** `DataResourceResponse[]`

### `GET /api/data` ✅

需登录。返回**当前用户**数据列表。

Query：

| 参数 | 说明 |
|------|------|
| modality | 模态 |
| annotation_status | `annotated` \| `unannotated` |
| status | `active` \| `archived` |
| scene | 场景（匹配 `meta_info.scene`） |
| start_time / end_time | ISO 时间范围 |
| page / size | 分页 |

**`DataResourceResponse`：**

```json
{
  "resource_id": 1,
  "name": "sample.jpg",
  "owner_id": 1,
  "modality": "visible",
  "file_path": "data/1/uuid.jpg",
  "meta_info": {
    "width": 1920,
    "height": 1080,
    "channels": 3,
    "scene": "daytime",
    "weather": "clear"
  },
  "annotation_status": "unannotated",
  "status": "active",
  "version": 1,
  "created_at": "...",
  "updated_at": "..."
}
```

> **字段名约定**：对外 JSON 统一使用 `meta_info`（库表列名为 `metadata`）。前端旧 Mock 若写 `metadata`，联调时需与本契约对齐。

### 扩展（📋 / ⏳ 第二阶段）

| 路径 | 说明 | 状态 |
|------|------|------|
| `GET /api/data/{id}` | 详情 | 📋 |
| `GET /api/data/{id}/versions` | 版本列表 | 📋 |
| `PUT /api/data/{id}/metadata` | 更新元信息 | 📋 |
| `POST /api/data/align` | 多模态帧对齐 | 📋 |

---

## 6. 数据集（杨子杰主导 · 📋）

路径与前端 `api/dataset.js`、设计报告一致：

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/datasets` | 市场列表（公开） |
| GET | `/api/datasets/{id}` | 详情 |
| GET | `/api/datasets/{id}/preview` | 样本预览 |
| POST | `/api/datasets/preview` | 按条件预览命中数 |
| POST | `/api/datasets` | 创建数据集 |
| POST | `/api/datasets/{id}/split` | train/val/test 划分 |
| POST | `/api/datasets/{id}/freeze` | 冻结 |
| POST | `/api/datasets/{id}/publish` | 发布 |
| POST | `/api/datasets/{id}/submit-review` | 提交审核 |
| PUT | `/api/datasets/{id}/visibility` | 可见性 |
| POST | `/api/datasets/{id}/archive` | 归档 |
| POST | `/api/datasets/{id}/restore` | 恢复 |
| GET | `/api/datasets/{id}/versions` | 版本 |
| GET | `/api/datasets/{id}/diff` | 版本 diff |
| GET | `/api/datasets/{id}/export` | 导出 ZIP |
| POST | `/api/datasets/{id}/copy` | 复制到个人库 |

**列表 Query 草案：** `visibility`, `modality`, `keyword`, `page`, `size`

**核心字段草案：**

```json
{
  "dataset_id": 1,
  "name": "...",
  "description": "...",
  "owner_id": 1,
  "modality": "visible",
  "sample_count": 200,
  "status": "draft",
  "visibility": "private",
  "is_official": false,
  "review_status": "none",
  "created_at": "..."
}
```

`status`：`draft` | `frozen` | `published`  
`visibility`：`private` | `public`

> 评测 / 训练提交前，契约强制要求：`dataset.status === "frozen"`（训练）或测试集不可随意修改（评测锁定）。

---

## 7. 模型管理 M4（张胤萌 · ⏳）

> Service：`normal_model_service.py`（待建）  
> 表：`models`, `model_versions`（DDL/ORM 已就绪）

### `POST /api/models` ⏳

注册模型。`multipart/form-data`：

| 字段 | 说明 |
|------|------|
| file | 权重文件（`.pt` / `.pth` / `.onnx`） |
| name | 模型名 |
| framework | `pytorch` \| `tensorflow` \| `onnx` |
| metadata | JSON 字符串：输入尺寸、支持模态、类别列表等 |

**响应 `201`：**

```json
{
  "model_id": 1,
  "name": "yolo-visible-v1",
  "owner_id": 1,
  "framework": "onnx",
  "file_path": "models/1/xxx.onnx",
  "meta_info": {
    "input_size": [640, 640],
    "modalities": ["visible"],
    "categories": ["电线杆", "桥梁"]
  },
  "is_baseline": false,
  "is_public": true,
  "status": "pending",
  "created_at": "..."
}
```

`status`：`pending` → 校验通过后 `available`；失败保持异常信息（实现细节第三阶段）。

### `GET /api/models` ⏳

我的模型列表。Query：`framework`, `status`, `page`, `size`

### `GET /api/models/{id}` ⏳

详情 + 版本列表：

```json
{
  "model_id": 1,
  "name": "...",
  "versions": [
    {
      "version_id": 10,
      "version_number": "1.0.0",
      "file_path": "...",
      "trained_on_dataset_id": 3,
      "change_note": "initial",
      "created_at": "..."
    }
  ]
}
```

### `POST /api/models/{id}/versions` ⏳

上传新版本。`multipart`：`file`, `version_note`, 可选 `trained_on_dataset_id`

### `PUT /api/models/{id}/visibility` ⏳

```json
{ "is_public": true }
```

### `DELETE /api/models/{id}` ⏳

废弃模型（`status = deprecated`），非物理删除。

### `GET /api/models/baselines` ⏳

平台预置基线，只读，无需按 owner 过滤。

---

## 8. 训练任务 M4（张胤萌 · ⏳）

> 入队：Celery `train_task`；审批通过后 Worker 拉起 Docker 训练容器（第二阶段）

### `POST /api/train/tasks` ⏳

```json
{
  "model_id": 1,
  "dataset_id": 3,
  "config": {
    "epochs": 50,
    "batch_size": 16,
    "lr": 0.001,
    "optimizer": "adam"
  },
  "gpu_config": {
    "gpu_count": 1,
    "gpu_type": "rtx4090"
  }
}
```

**前置校验：** `dataset.status == frozen`  
**响应 `201`：** `{ "task_id": 1, "status": "pending_approval" }`

### `POST /api/train/tasks/{id}/enqueue` ⏳（Phase1 联调辅助）

将 `pending_approval` / `approved` 任务置为 `queued` 并投递 Celery `tasks.train.run`。  
第二阶段由管理员审批接口替代，本路径可废弃或仅限 `admin`。

### `GET /api/train/tasks/{id}` ⏳

```json
{
  "task_id": 1,
  "model_id": 1,
  "dataset_id": 3,
  "status": "running",
  "progress": {
    "epoch": 12,
    "loss": 0.42,
    "map50": 0.61
  },
  "started_at": "...",
  "finished_at": null,
  "error_log": null
}
```

### `POST /api/train/tasks/{id}/stop` ⏳

终止训练，释放资源。`status → stopped`

### `GET /api/train/tasks/{id}/logs` ⏳

从 Redis Stream 读日志行：

```json
{
  "lines": ["epoch 1 loss=...", "epoch 2 loss=..."]
}
```

---

## 9. 推理任务 M4（张胤萌 · ⏳）

> Celery：`infer_task`；ONNX Runtime 前向（第三阶段实装）

### `POST /api/infer/tasks` ⏳

```json
{
  "model_id": 1,
  "dataset_id": 5,
  "image_id": null
}
```

`dataset_id` 与 `image_id` 二选一（整集或单图）。

**响应：** `{ "task_id": 9, "status": "queued" }`

### `GET /api/infer/tasks/{id}/results` ⏳

Query：`class_filter`, `min_confidence`（默认 0.1）

```json
{
  "task_id": 9,
  "status": "completed",
  "results": {
    "total_images": 100,
    "completed": 100,
    "detections": [
      {
        "image_id": 1,
        "boxes": [
          {
            "x": 0.1, "y": 0.2, "w": 0.15, "h": 0.25,
            "category_id": 1,
            "confidence": 0.91,
            "depth": 12.5
          }
        ]
      }
    ]
  }
}
```

### `GET /api/infer/tasks/{id}/visualize/{image_id}` ⏳

返回叠加框后的图片字节流：`Content-Type: image/jpeg`

---

## 10. 评测分析 M5（张胤萌 · ⏳）

> Service：`normal_eval_service.py` + `MetricsEngine`（第三阶段）  
> Celery：`eval_task`

### `POST /api/eval/tasks` ⏳

```json
{
  "model_id": 1,
  "model_version_id": 10,
  "dataset_id": 5,
  "metric_config": {
    "iou_thresholds": [0.5, 0.75],
    "max_detections": 100
  }
}
```

**前置：** 数据集冻结；存在 Ground Truth。  
**响应：** `{ "task_id": 3, "status": "queued" }`

### `GET /api/eval/tasks/{id}` ⏳

任务状态查询（同异步状态机）。

### `GET /api/eval/tasks/{id}/metrics` ⏳

```json
{
  "task_id": 3,
  "overall_metrics": {
    "mAP50": 0.72,
    "mAP50_95": 0.45,
    "precision": 0.81,
    "recall": 0.68,
    "f1": 0.74,
    "fps": 42.5
  },
  "per_class_metrics": [
    { "category_id": 1, "name": "电线杆", "ap50": 0.80 }
  ],
  "per_size_metrics": {
    "small": 0.31,
    "medium": 0.55,
    "large": 0.70
  }
}
```

### `GET /api/eval/tasks/{id}/pr-curve` ⏳

Query：`class_id`（可选）

```json
{
  "points": [[0.0, 1.0], [0.1, 0.95], [1.0, 0.0]]
}
```

`[precision, recall]` 点列，供 ECharts 使用。

### `GET /api/eval/tasks/{id}/confusion` ⏳

```json
{
  "matrix": [[10, 1], [2, 8]],
  "labels": ["电线杆", "桥梁"]
}
```

### `GET /api/eval/tasks/{id}/errors` ⏳

Query：`error_type` = `fp` \| `fn` \| `tp`，`class_id`，`page`，`size`（默认 20）

```json
{
  "items": [
    {
      "image_id": 12,
      "error_type": "fn",
      "category_id": 1,
      "thumbnail_url": "/api/data/12/..."
    }
  ],
  "total": 35,
  "page": 1,
  "size": 20
}
```

### `POST /api/eval/compare` ⏳

最多 5 个模型，同一 `dataset_id`：

```json
{
  "model_ids": [1, 2, 3],
  "dataset_id": 5
}
```

**响应（雷达图六维）：**

```json
{
  "axes": ["mAP50", "mAP50_95", "precision", "recall", "fps", "lightweight"],
  "series": [
    { "model_id": 1, "name": "...", "values": [0.72, 0.45, 0.81, 0.68, 0.6, 0.7] }
  ]
}
```

### `GET /api/eval/leaderboard` ⏳

Query：`dataset_id`（必填）

仅 `eval_results.is_public = true`，按 `mAP` 降序。

### `GET /api/eval/history/{model_id}` ⏳

Query：`dataset_id`

同模型多版本趋势；若新版本 mAP 低于上一版，响应中增加 `"regression": true`。

---

## 11. 标注 / 审核 / 管理（摘要）

路径与前端 `api/annotation.js`、`review.js`、`admin.js` 及设计报告一致，第一阶段不强制实现，契约路径冻结如下：

### 标注 📋

| Method | Path |
|--------|------|
| POST | `/api/annotation/tasks` |
| GET | `/api/annotation/tasks` |
| GET | `/api/annotation/tasks/{id}/progress` |
| GET | `/api/annotation/tasks/{id}/next` |
| PUT | `/api/annotation/images/{imageId}/save` |
| POST | `/api/annotation/images/{imageId}/submit` |
| GET | `/api/annotation/images/{imageId}/history` |

### 审核 📋

| Method | Path |
|--------|------|
| GET | `/api/review/datasets` |
| POST | `/api/review/datasets/{id}/claim` |
| POST | `/api/review/datasets/{id}/verdict` |
| GET | `/api/review/annotation-tasks` |
| POST | `/api/review/annotations/{id}/verdict` |

### 管理 ⏳/📋

| Method | Path | 与张相关 |
|--------|------|----------|
| GET | `/api/admin/train-tasks/pending` | 训练审批 |
| POST | `/api/admin/train-tasks/{id}/approve` | 训练审批 |
| GET | `/api/admin/infer-tasks/pending` | 推理审批 |
| GET | `/api/admin/eval/leaderboard` | 天梯治理 |
| POST | `/api/admin/eval-results/{id}/invalidate` | 作弊下架 |

---

## 12. HTTP 状态码约定

| 码 | 场景 |
|----|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 204 | 成功无 Body（登出等） |
| 400 | 参数校验失败 / 业务前置不满足（如数据集未冻结） |
| 401 | 未登录或 Token 无效 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 409 | 冲突（用户名重复等） |
| 422 | Pydantic 校验失败 |
| 500 | 服务器内部错误 |
| 501 | （过渡期）契约已定但未实现，可返回此码 |

---

## 13. Mock 联调约定（第一阶段）

1. **已实现接口**：直接打真实后端 `uvicorn app.main:app`（端口以 `.env` / 测试报告为准，常见 `8000` 或 `8002`）。
2. **未实现接口**：  
   - 方案 A：Apifox 导入本契约，打开 Mock；  
   - 方案 B：后端对 ⏳ 路径先挂路由返回 `501` + 本契约中的示例 JSON（推荐 Day3–4 由张胤萌提交骨架）。
3. 前端当前部分页面仍 `USE_MOCK = true`，切换真实后端前，字段名以**本契约**为准做一次对齐（尤其 `meta_info` vs `metadata`）。

---

## 14. Celery 任务名约定（张胤萌）

| 任务名 | 触发 API | 入参 |
|--------|----------|------|
| `tasks.train.run` | 管理员审批通过后 / 或自动入队 | `train_task_id` |
| `tasks.infer.run` | `POST /api/infer/tasks` | `infer_task_id` |
| `tasks.eval.run` | `POST /api/eval/tasks` | `eval_task_id` |

Broker / Result Backend：复用现有 `REDIS_URL`（`redis://localhost:6379/0`）。

---

## 15. 与前端 API 文件映射

| 前端文件 | 契约章节 |
|----------|----------|
| `api/auth.js` | §4 |
| `api/data.js` | §5 |
| `api/dataset.js` | §6 |
| `api/model.js` | §7–§9 |
| `api/eval.js` | §10 |
| `api/annotation.js` | §11 |
| `api/review.js` | §11 |
| `api/admin.js` | §11 |

---

## 16. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-07-14 | 首版：合并设计报告路由 + 杨子杰已实现鉴权/数据字段 + 前端路径 |
| v1.0.1 | 2026-07-14 | 补充训练 Phase1 联调辅助入队 `POST /api/train/tasks/{id}/enqueue` |

---

## 17. 确认清单（Day4 联调前）

- [ ] 三人确认：Base URL、Token Header、分页字段名  
- [ ] 三人确认：`meta_info` 为数据元信息标准字段名  
- [ ] 赵：前端 Mock / 真实切换计划  
- [ ] 杨：数据集/标注第二阶段路径不改动  
- [ ] 张：按本契约写 OpenAPI 骨架 + Celery 空任务，打 `v1.0-alpha`  

文档路径：`docs/api/RESTful-API-契约-v1.0.md`
