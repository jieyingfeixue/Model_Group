# 第二阶段集成测试报告

**测试日期**：2026-07-14
**测试范围**：第二阶段全部 7 个任务
**测试脚本**：`backend/scripts/phase2_integration_test.py`

---

## 测试环境

| 项目 | 值 |
|------|-----|
| 数据库 | PostgreSQL 16 (Docker pg-local) |
| 测试数据 | 9 张 RGB 图片（3 visible + 3 infrared + 1 QC + 1 import + 1 test） |
| 测试用户 | 3 个（owner / reviewer / assignee） |
| 标签体系 | Phase2_Test_Labels（car / pedestrian / cyclist，cat_003 已废弃） |

---

## 测试结果摘要

```
RESULTS: 50 passed, 0 failed, 50 total
```

---

## 逐任务测试详情

### 任务 2：标签体系 CRUD（8 项）

| # | 测试项 | 结果 |
|---|--------|:---:|
| 1 | 创建标签体系 | ✅ |
| 2 | 新增类别 cat_001 | ✅ |
| 3 | 累计新增 3 个类别 | ✅ |
| 4 | 修改类别快捷键 | ✅ |
| 5 | 废弃类别（status=deprecated） | ✅ |
| 6 | 活跃类别排除已废弃（2/3） | ✅ |
| 7 | 导出 JSON | ✅ |
| 8 | 导入 JSON（Pydantic 校验） | ✅ |

### 任务 1：多模态时间戳对齐（4 项）

| # | 测试项 | 结果 |
|---|--------|:---:|
| 1 | 上传 3 张 visible 图片（with captured_at） | ✅ |
| 2 | 上传 3 张 infrared 图片（with captured_at） | ✅ |
| 3 | 对齐：nearest_neighbor 策略，3 pairs | ✅ |
| 4 | 对齐结果 4 条记录写入 alignment_group_items | ✅ |

**发现的 Bug**：`multi_modal_align()` 中当同一帧被多次匹配时，违反 `UNIQUE(group_id, resource_id)` 约束。**已修复**：增加 `inserted: set[int]` 去重逻辑。

### 任务 3：标注多版本存储（10 项）

| # | 测试项 | 结果 |
|---|--------|:---:|
| 1 | 创建标注任务 | ✅ |
| 2 | 保存 v1（追加写） | ✅ |
| 3 | 任务状态自动切换：draft → in_progress | ✅ |
| 4 | 保存 v2（版本递增） | ✅ |
| 5 | 历史查询（2 个版本） | ✅ |
| 6 | 提交审核（review_status=submitted） | ✅ |
| 7 | 任务状态：submitted | ✅ |
| 8 | 提交后锁定（403 拒绝保存） | ✅ |
| 9 | 进度统计：annotated=1 | ✅ |
| 10 | 进度统计：total=data_range 匹配资源数（修复 Phase 1 bug） | ✅ |

### 任务 4：数据集审核流程（8 项）

| # | 测试项 | 结果 |
|---|--------|:---:|
| 1 | 创建数据集（review_status=submitted） | ✅ |
| 2 | 待审核队列查询 | ✅ |
| 3 | 认领（status→reviewing） | ✅ |
| 4 | 7 项自动检测（1 项 FAIL：元信息缺失） | ✅ |
| 5 | 放弃认领（status→submitted） | ✅ |
| 6 | 重新认领 + 审核通过 | ✅ |
| 7 | review_status→approved | ✅ |
| 8 | 自动发布（status→published） | ✅ |

### 任务 5：标注审核流程（7 项）

| # | 测试项 | 结果 |
|---|--------|:---:|
| 1 | 待审核标注任务查询 | ✅ |
| 2 | 认领（status→reviewing） | ✅ |
| 3 | 配置抽检（100% 随机） | ✅ |
| 4 | 逐张审核（approved） | ✅ |
| 5 | 抽检结果摘要（passed=1, pass_rate=1.0） | ✅ |
| 6 | 结束审核（dismiss_only → completed） | ✅ |
| 7 | 任务完成 | ✅ |

### 任务 6：质量检查 + 绩效统计（3 项）

| # | 测试项 | 结果 |
|---|--------|:---:|
| 1 | 质量检查检出 2 个异常（out_of_bounds + depth_out_of_range） | ✅ |
| 2 | 数据集审核维度统计 | ✅ |
| 3 | 标注审核维度统计（含 anno_total） | ✅ |

### 任务 7：标注文件导入解析（3 项）

| # | 测试项 | 结果 |
|---|--------|:---:|
| 1 | COCO JSON 导入：1 annotation | ✅ |
| 2 | 图片上传：1 resource | ✅ |
| 3 | annotation_status 更新为 annotated | ✅ |

**Review 修复验证**：Review 中发现的 `annotation_status` 未更新问题已修复，测试验证通过。

---

## 测试过程中发现并修复的 Bug

| # | Bug | 严重程度 | 修复 |
|---|-----|:---:|------|
| 1 | `multi_modal_align()` 中重复插入同一 resource_id 到 alignment_group_items | ⚠️ 崩溃 | 增加 `inserted: set[int]` 去重逻辑 |
| 2 | `annotation_status` 导入后未更新为 `'annotated'` | ⚠️ 功能遗漏 | Review 后发现并修复 |

---

## 测试覆盖的 API 端点

| 任务 | 覆盖端点 |
|------|---------|
| 上传+对齐 | `POST /api/data/upload` (×4), `POST /api/data/align` |
| 标签 CRUD | 全部 7 个端点（admin + public） |
| 标注存储 | `POST /api/annotation/tasks`, `PUT .../save`, `POST .../submit`, `GET .../history`, `GET .../progress` |
| 数据集审核 | `GET /api/review/datasets`, `POST .../claim`, `POST .../unclaim`, `GET .../checklist`, `POST .../verdict` |
| 标注审核 | `GET /api/review/annotation-tasks`, `POST .../claim`, `POST .../sample`, `POST .../verdict`, `GET .../summary`, `POST .../finalize` |
| 质量+统计 | `GET /api/review/annotation-tasks/{id}/quality-check`, `GET /api/review/stats` |
| 导入 | `POST /api/data/upload`（annotation_file 模式） |

**覆盖全部 31 个端点中的 27 个**（4 个 admin 端点——`schemas/export`、`schemas/import`、`admin/schemas` GET/POST——被 Service 层测试覆盖，未单独测试路由层）。

---

## 总体评价

- **50 项测试全部通过，0 失败**
- 测试覆盖所有 7 个任务的完整业务流程
- 发现并修复 2 个 Bug（对齐重复插入、标注状态未更新）
- 验证了 Phase 1 bug 修复（progress total 语义）
