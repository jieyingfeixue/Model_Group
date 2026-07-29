# SAM3 建筑物分割 — 使用指南

## 当前状态

项目当前使用 **SAM2**（[src/models/segmentor.py](../src/models/segmentor.py)），仅支持 box/point prompt，
不支持文本 prompt。SAM3 发布后可直接升级。

## SAM2 vs SAM3 对建筑物标注的区别

| 能力 | SAM2 (当前) | SAM3 (目标) |
|------|------------|------------|
| Box prompt | ✅ `segment(image, bbox=(x1,y1,x2,y2))` | ✅ 继承 |
| Point prompt | ✅ 点击正/负样本点 | ✅ 继承 |
| Text prompt | ❌ 不支持 | ✅ `segment(image, text="building")` |
| 全景分割 | ❌ 需 grid point 扫描 | ✅ 原生 `segment_everything` |
| 类别标签 | ❌ 只输出 mask，无类别 | ✅ mask + class name |
| Temporal propagation | ❌ | ✅ 跨帧传播 mask identity |

**SAM2 做建筑物标注的关键限制**：必须先由用户画框或点击，无法说"把所有建筑物标出来"。
SAM3 的 text prompt 可以直接用 `"building"` 触发全景分割并自动筛选建筑类别。

---

## 集成方案

### 1. 扩展 Segmentor 接口（[src/models/segmentor.py](../src/models/segmentor.py)）

在现有 `Segmentor` 类中新增 text-prompt 方法：

```python
def segment_with_text(
    self,
    image: np.ndarray,        # HxWx3 RGB uint8
    text: str,                # "building" / "building. house. structure"
    box: tuple | None = None, # 可选空间约束 (x1,y1,x2,y2)
) -> list[dict]:
    """SAM3 text-prompted segmentation → list of {mask, bbox, score, label}."""
    ...
```

### 2. 新增 `SAM3Segmentor` 后端

```python
# src/models/segmentor.py 新增

def _try_load_sam3(self) -> bool:
    """Load SAM3 model with text encoder."""
    try:
        # SAM3 预期通过 HuggingFace transformers 或官方 sam3 包发布
        from transformers import Sam3Model, Sam3Processor
    except ImportError:
        logger.info("SAM3 not available")
        return False

    device = self._resolve_device()
    try:
        self._processor = Sam3Processor.from_pretrained(self.hf_model_id)
        self._model = Sam3Model.from_pretrained(self.hf_model_id).to(device).eval()
        self._backend = "sam3"
        logger.info("Loaded SAM3 (%s) on %s", self.hf_model_id, device)
        return True
    except Exception as exc:
        logger.warning("SAM3 load failed: %s", exc)
        return False
```

### 3. 配置切换

```yaml
# config/default.yaml
models:
  segmentor:
    name: "sam3"                                      # sam3 | sam2 | auto
    hf_model_id: "facebook/sam3-hiera-large"          # SAM3 HF model id (待确认)
    device: "cuda"
    text_prompt: "building. structure. house. wall. facade."  # 默认文本提示
    conf_threshold: 0.3
    mask_min_area: 200                                # 过滤 <200px 碎片
    nms_iou_threshold: 0.7                            # 合并重叠度 >0.7 的 mask
```

---

## 端到端工作流

### 用户视角

```
1. 打开一帧图像 (Page 2 MultiViewAnnotation)
2. 点击 "SAM3 建筑标注" 按钮（或按 B 键）
3. SAM3 自动:
   a. 文本 prompt "building" 触发全景分割
   b. 输出所有建筑物 mask
   c. 每个 mask → 2D bbox
   d. 结合深度图 → 3D 初始框
4. 人工核验: 拖拽调整 / 删除误检 / 补充漏检
5. 切到下一帧 → SAM3 propagation 继承上一帧 mask
```

### 代码调用链

```
GUI 按钮 "SAM3 建筑标注"
  │
  ▼
Segmentor.segment_with_text(image, text="building. structure. house")
  │
  ├─ SAM3 前向推理 (text encoder + image encoder + mask decoder)
  ├─ 输出: [{mask, bbox_xyxy, score, class_name}, ...]
  │
  ├─ 后处理:
  │   ├─ 过滤 mask_min_area < 200px
  │   ├─ NMS 合并 IOU > 0.7
  │   └─ 形态学闭运算填充孔洞
  │
  ▼
每个 bbox → box_from_2d_v3.fit_box_with_sam2()
  │
  ├─ 深度估计 (Depth Anything v2)
  ├─ DBSCAN 聚类 (有 LiDAR 时)
  ├─ L-shape BEV 拟合 → yaw + dims
  └─ → Label3D (class_name="building")
  │
  ▼
SessionState.boxes.append(...)  →  UI 刷新
```

---

## 实际代码示例

### A. 单张图像自动标注所有建筑物

```python
import cv2
import numpy as np
from src.models.segmentor import Segmentor

# 初始化 (使用 SAM3 config)
seg_config = {
    "enabled": True,
    "name": "sam3",
    "hf_model_id": "facebook/sam3-hiera-large",
    "device": "cuda",
    "conf_threshold": 0.3,
}
segmentor = Segmentor(seg_config)

# 加载图像
image = cv2.imread("frame_000001.jpg")
image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

# SAM3 文本分割
buildings = segmentor.segment_with_text(
    image=image_rgb,
    text="building. structure. house. wall. facade.",
)

# 结果
for b in buildings:
    print(f"class={b['class_name']}, bbox={b['bbox']}, score={b['score']:.2f}")
    # b['mask']: H×W bool numpy array
    # b['bbox']: (x1, y1, x2, y2) int tuple
```

### B. 用户框选 + SAM3 精细化

```python
# 用户在 GUI 画出粗略的 2D 框
user_bbox = (320, 180, 800, 600)  # (x1, y1, x2, y2)

# SAM3 在框内做分割
mask = segmentor.segment_with_text(
    image=image_rgb,
    text="building",
    box=user_bbox,  # 空间约束: 只在这个框内找建筑
)
```

### C. 连续帧 propagation

```python
# 帧 1: 完整 SAM3 推理
masks_frame1 = segmentor.segment_with_text(image1, text="building")

# 帧 2: 用 propagation 加速 (mask identity 继承)
masks_frame2 = segmentor.propagate_to_next(
    prev_image=image1,
    prev_masks=masks_frame1,
    curr_image=image2,
)
# propagation 比重新推理快 5-10×
```

---

## 与现有管线集成

当前项目已有两种方式触发 SAM：

| 路径 | 代码位置 | SAM 使用方式 |
|------|----------|-------------|
| **A2: 用户画框 → SAM mask → 3D 拟合** | [box_from_2d_v3.py](../src/fusion/box_from_2d_v3.py) `fit_box_with_sam2()` | box prompt 精细化 mask |
| **B2: 一键自动标注 V2** | [auto_label_v2.py](../src/agent/auto_label_v2.py) | detector → SAM2 mask → frustum + DBSCAN |

SAM3 集成后，可新增：

| 新路径 | 触发方式 | SAM3 使用方式 |
|--------|----------|--------------|
| **C1: 一键建筑物标注** | GUI 按钮 / 快捷键 B | text prompt 全景分割 → 批量 3D 框 |
| **D1: 连续帧 propagation** | 切帧自动触发 | propagation 继承 mask identity |

---

## 模型加载策略

```
Segmentor._ensure_model()
  │
  ├─ name="sam3"  → _try_load_sam3()     # SAM3 (text prompt 支持)
  │                   └─ 失败 → 回退
  ├─ name="sam2"  → _try_load_sam2()     # SAM2-Hiera-L (box/point prompt)
  │                   └─ 失败 → 回退
  ├─ name="mobile_sam" → _try_load_mobile_sam()  # MobileSAM (快速 CPU)
  │                   └─ 失败 → 回退
  └─ 回退 → "stub"                       # 无 SAM, bbox-only 降级路径
```

---

## 注意事项

1. **SAM3 目前未正式发布**（2026-07）— 以上代码基于 SAM2 架构和 Meta 公开的 SAM3 预览信息预估。发布后需根据实际 API 调整 `_try_load_sam3()` 和 `segment_with_text()` 的实现。

2. **GPU 显存** — SAM 大模型 (Hiera-L) 约需 4-6 GB VRAM。LH 数据集的 1920×1200 图像可能需要先 resize 到 1024×1024 再推理。

3. **建筑物类别覆盖** — text prompt 可能需要覆盖多种表述：
   ```
   "building. house. structure. wall. facade. roof. apartment. tower."
   ```
   具体需要在实际数据上测试调优。

4. **propagation 的失效条件** — 当相机大幅移动（>5 帧间隔）或场景切换时，propagation 会丢失目标，
   此时应回退到完整 SAM3 推理。此逻辑由 `max_gap` 参数控制。

5. **SAM3 mask → 深度 → 3D 框** — mask 只给出像素级分割，深度仍需从雷达点云或 Depth Anything 获取。
   对于 LH 数据集，建筑深度主要由 GPS 目标匹配 (`target_depth_db.json`) 提供，这是最可靠的来源。
