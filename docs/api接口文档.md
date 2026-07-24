# 后端 API 接口文档

> **依据**：`backend/app/api/v1/` 实际代码，79 个端点完整梳理  
> **Base URL**：`http://127.0.0.1:8000`  
> **最后更新**：2026-07-24

---

## 通用约定

### 鉴权

| 项 | 约定 |
|----|------|
| Header | `Authorization: Bearer <access_token>` |
| Access Token 有效期 | 24h |
| Refresh Token 有效期 | 7d |
| 未登录 | `401` |
| 角色不足 | `403` |

### 角色枚举

| 角色 | 说明 |
|------|------|
| `normal` | 普通用户 |
| `reviewer` | 审核员 |
| `admin` | 管理员 |

### 统一分页响应

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "size": 20
}
```

- `page` 从 **1** 开始
- `size` 默认 **20**，最大 **100**（部分接口可达 6000）

### 时间格式

所有时间字段使用 **ISO 8601** 字符串：`2024-03-01T08:00:00`

---

## 一、公开接口（无需鉴权）

### 1.1 系统

#### `GET /api/health`

健康检查。

**响应**：
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

### 1.2 注册与登录

#### `POST /api/auth/register`

新用户注册。

**请求体** `RegisterRequest`：
| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| username | string | 是 | 3–50 字符，唯一 |
| password | string | 是 | 8–20 位；大小写/数字/特殊字符至少三类 |
| email | EmailStr | 是 | 合法邮箱，唯一 |

**响应 `201`** `UserResponse`：
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

#### `POST /api/auth/login`

用户登录。

**请求体** `LoginRequest`：
| 字段 | 类型 | 必填 |
|------|------|------|
| username | string | 是 |
| password | string | 是 |

**响应** `TokenResponse`：
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "role": "normal"
}
```

#### `POST /api/auth/refresh`

刷新 Token。

**请求体** `RefreshTokenRequest`：
| 字段 | 类型 | 必填 |
|------|------|------|
| refresh_token | string | 是 |

**响应** `TokenResponse`（同上）

---

## 二、普通用户接口（需登录，角色 `normal` / `reviewer` / `admin`）

### 2.1 个人信息

#### `GET /api/users/me`

获取当前登录用户信息。返回 `UserResponse`。

#### `PUT /api/users/me`

修改个人信息。

**请求体** `UserUpdateRequest`（字段均可选）：
| 字段 | 类型 | 说明 |
|------|------|------|
| email | EmailStr | 新邮箱 |
| old_password | string | 旧密码（修改密码时必填） |
| new_password | string | 新密码 |

**响应** `UserResponse`

#### `GET /api/users/me/history`

个人操作历史。

| Query 参数 | 类型 | 默认值 | 说明 |
|------------|------|--------|------|
| page | int | 1 | 页码 |
| size | int | 20 | 每页条数，≤100 |
| action | string | — | 操作类型筛选 |

**响应** 标准分页

#### `POST /api/auth/logout`

登出。`Authorization` Header 传递 Access Token，可选 Query `refresh_token` 一并吊销 Refresh Token。

**响应** `204 No Content`

---

### 2.2 数据资源

#### `POST /api/data/upload`

上传图片（支持多文件）。

**请求** `multipart/form-data`：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| files | file[] | 是 | 图片文件，支持多文件 |
| name | string | 是 | 文件名 |
| modality | string | 否 | `visible` / `infrared` / `mmwave` / `lidar`，默认 `visible` |
| meta_info | string(JSON) | 否 | 附加元信息 JSON，如 `{"scene":"daytime","weather":"clear"}` |

**响应 `201`** `list[DataResourceResponse]`：
```json
[{
  "resource_id": 1,
  "name": "sample.jpg",
  "owner_id": 1,
  "modality": "visible",
  "file_path": "/bucket/images/abc.jpg",
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
}]
```

#### `GET /api/data`

查询数据资源列表（多条件筛选）。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| modality | string | `visible` / `infrared` / `mmwave` / `lidar` |
| annotation_status | string | `annotated` / `unannotated` |
| status | string | `active` / `archived` |
| scene | string | 场景（匹配 `meta_info.scene`） |
| weather | string | 天气 |
| time_of_day | string | 时段 |
| terrain | string | 地形 |
| obstacle | string | 障碍物 |
| batch_id | string | 批次号 |
| sample_group | int | 样本组 |
| start_time | string | 起始时间 ISO |
| end_time | string | 结束时间 ISO |
| page | int | 默认 1 |
| size | int | 默认 20，最大 6000 |

**响应** 标准分页，items 为 `DataResourceResponse[]`

#### `GET /api/data/{resource_id}`

获取数据资源详情。返回 `DataResourceResponse`。

#### `GET /api/data/{resource_id}/versions`

获取数据资源版本列表。

**响应**：
```json
{
  "resource_id": 1,
  "versions": [{"version": 1, "updated_at": "..."}],
  "current_version": 1
}
```

#### `PUT /api/data/{resource_id}/metadata`

更新元信息（合并模式，版本号自动递增）。

**请求体** `DataResourceMetadataUpdateRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| meta_info | dict | 要合并的字段 |

**响应** `DataResourceResponse`

#### `POST /api/data/align`

多模态帧对齐（按 `sample_group` 分组）。

**请求体** `DataAlignRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| resource_ids | int[] | 待对齐的数据资源 ID 列表 |

**响应**：
```json
{
  "groups": [{
    "sample_group": "1",
    "modalities": ["visible", "infrared"],
    "resource_ids": [1, 2, 3],
    "scene": "daytime",
    "time_of_day": "morning"
  }],
  "total_groups": 5,
  "ungrouped": []
}
```

#### `GET /api/images/{resource_id}`

返回图片二进制流 (`image/jpeg`)。

#### `GET /api/images/{resource_id}/thumbnail`

返回缩略图。Query：`size`（默认 240）。

---

### 2.3 数据集

#### `POST /api/datasets`

创建数据集。

**请求体** `DatasetCreateRequest`：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 1–200 字符 |
| description | string | 否 | 数据集描述 |
| resource_ids | int[] | 是 | 数据资源 ID 列表 |
| split_config | object | 否 | 切分配置 `{train:70, val:20, test:10, strategy:"random"}` |
| visibility | string | 否 | `private`（默认）/ `public` |

**响应 `201`** `DatasetResponse`：
```json
{
  "dataset_id": 1,
  "name": "my-dataset",
  "description": "...",
  "owner_id": 1,
  "filters": {"resource_ids": [1,2,3]},
  "split_config": {"train": 70, "val": 20, "test": 10, "strategy": "random"},
  "version": "v1.0",
  "status": "draft",
  "archive_status": "active",
  "visibility": "private",
  "review_status": "not_submitted",
  "sample_count": 200,
  "subset_counts": {"train": 140, "val": 40, "test": 20},
  "created_at": "...",
  "updated_at": "..."
}
```

#### `GET /api/datasets`

查询数据集列表。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| visibility | string | `private` / `public` |
| keyword | string | 名称关键字 |
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

**响应** `DatasetListResponse`

#### `GET /api/datasets/{dataset_id}`

获取数据集详情。返回 `DatasetResponse`。

#### `GET /api/datasets/{dataset_id}/items`

获取数据集内样本列表，按 `sample_group` 分组。

#### `GET /api/datasets/{dataset_id}/preview`

预览数据集样本（基于已有 dataset_items）。

| Query 参数 | 类型 | 默认值 |
|------------|------|--------|
| page | int | 1 |
| size | int | 20 |

#### `POST /api/datasets/preview`

按条件预览命中资源数（不创建数据集）。

**请求体** `DatasetPreviewRequest`（字段均可选）：
| 字段 | 类型 | 说明 |
|------|------|------|
| resource_ids | int[] | 资源 ID 列表 |
| filters | object | 筛选条件 `{modality, scene, weather, time_of_day, terrain, obstacle, annotation_status}` |

**响应** `DatasetPreviewResponse`：
```json
{
  "match_count": 500,
  "sample_items": [{...}, ...]
}
```

#### `POST /api/datasets/{dataset_id}/split`

重新切分数据集。

**请求体** `DatasetSplitRequest`：
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| train | int | 70 | 训练集比例 |
| val | int | 20 | 验证集比例 |
| test | int | 10 | 测试集比例 |
| strategy | string | "random" | `random` / `sequential` / `grouped`（按样本组聚合） |

**响应** `DatasetResponse`

#### `POST /api/datasets/{dataset_id}/freeze`

冻结数据集（`draft` → `frozen`）。返回 `DatasetResponse`。

#### `POST /api/datasets/{dataset_id}/publish`

发布数据集（需先冻结，`frozen` → `published`）。

**请求体** `DatasetPublishRequest`（可选）：
| 字段 | 类型 | 默认值 |
|------|------|--------|
| version_note | string | "v1.0" |

**响应** `DatasetResponse`

#### `POST /api/datasets/{dataset_id}/submit-review`

提交数据集审核（需先冻结）。返回 `DatasetResponse`。

#### `PUT /api/datasets/{dataset_id}/visibility`

设置数据集可见性。

**请求体** `DatasetVisibilityRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| visibility | string | `private` / `public` |

**响应** `DatasetResponse`

#### `POST /api/datasets/{dataset_id}/archive`

归档数据集。返回 `DatasetResponse`。

#### `POST /api/datasets/{dataset_id}/restore`

恢复已归档数据集。返回 `DatasetResponse`。

#### `GET /api/datasets/{dataset_id}/versions`

获取数据集版本列表。

#### `GET /api/datasets/{dataset_id}/diff`

数据集版本差异对比。

| Query 参数 | 类型 | 必填 | 说明 |
|------------|------|------|------|
| v1 | string | 是 | 基准版本 |
| v2 | string | 是 | 对比版本 |

#### `GET /api/datasets/{dataset_id}/export`

导出数据集为 ZIP 下载（含所有图片文件 + `manifest.json`）。

#### `POST /api/datasets/{dataset_id}/copy`

复制数据集到个人库（深拷贝数据集条目）。**响应 `201`** `DatasetResponse`。

---

### 2.4 标注

#### `POST /api/annotation/tasks`

创建标注任务。

**请求体** `AnnotationTaskCreateRequest`：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 1–200 字符 |
| data_range | object | 是 | 标注范围，如 `{dataset_id:1, subset:"train", sample_count:100}` |
| schema_id | int | 是 | 标签体系 ID |
| assignee_ids | int[] | 是 | 标注员用户 ID 列表 |
| reviewer_id | int | 否 | 审核员用户 ID |
| skip_review | bool | 否 | 是否跳过审核，默认 false |
| deadline | string | 否 | 截止日期 ISO 字符串 |

**响应 `201`** `AnnotationTaskResponse`：
```json
{
  "task_id": 1,
  "name": "annotation-task-1",
  "data_range": {"dataset_id": 1, "subset": "train", "sample_count": 100},
  "schema_id": 1,
  "assignee_ids": [2, 3],
  "reviewer_id": 4,
  "skip_review": false,
  "status": "draft",
  "deadline": "2024-06-01T00:00:00",
  "created_by": 1,
  "created_at": "..."
}
```

#### `GET /api/annotation/tasks`

标注任务列表。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| status | string | `draft` / `in_progress` / `completed` |
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

**说明**：`normal` 用户只看分配给自己或自己创建的；`admin` 看全部。

**响应** `AnnotationTaskListResponse`

#### `GET /api/annotation/tasks/{task_id}/progress`

获取标注任务进度统计。

**响应** `AnnotationProgressResponse`：
```json
{
  "task_id": 1,
  "total_images": 100,
  "annotated": 45,
  "reviewed": 30,
  "progress_pct": 45.0
}
```

#### `GET /api/annotation/tasks/{task_id}/next`

获取下一个待标注的图片（跳过已标注的）。

**响应** `AnnotationNextImageResponse`：
```json
{
  "resource_id": 100,
  "name": "img_001.jpg",
  "modality": "visible",
  "file_path": "/bucket/images/abc.jpg",
  "has_existing_annotation": false,
  "existing_annotation_id": null,
  "existing_bboxes": null
}
```

#### `PUT /api/annotation/images/{resource_id}/save`

保存标注结果（追加写版本）。

| Query 参数 | 类型 | 必填 | 说明 |
|------------|------|------|------|
| task_id | int | 是 | 标注任务 ID |

**请求体** `AnnotationSaveRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| bboxes | object[] | 边界框列表，每个含 `class_id/x/y/w/h/confidence` |

**响应** `AnnotationSaveResponse`：
```json
{
  "annotation_id": 5,
  "task_id": 1,
  "resource_id": 100,
  "version": 2,
  "message": "保存成功"
}
```

#### `POST /api/annotation/images/{resource_id}/submit`

提交标注结果（标记该图片标注完成）。

| Query 参数 | 类型 | 必填 | 说明 |
|------------|------|------|------|
| task_id | int | 是 | 标注任务 ID |

**响应** `AnnotationSubmitResponse`：
```json
{
  "annotation_id": 5,
  "task_id": 1,
  "resource_id": 100,
  "version": 2,
  "message": "提交成功"
}
```

**说明**：如果任务设置了 `skip_review`，则自动标记为 `approved`，否则为 `submitted` 等待审核。

#### `GET /api/annotation/images/{resource_id}/history`

获取某图片在指定任务中的标注历史（所有版本）。

| Query 参数 | 类型 | 必填 | 说明 |
|------------|------|------|------|
| task_id | int | 是 | 标注任务 ID |

**响应** `AnnotationHistoryResponse`：
```json
{
  "resource_id": 100,
  "task_id": 1,
  "history": [{
    "annotation_id": 5,
    "task_id": 1,
    "resource_id": 100,
    "version": 2,
    "bboxes": [{"class_id": 1, "x": 0.1, "y": 0.2, "w": 0.15, "h": 0.25}],
    "review_status": "submitted",
    "created_by": 2,
    "updated_at": "..."
  }],
  "current_version": 2
}
```

---

### 2.5 模型管理

#### `POST /api/models`

注册模型。

**请求** `multipart/form-data`：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 权重文件 (`.pt` / `.pth` / `.onnx`) |
| name | string | 是 | 模型名称 |
| framework | string | 是 | `pytorch` / `tensorflow` / `onnx` |
| metadata | string(JSON) | 否 | 元信息，如输入尺寸、支持模态、类别列表等 |

**响应 `201`** `ModelResponse`：
```json
{
  "model_id": 1,
  "name": "yolo-visible-v1",
  "owner_id": 1,
  "framework": "onnx",
  "file_path": "/bucket/models/1/xxx.onnx",
  "meta_info": {"input_size": [640, 640], "modalities": ["visible"]},
  "is_baseline": false,
  "is_public": true,
  "status": "available",
  "created_at": "..."
}
```

#### `GET /api/models`

我的模型列表。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| framework | string | `pytorch` / `tensorflow` / `onnx` |
| status | string | `available` / `deprecated` / `pending` |
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

#### `GET /api/models/baselines`

平台基线模型（只读）。返回 `list[ModelResponse]`。

#### `GET /api/models/{model_id}`

模型详情 + 版本列表。

**响应** `ModelDetailResponse`（继承 `ModelResponse`，增加 `versions` 字段）：
```json
{
  "model_id": 1,
  "name": "...",
  "versions": [{
    "version_id": 10,
    "version_number": "1.0.0",
    "file_path": "...",
    "trained_on_dataset_id": 3,
    "change_note": "initial",
    "created_at": "..."
  }]
}
```

#### `POST /api/models/{model_id}/versions`

上传模型新版本。

**请求** `multipart/form-data`：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 新权重文件 |
| version_note | string | 否 | 版本说明 |
| trained_on_dataset_id | int | 否 | 训练所用数据集 ID |

**响应 `201`** `ModelVersionResponse`

#### `PUT /api/models/{model_id}/visibility`

设置模型可见性。

**请求体** `ModelVisibilityRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| is_public | bool | 是否公开 |

**响应** `ModelResponse`

#### `DELETE /api/models/{model_id}`

废弃模型（`status` → `deprecated`，非物理删除）。**响应 `204`**。

---

### 2.6 训练任务

#### `POST /api/train/tasks`

提交训练任务。

**请求体** `TrainTaskCreate`：
| 字段 | 类型 | 说明 |
|------|------|------|
| model_id | int | 模型 ID |
| dataset_id | int | 数据集 ID（需 `frozen`） |
| config | object | 训练配置 `{epochs, batch_size, lr, optimizer}` |
| gpu_config | object | GPU 配置 `{gpu_count, gpu_type}` |

**响应 `201`** `TrainTaskResponse`：
```json
{
  "task_id": 1,
  "model_id": 1,
  "dataset_id": 3,
  "status": "pending_approval",
  "progress": null,
  "started_at": null,
  "finished_at": null,
  "error_log": null
}
```

#### `POST /api/train/tasks/{task_id}/enqueue`

将训练任务入队（Phase1 辅助接口，后续由管理员审批替代）。

**响应** `TrainTaskResponse`

#### `GET /api/train/tasks/{task_id}`

查看训练进度。返回 `TrainTaskResponse`。

#### `POST /api/train/tasks/{task_id}/stop`

终止训练。返回 `TrainTaskResponse`。

#### `GET /api/train/tasks/{task_id}/logs`

读取训练日志（Redis Stream）。

**响应**：
```json
{"lines": ["epoch 1 loss=...", "epoch 2 loss=..."]}
```

---

### 2.7 推理任务

#### `POST /api/infer/tasks`

提交推理任务。

**请求体** `InferTaskCreate`：
| 字段 | 类型 | 说明 |
|------|------|------|
| model_id | int | 模型 ID |
| dataset_id | int | 数据集 ID（与 image_id 二选一） |
| image_id | int | 图片 ID（与 dataset_id 二选一） |

**响应 `201`** `InferTaskResponse`

#### `GET /api/infer/tasks/{task_id}/results`

查看推理结果。

| Query 参数 | 类型 | 默认值 | 说明 |
|------------|------|--------|------|
| class_filter | int | — | 按类别过滤 |
| min_confidence | float | 0.1 | 最低置信度 (0.0–1.0) |

**响应** `InferTaskResponse`（含 `results.detections` 数组）

#### `GET /api/infer/tasks/{task_id}/visualize/{image_id}`

返回叠加框可视化图片（`image/jpeg`）。

---

### 2.8 评测分析

#### `POST /api/eval/tasks`

发起评测任务。

**请求体** `EvalTaskCreate`：
| 字段 | 类型 | 说明 |
|------|------|------|
| model_id | int | 模型 ID |
| model_version_id | int | 模型版本 ID（可选） |
| dataset_id | int | 数据集 ID（需 `frozen`） |
| metric_config | object | 评测配置，默认 `{iou_thresholds:[0.5,0.75], max_detections:100}` |

**响应 `201`** `EvalTaskResponse`

#### `GET /api/eval/tasks/{task_id}`

查询评测任务状态。返回 `EvalTaskResponse`。

#### `GET /api/eval/tasks/{task_id}/metrics`

获取评测核心指标。

**响应** `EvalMetricsResponse`：
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
  "per_class_metrics": [{"category_id": 1, "name": "电线杆", "ap50": 0.80}],
  "per_size_metrics": {"small": 0.31, "medium": 0.55, "large": 0.70},
  "per_scene_metrics": null
}
```

#### `GET /api/eval/tasks/{task_id}/pr-curve`

PR 曲线数据。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| class_id | int | 按类别筛选（可选） |

**响应**：
```json
{"points": [[0.0, 1.0], [0.1, 0.95], [1.0, 0.0]], "class_id": null}
```

#### `GET /api/eval/tasks/{task_id}/confusion`

混淆矩阵。

**响应**：
```json
{"matrix": [[10, 1], [2, 8]], "labels": ["电线杆", "桥梁"]}
```

#### `GET /api/eval/tasks/{task_id}/errors`

错题本样本。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| error_type | string | `fp` / `fn` / `tp` |
| class_id | int | 按类别筛选 |
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

**响应** 标准分页

#### `POST /api/eval/compare`

多模型对比（最多 5 个模型，同一数据集）。

**请求体** `EvalCompareRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| model_ids | int[] | 模型 ID 列表，最多 5 个 |
| dataset_id | int | 数据集 ID |

**响应**（雷达图六维）：
```json
{
  "axes": ["mAP50", "mAP50_95", "precision", "recall", "fps", "lightweight"],
  "series": [{"model_id": 1, "name": "...", "values": [0.72, 0.45, 0.81, 0.68, 0.6, 0.7]}]
}
```

#### `GET /api/eval/leaderboard`

天梯榜。

| Query 参数 | 类型 | 必填 | 说明 |
|------------|------|------|------|
| dataset_id | int | 是 | 数据集 ID |

**响应** 按 mAP 降序排列：
```json
{
  "items": [{"result_id": 1, "model_id": 1, "model_name": "...", "dataset_id": 5, "mAP50": 0.72, "mAP50_95": 0.45, "created_at": "..."}]
}
```

#### `GET /api/eval/history/{model_id}`

单模型历史趋势（同模型各版本指标，含 `regression` 回归标记）。

| Query 参数 | 类型 | 必填 | 说明 |
|------------|------|------|------|
| dataset_id | int | 是 | 数据集 ID |

**响应**：
```json
{
  "items": [{"result_id": 1, "task_id": 3, "mAP50": 0.72, "mAP50_95": 0.45, "created_at": "...", "regression": false}]
}
```

---

## 三、审核员接口（角色 `reviewer` / `admin`）

审核员拥有普通用户的**全部权限**，并额外拥有以下接口：

### 3.1 数据集审核

#### `GET /api/review/datasets`

待审核数据集列表。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |
| claimed_only | bool | 仅看我已认领的，默认 false |

**响应** `DatasetReviewListResponse`

#### `POST /api/review/datasets/{dataset_id}/claim`

认领数据集审核任务。

**响应**：
```json
{"message": "认领成功", "dataset_id": 1, "reviewer_id": 2}
```

#### `POST /api/review/datasets/{dataset_id}/verdict`

提交数据集审核结果。

**请求体** `DatasetVerdictRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| verdict | string | `approved` / `rejected` |
| notes | string | 审核意见 |

**响应** `DatasetVerdictResponse`

---

### 3.2 标注审核

#### `GET /api/review/annotation-tasks`

待审核标注任务列表。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

**响应** `AnnotationReviewListResponse`

#### `POST /api/review/annotations/{annotation_id}/verdict`

提交标注审核结果。

**请求体** `AnnotationVerdictRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| verdict | string | `approved` / `rejected` |
| reject_reasons | object[] | 驳回原因 |

**响应** `AnnotationVerdictResponse`

---

## 四、管理员接口（角色 `admin`）

管理员拥有审核员的**全部权限**，并额外拥有以下接口：

### 4.1 用户管理

#### `GET /api/admin/users`

用户列表。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| role | string | `admin` / `reviewer` / `normal` |
| is_active | bool | 按激活状态筛选 |
| keyword | string | 用户名或邮箱关键字 |
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

**响应** `AdminUserListResponse`

#### `POST /api/admin/users`

创建新用户。

**请求体** `AdminUserCreateRequest`：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 3–50 字符 |
| email | EmailStr | 是 | 合法邮箱 |
| password | string | 是 | 6–100 字符 |
| role | string | 否 | `admin` / `reviewer` / `normal`，默认 `normal` |

**响应 `201`** `AdminUserResponse`

#### `PUT /api/admin/users/{user_id}/role`

修改用户角色。

**请求体** `RoleUpdateRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| role | string | `admin` / `reviewer` / `normal` |

#### `PUT /api/admin/users/{user_id}/status`

冻结 / 解冻用户。

**请求体** `StatusUpdateRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| is_active | bool | true=激活，false=冻结 |

---

### 4.2 标签体系管理

#### `GET /api/admin/labels`

标签体系列表。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

**响应** `LabelSchemaListResponse`

#### `POST /api/admin/labels`

新增标签体系。

**请求体** `LabelSchemaCreateRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| name | string | 标签体系名称 |
| categories | object[] | 类别列表 |

**响应 `201`** `LabelSchemaResponse`

#### `POST /api/admin/labels/{schema_id}/categories`

向标签体系新增类别。

**请求体** `AddCategoryRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| category | object | 类别定义（`name` / `color` 等） |

**响应** `CategoryResponse`

---

### 4.3 推理审批

#### `GET /api/admin/infer-tasks/pending`

待审批推理任务列表。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

**响应** `InferTaskPendingListResponse`

---

### 4.4 天梯治理

#### `GET /api/admin/eval/leaderboard`

查看所有评测结果（含非公开），用于治理。

| Query 参数 | 类型 | 说明 |
|------------|------|------|
| dataset_id | int | 按数据集筛选（可选） |
| page | int | 默认 1 |
| size | int | 默认 20，≤100 |

**响应** `LeaderboardGovernanceResponse`

#### `POST /api/admin/eval-results/{result_id}/invalidate`

作弊下架（将评测结果标记无效，从排行榜移除）。

**请求体** `EvalResultInvalidateRequest`：
| 字段 | 类型 | 说明 |
|------|------|------|
| reason | string | 下架原因说明 |

**响应**：
```json
{"result_id": 1, "model_id": 1, "message": "评测结果已下架，原因: 作弊行为"}
```

---

## 附录 A：HTTP 状态码约定

| 状态码 | 场景 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 204 | 成功无 Body（登出、废弃模型） |
| 400 | 参数校验失败 / 业务前置不满足 |
| 401 | 未登录或 Token 无效 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 409 | 冲突（用户名重复等） |
| 422 | Pydantic 校验失败 |
| 500 | 服务器内部错误 |

---

## 附录 B：接口数量统计

| 模块 | 数量 | 角色 |
|------|------|------|
| 系统 | 1 | 公开 |
| 鉴权 | 4 | 公开 |
| 个人信息 | 3 | 普通用户 |
| 数据资源 | 8 | 普通用户 |
| 数据集 | 17 | 普通用户 |
| 标注 | 7 | 普通用户 |
| 模型管理 | 7 | 普通用户 |
| 训练任务 | 5 | 普通用户 |
| 推理任务 | 3 | 普通用户 |
| 评测分析 | 9 | 普通用户 |
| 审核 | 5 | 审核员 |
| 用户管理 | 4 | 管理员 |
| 标签管理 | 3 | 管理员 |
| 推理审批 | 1 | 管理员 |
| 天梯治理 | 2 | 管理员 |
| **合计** | **79** | |

---

## 附录 C：源文件映射

| 源文件 | 对应章节 |
|--------|----------|
| `api/v1/auth.py` + `main.py` | 一、公开接口 / 二.1 个人信息 |
| `api/v1/data.py` | 二.2 数据资源 |
| `api/v1/datasets.py` | 二.3 数据集 |
| `api/v1/annotations.py` | 二.4 标注 |
| `api/v1/models.py` | 二.5 模型管理 |
| `api/v1/train.py` | 二.6 训练任务 |
| `api/v1/infer.py` | 二.7 推理任务 |
| `api/v1/eval.py` | 二.8 评测分析 |
| `api/v1/review.py` | 三、审核员接口 |
| `api/v1/admin.py` | 四、管理员接口 |
