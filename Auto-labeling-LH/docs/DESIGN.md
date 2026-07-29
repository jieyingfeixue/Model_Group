# Auto-Labeling 应用设计文档

> 多传感器（LiDAR + 相机 + 4D 雷达）开放词汇 3D 自动标注桌面应用。
> 主要数据集：K-Radar v2.1，可通过 adapter 模式扩展其他数据集。

---

## 1. 项目概览

| 项 | 说明 |
|----|------|
| 形态 | PyQt6 桌面 GUI（可打包为 PyInstaller one-dir EXE） |
| 入口 | [run.py](../run.py) → [src/main.py](../src/main.py) → `MainWindow(config)` |
| 配置 | [config/default.yaml](../config/default.yaml) + [profiles/kradar.yaml](../profiles/kradar.yaml) |
| 打包 | [auto_labeling.spec](../auto_labeling.spec)，运行钩子 [hooks/rthook_qt6.py](../hooks/rthook_qt6.py) |
| 模型权重 | `models/`（YOLOv8x、Depth-Anything v2、可选 SAM/SAM2） |
| 主数据集 | K-Radar，通过 [src/io/adapters/kradar_adapter.py](../src/io/adapters/kradar_adapter.py) 接入 |

设计目标：
1. **少人工**：一键（Space）触发完整 5-stage pipeline，输出可信的 3D 标注。
2. **多模态融合**：图像 2D 检测 + 单目深度 + LiDAR 拟合 + 4D 雷达 ROI 验证。
3. **可审查**：每个候选框带置信度与决策来源（rule / LLM / vision），人工可接受/驳回。
4. **可离线**：核心 detector / depth / SAM 全部支持本地推理，无需联网。

---

## 2. 顶层架构

```
┌───────────────────────────────────────────────────────────────────┐
│                          MainWindow (PyQt6)                       │
│  Toolbar | StageBar | StatusBar | FrameNavigator | 多 Page 切换   │
└───────────────────────────────────────────────────────────────────┘
            │                              │
            ▼                              ▼
   ┌─────────────────┐           ┌─────────────────────┐
   │  AutoPipeline   │  ←──────  │  MultiViewAnnotation │ (主标注页)
   │ (core/pipeline) │           │ (ui/pages/...)       │
   └────────┬────────┘           └─────────┬───────────┘
            │                              │
            ▼                              ▼
   ┌─────────────────────────────────────────────────────┐
   │       FrameData (core/types.FrameData)              │
   │  images / pointclouds / radar_tensors /             │
   │  calibration / labels                               │
   └─────────────────────────────────────────────────────┘
            ▲
            │ load_frame()
   ┌────────┴──────────────────────────────────────────┐
   │  io/adapters/kradar_adapter.py                    │
   │  io/calibration.py / io/label_io.py /             │
   │  io/sensor_profile.py                             │
   └───────────────────────────────────────────────────┘
```

---

## 3. 数据加载与标定

### 3.1 Profile 体系 — [src/io/sensor_profile.py](../src/io/sensor_profile.py)

YAML 描述每个传感器的：路径模板、内参来源、外参来源、立体裁剪、视图配置。

```yaml
sensors:
  camera_front: { type: camera, intrinsics_source: static, ... }
  lidar_os2:    { type: lidar, ... }
  radar_4d:     { type: radar, tensor_axes: [z,y,x], ... }
viewer:
  camera_stereo_crop: { cam-front: left, cam-left: left, ... }
labels:
  format: kradar
```

### 3.2 K-Radar Adapter — [src/io/adapters/kradar_adapter.py](../src/io/adapters/kradar_adapter.py)

`load_frame(root, profile, seq_id, frame_id) -> FrameData` 完成：

1. **解析 label 头**：`* idx(tesseract_os2-64_cam-front_os1-128_cam-lrr)=...` 取每个传感器对应的帧号。
2. **图像加载**：保留 K-Radar 原始 2560×720 立体对（不在 adapter 裁剪，由 UI/pipeline 按 profile 决定 left/right）。
3. **LiDAR**：优先 `os2-64`（label 与该 LiDAR 对齐），不做任何 shift（保留 raw 帧，详见 §3.4）。
4. **相机标定**：
   - 优先级：`resources/calib_seq_v2/seq_NN/cam_X.yml`（per-seq 真值）
   - 回退：硬编码 `_KRADAR_T_LDR2CAM`（仅 cam-front）
   - Euler 顺序：`scipy.from_euler('zyx', [yaw, pitch, roll], deg)` ≡ `Rx(roll) @ Ry(pitch) @ Rz(yaw)`（手写矩阵时易错）
5. **去畸变 + 立体裁剪**：`_undistort_camera_images()` 严格复刻 K-Radar `util_calib.show_projected_point_cloud(undistort=True)` 流程（见 §3.3）。
6. **覆盖（override）**：`profiles/kradar_calib_overrides.json` 支持 per-seq / per-cam 的 `delta_xyz` + `delta_rpy` 微调。

### 3.3 K-Radar 官方 undistort 复刻（关键修复点）

K-Radar 视觉化基线写法不严谨但是事实标准：

```python
ncm, _ = cv2.getOptimalNewCameraMatrix(K, dist, (w,h), alpha=0)
for j,i: K[j,i] = ncm[j,i]            # K 被覆盖为 ncm（非常规！）
map_x, map_y = cv2.initUndistortRectifyMap(
    K, dist, None, ncm, (w,h), cv2.CV_32FC1)   # cameraMatrix 也是 ncm
img_u = cv2.remap(img_left, map_x, map_y, cv2.INTER_LINEAR)
```

教科书式正确写法 (`initUndistortRectifyMap(K_orig, ...)`) 与上式生成的图像 mean diff ≈ 6.4 灰度级 → 点云"看起来没贴合"。

`_undistort_camera_images` 内必须 `K_for_map = ncm.copy()` 后再传入 `initUndistortRectifyMap`，得到与 [temp/render_v21_B.py](../temp/render_v21_B.py) 逐像素相同的底图。

去畸变后：
- `fd.images[cam]` ← 去畸变 LEFT-half（1280×720）
- `fd.calibration.intrinsics[cam]` ← `(ncm, distortion=0)`
- `project_3d_to_image` 走纯线性 `K @ p / z` 路径，与官方 `T_ldr2pix = T_cam2pix @ T_ldr2cam_4` 数学等价

实测 4 个相机（front/left/right/rear）逐像素 diff = 0。

### 3.4 LiDAR / Label 帧约定（曾经踩过的坑）

| 项 | 选择 | 原因 |
|---|---|---|
| LiDAR | OS2-64 raw，**不**叠加 `calib_radar_lidar` 的 (dx,dy,0.7) | per-seq YAML 外参就是按 raw LiDAR 标定的 |
| Label v2.1 | raw（不 shift） | 与上同帧 |
| OS1-128 | 不用 | 与 radar/label 无官方标定 |
| 立体相机 | `cam-front: left`（1280 列） | 右半视差导致整体偏移，非标定错误 |

详见 [memory:repo/kradar-camera-frame.md](../docs/plans/) 中的历史记录。

### 3.5 类型核心 — [src/core/types.py](../src/core/types.py)

```python
@dataclass
class CalibrationBundle:
    intrinsics: dict[str, CameraIntrinsics]
    extrinsics: dict[str, np.ndarray]   # sensor → 4×4 (LiDAR→cam)
    def project_3d_to_image(pts, camera) -> Nx2:
        # distortion ≠ 0 → cv2.projectPoints
        # distortion == 0 → 纯线性 K @ p / z

@dataclass
class FrameData:
    seq_id, frame_id
    images: dict[str, ndarray]
    pointclouds: dict[str, ndarray]
    radar_tensors: dict[str, ndarray]
    calibration: CalibrationBundle
    labels: list[Label3D]
```

---

## 4. 一键自动标注 Pipeline

两套并存，由用户在 UI 选择：

### 4.1 经典 5-stage Pipeline — [src/core/pipeline.py](../src/core/pipeline.py)

`AutoPipeline.run(frame)` 异步执行：

| Stage | 模块 | 职责 |
|-------|------|------|
| 1. detect    | [models/detector_2d.py](../src/models/detector_2d.py) | YOLOv8 / Grounding DINO 2D 检测，所有相机并行 |
| 2. project   | [fusion/image_to_3d.py](../src/fusion/image_to_3d.py) + [fusion/depth_anything_metric.py](../src/fusion/depth_anything_metric.py) | 单目深度 + 2D bbox → 3D 中心 |
| 3. lidar_fit | [fusion/lidar_fitting.py](../src/fusion/lidar_fitting.py) + [fusion/lshape_fit.py](../src/fusion/lshape_fit.py) | 视锥内 LiDAR 聚类 + L-shape yaw |
| 4. radar_map | [fusion/radar_projection.py](../src/fusion/radar_projection.py) | 4D 雷达 ROI 提取，统计功率 |
| 5. agent     | [agent/](../src/agent/) | 规则 + LLM + Vision 融合决策 |

输出：`SessionState`，每个 box 带 `FinalDecision(confidence, source, reason)`。

### 4.2 B2-MVP V2 Pipeline — [src/agent/auto_label_v2.py](../src/agent/auto_label_v2.py)

更轻量、单帧多相机融合：

```
所有相机:
  detector → SAM2 mask → frustum + DBSCAN → fit_box_with_sam2
合并:
  按 BEV IoU 做 3D NMS（_nms_3d_bev）
排序:
  按 score × log(box_density) 排序
返回:
  Top-K 候选 Label3D，UI 追加（不替换用户已有框）
```

### 4.3 模型管理 — [src/models/model_manager.py](../src/models/model_manager.py)

懒加载、统一接口：
- `Detector2D`：YOLOv8 (.pt / .onnx) 或 Grounding DINO (transformers)
- `DepthEstimator`：Depth-Anything v2 (torch / onnx / lidar projection 回退)
- `Segmentor`：SAM2-Hiera-L / MobileSAM / SAM v1 / stub（在 `fit_quality` 配置下自适应）

---

## 5. Agent 决策系统 — [src/agent/](../src/agent/)

三路并行 → 合并：

### 5.1 RuleEngine ([rule_engine.py](../src/agent/rule_engine.py))
零延迟确定性检查：
- LiDAR 支持点数下限（`lidar_min_points: 3`，0 → delete）
- 维度先验偏差（`σ` 阈）
- BEV IoU 重叠
- 地面穿透
- yaw 与 LiDAR PCA 一致性

### 5.2 LLMAgent ([llm_agent.py](../src/agent/llm_agent.py) + [tool_executor.py](../src/agent/tool_executor.py))
- Provider：Anthropic Claude 4 Sonnet（默认）/ GPT-4.1 fallback
- 多轮 tool calling（最多 20 轮）
- 工具：`get_box_info`、`adjust_box`、`delete_box`、`refit_box_to_lidar`、`merge_boxes`、`split_box`、`get_neighbours`、`query_class_prior`、`get_radar_signature`、`final_decision`

### 5.3 VisionAgent ([vision_agent.py](../src/agent/vision_agent.py))
- Qwen2.5-VL-72B（本地 vLLM 或 DashScope API）
- 把 3D 框投影到图像，VLM 验证类别 / 对齐 / 是否多框

### 5.4 DecisionMerger ([decision_merger.py](../src/agent/decision_merger.py))
| Confidence | 行为 |
|---|---|
| ≥ 0.85 | `auto_apply` |
| 0.5 – 0.85 | `ask_human` |
| < 0.5 | `info_only` |

`max_auto_adjustments_per_frame: 10` 防止 LLM 失控。

---

## 6. UI 设计 — [src/ui/](../src/ui/)

### 6.1 主窗口结构 — [src/ui/main_window.py](../src/ui/main_window.py)
```
┌─ Toolbar (open / save / sequence / pipeline buttons) ──────┐
│─ StageBar (5-stage progress) ──────────────────────────────│
├─ Page 切换 (Tabs) ─────────────────────────────────────────┤
│  • DatasetBrowser    → 选 dataset / 序列                   │
│  • SceneFrameBrowser → 序列内浏览 / 缩略图                 │
│  • MultiViewAnnotation → 主标注（多相机 + 3D + 雷达）     │
│  • LidarRadarSync    → LiDAR / Radar 时空对齐校验         │
│  • Completion        → 帧标注完成度统计                   │
├─ FrameNavigator (← →  / A D / 滑块) ───────────────────────┤
└─ StatusBar (帧 / agent / 模型设备) ────────────────────────┘
```

### 6.2 主标注页 — [ui/pages/multiview_annotation.py](../src/ui/pages/multiview_annotation.py)
- **CameraImageView**（QGraphicsView 子类）
  - `set_image` / `draw_boxes_3d`（可拖拽手柄）/ `draw_gt_labels`（青色虚线）/ `draw_lidar_overlay`（彩虹深度点）/ `draw_detections_2d`
  - 工具：select / add_box / pan / zoom；右键 = pan
  - `_show_camera`：跳过宽度 ≤1500 的二次裁剪（adapter 已裁过）
- **PointCloudView**（pyvistaqt）
  - 3D 点云 + 框 + GT 框 + 选中高亮
  - 右键合成左键 orbit（VTK observer + Qt eventFilter，详见 user memory `vtk-pyqt-gotchas.md`）
- **AnnotationTable** + **BoxEditor**：直接修改 x/y/z/yaw/l/w/h
- **AgentPanel**：决策列表，accept/reject 按钮
- **CalibrationTunePanel**：实时微调外参 → 写回 `kradar_calib_overrides.json`

### 6.3 Panels — [ui/panels/](../src/ui/panels/)
- `image_panel`、`pointcloud_panel`、`radar_panel`（matplotlib BEV 热图）
- `agent_panel`、`annotation_table`、`calibration_tune_panel`

---

## 7. 会话与持久化 — [src/core/session.py](../src/core/session.py)

- `SessionState`：当前帧的所有 box + decisions + 历史
- 自动保存：每 60s（可配）→ `Auto-labeling/sessions/<hash>.json`
- Undo/Redo：栈深 50
- 完成度：`completion.py` 统计已审帧数

---

## 8. 导出 — [src/export/](../src/export/)

| 格式 | 模块 | 行格式 |
|---|---|---|
| K-Radar | [formats/kradar_writer.py](../src/export/formats/kradar_writer.py) | `*, R, idx, class, x, y, z, yaw_deg, l/2, w/2, h/2` |
| KITTI   | [formats/kitti_writer.py](../src/export/formats/kitti_writer.py)   | `Type, ..., dims, location, rotation_y` |
| JSON    | [writer.py](../src/export/writer.py) | 完整 frame + metadata |

---

## 9. 配置 ([config/default.yaml](../config/default.yaml))

关键开关（节选）：
```yaml
models:
  device: cpu | cuda
  detector: { name: yolo_pt | grounding_dino, conf_threshold: 0.35 }
  depth:    { name: torch_depth, max_depth: 80.0 }
  segmentor:{ enabled: true, hf_model_id: facebook/sam2-hiera-large }
  fit_quality: auto         # fast | full | auto | none

agent:
  enabled: true
  llm_agent:    { provider: anthropic, model: claude-sonnet-4 }
  vision_agent: { provider: local, endpoint: http://localhost:8000/v1 }
  decision: { auto_apply_threshold: 0.85, ask_human_threshold: 0.5 }
```

---

## 10. 打包与运行

| 模式 | 命令 |
|---|---|
| 开发 | `Auto-labeling/run_dev.ps1`（venv + `python run.py`） |
| 构建 EXE | `Auto-labeling/build.ps1` → `dist/AutoLabeling/AutoLabeling.exe` |
| 模型下载 | `Auto-labeling/download_models.ps1` |

PyInstaller spec 排除 `torch` / `transformers`（运行时按需加载，避免 EXE 过大）；Qt 插件路径由 `hooks/rthook_qt6.py` 在 frozen 模式下修正。

---

## 11. 已验证关键不变量

1. **相机投影 ↔ K-Radar 官方一致**：4 相机 × 序列 1 / 帧 00033_00001，去畸变底图与点云/GT 框逐像素 diff = 0。
2. **不 shift LiDAR / labels**：OS2-64 raw + per-seq YAML 外参就是 K-Radar 标注工具的真值帧。
3. **LEFT 半立体**：所有 cam-* 必须 `camera_stereo_crop: left`，RIGHT 半视差导致 ~12cm 物理偏移。
4. **`scipy.from_euler('zyx', [yaw,pitch,roll]) == Rx @ Ry @ Rz`**（反直觉，必须按 scipy 实测）。
5. **K-Radar 官方 ncm-overwrite undistort 写法**：`_undistort_camera_images` 必须复刻，否则底图错位约 6 灰度级。

---

## 12. 验证脚本

- [temp/render_v21_B.py](../temp/render_v21_B.py)：纯 K-Radar 官方流程，作为对齐基线（ground truth 渲染）
- [temp/render_v21_app.py](../temp/render_v21_app.py)：通过 adapter + `project_3d_to_image` 渲染，与 B 比对
- [temp/render_v21_all_cams.py](../temp/render_v21_all_cams.py)：4 相机批量验证（diff = 0）

---

## 13. 文件分布速查

| 类别 | 路径 | 文件数 |
|---|---|---|
| Core   | [src/core/](../src/core/) | types / config / session / pipeline / constants / paths |
| I/O    | [src/io/](../src/io/) | adapters / calibration / frame_loader / label_io / sensor_profile |
| Models | [src/models/](../src/models/) | detector_2d / depth_estimator / segmentor / model_manager |
| Fusion | [src/fusion/](../src/fusion/) | geometry / lidar_fitting / radar_projection / image_to_3d / lshape_fit / sam2_frustum / box_from_2d_v3 / depth_anything_metric / bbox_geometric_fit |
| Agent  | [src/agent/](../src/agent/) | rule_engine / llm_agent / vision_agent / tool_executor / decision_merger / auto_label_v2 |
| Export | [src/export/](../src/export/) | writer + formats/{kradar,kitti}_writer |
| UI     | [src/ui/](../src/ui/) | main_window / toolbar / status_bar / stage_bar / frame_navigator / pages/ / panels/ / widgets/ / dialogs/ |
| Eval   | [src/eval/](../src/eval/) | metrics |

总计约 70+ Python 文件。

---

## 14. 端到端标注方法与全链路（文字版）

下面用一段连贯的文字描述"用户从打开数据集到导出 K-Radar 标签"全过程中，数据如何在各模块间流动、每一步做了什么、为什么这么做。

### 14.1 启动与数据集打开

用户运行 [run.py](../run.py)，进入 `MainWindow`。在 `Toolbar` 选择"打开数据集"，弹出对话框，指定 K-Radar 根目录与 profile [profiles/kradar.yaml](../profiles/kradar.yaml)。`SensorProfile` 解析出 4 个相机、2 个 LiDAR、1 个 4D 雷达的路径模板与立体裁剪策略。`DatasetBrowser` 页扫描根目录，列出所有 `seq_*` 序列；用户选中某个序列后切到 `SceneFrameBrowser`，按时间轴或缩略图选定具体帧（如 `seq_1 / 00033_00001`）。这一步只产生"序列 + 帧号"二元组，真正的数据加载推迟到下一步。

### 14.2 帧数据加载（adapter 层）

主标注页 `MultiViewAnnotation` 接到选帧事件，调用 [src/io/adapters/kradar_adapter.py](../src/io/adapters/kradar_adapter.py) 的 `load_frame`：
1. 读取 `info_label_v2_1/000XXX.txt`，解析 `* idx(...)= cam_front=NNN, os2-64=MMM, ...` 头，确定每个传感器对应的具体帧号；
2. 加载 4 张 2560×720 立体彩图、`os2-64` 原始 LiDAR `.pcd`、4D 雷达 `.npy` tensor；
3. 加载 per-seq YAML 标定 [resources/calib_seq_v2/seq_NN/cam_X.yml](../resources/calib_seq_v2/)，组合出每个相机的 `K, dist, T_lidar→cam`；
4. 应用 [profiles/kradar_calib_overrides.json](../profiles/kradar_calib_overrides.json) 里的 `delta_xyz / delta_rpy` 微调；
5. 调用 `_undistort_camera_images`：严格复刻 K-Radar 官方 `getOptimalNewCameraMatrix → 把 K 覆盖成 ncm → initUndistortRectifyMap(ncm, dist, None, ncm) → remap → 取左半 1280×720`。结果写回 `fd.images[cam]`，对应 intrinsics 替换为 ncm 且 distortion = 0；
6. 解析 label 行 `*, R, idx, class, x, y, z, yaw, hl, hw, hh` 生成 `Label3D` 列表（K-Radar 的 `hl/hw/hh` 是半边长，转换为 l/w/h = 2×）。

最终返回一个 `FrameData`，所有后续模块都只依赖这个不可变对象。

### 14.3 多视图渲染（人工浏览阶段）

`MultiViewAnnotation` 把 `FrameData` 分发给 4 个 `CameraImageView`、1 个 `PointCloudView`、1 个 `RadarPanel`：
- 相机视图先 `set_image(fd.images[cam])`（adapter 已裁过，UI 不再二次裁剪），再用 `fd.calibration.project_3d_to_image(pts, cam)` 把 LiDAR 点投到像素并用 `draw_lidar_overlay` 染色；GT 框（青色虚线）通过同一个 projector 从 8 个角点画线连出。由于 distortion = 0，投影走纯线性 K@p/z，与 K-Radar 官方 `T_ldr2pix = T_cam2pix @ T_ldr2cam_4` 数学等价。
- `PointCloudView`（pyvistaqt）渲染 LiDAR 全量点云、所有 3D 框、雷达 BEV 热图叠加；右键被拦截后合成左键 orbit。
- `RadarPanel` 在 BEV 上画 4D 雷达功率热力图，便于人工判断小目标位置。

此时若用户只是来"看 GT"，全流程已经结束——这是验证标定正确性的快速回路。

### 14.4 一键自动标注（核心路径）

用户按 `Space` 或点 Toolbar 的"AutoLabel"。`MainWindow` 起一个 asyncio 任务，调用 `AutoPipeline.run(frame, progress_cb)`，进度通过 `StageBar` 实时回显：

**Stage 1 detect**：对所有有内参的相机并行跑 [models/detector_2d.py](../src/models/detector_2d.py)（YOLOv8x.pt 或 Grounding DINO）。每个相机产出 `Detection2D(bbox, class, score)` 列表。stereo_crop 此处不再二次裁，因为 adapter 已经裁过 left 半。

**Stage 2 project**：对每个 2D 框，[fusion/depth_anything_metric.py](../src/fusion/depth_anything_metric.py) 在框内估计 depth；[fusion/image_to_3d.py](../src/fusion/image_to_3d.py) 用 depth + K 反投到相机系，再用 `T_cam→lidar = T_lidar→cam⁻¹` 转回 LiDAR 系，得到一个粗糙的 3D 中心 + 类别先验尺寸。

**Stage 3 lidar_fit**：[fusion/lidar_fitting.py](../src/fusion/lidar_fitting.py) 在该 3D 中心周围（与 2D 框对应的视锥）切出 LiDAR 点，DBSCAN 聚类取最大簇；[fusion/lshape_fit.py](../src/fusion/lshape_fit.py) 在 BEV 平面用 L-shape 拟合朝向 yaw 与 (l, w)；高度 h 由点云 z 范围给出，z 中心由地面 + h/2 修正。当 `fit_quality=full` 时，[fusion/sam2_frustum.py](../src/fusion/sam2_frustum.py) 先用 SAM2 mask 把视锥点过滤为前景，显著提升点稀疏目标的拟合质量。

**Stage 4 radar_map**：[fusion/radar_projection.py](../src/fusion/radar_projection.py) 把 4D 雷达 tensor 索引到框对应的 (range, az, el) 单元，统计累积功率与 doppler 一致性，作为后续 agent 的"是否真目标"附加证据。

**Stage 5 agent**：把 stage 1–4 的所有候选打包，扔给 [agent/](../src/agent/) 三路并行：`RuleEngine` 做硬性物理规则筛选（点数<3 → delete、尺寸偏离类别 σ、地面穿透、BEV IoU>0.7 强 NMS）；`LLMAgent`（Claude Sonnet 4）通过 `tool_executor` 调用 `get_box_info / refit_box_to_lidar / merge_boxes / adjust_box / final_decision` 等工具，最多 20 轮多轮推理；`VisionAgent`（Qwen2.5-VL-72B，本地 vLLM 优先）把 3D 框投影回图像后让 VLM 验证类别与对齐。`DecisionMerger` 把三路意见合成 `FinalDecision(confidence, source, reason)`：≥0.85 自动应用，0.5–0.85 进 `AgentPanel` 等人工，<0.5 仅 info。每帧自动改动数量上限 10。

如果用户偏好更轻量的"无 LLM"流程，可改走 [agent/auto_label_v2.py](../src/agent/auto_label_v2.py)：所有相机的 detector → SAM2 mask → frustum + DBSCAN → fit_box_with_sam2，最后多相机候选用 `_nms_3d_bev` 合并，按 `score × log(box_density)` 排序，Top-K 直接追加为新框。

### 14.5 人工审查与编辑

`AgentPanel` 列出每个候选的 `(class, confidence, source, reason)`，用户对中置信度项点 Accept/Reject。已应用的框自动出现在所有视图：
- 在相机视图直接拖拽 8 个角点手柄微调 2D 投影；
- 在 `AnnotationTable` / `BoxEditor` 直接编辑 `x, y, z, yaw, l, w, h` 数值；
- 在 `PointCloudView` 用 W/E/R 模式做 3D 平移/旋转/缩放。

每次编辑都进 `SessionState` 的 undo 栈（深度 50），并由 [src/core/session.py](../src/core/session.py) 60s 自动写入 [Auto-labeling/sessions/<hash>.json](../sessions/)。如果发现是标定本身不准（一组帧整体偏一致方向），切到 `CalibrationTunePanel` 实时调外参 delta，确认后 commit 到 `kradar_calib_overrides.json`，所有后续帧立即生效。

### 14.6 切帧、统计、导出

用 `FrameNavigator` 的 ←/→ 或 A/D 翻帧时，`MultiViewAnnotation` 重新调 `load_frame`（adapter 内部会缓存重计算的 undistort map），上一帧的 `SessionState` 已自动落盘。`Completion` 页持续统计"已审帧 / 总帧"。

满意后用 Toolbar 的"导出"，可选择三种 writer：
- [export/formats/kradar_writer.py](../src/export/formats/kradar_writer.py)：写回 K-Radar 原生格式，可直接覆盖 `info_label_v2_1`；
- [export/formats/kitti_writer.py](../src/export/formats/kitti_writer.py)：转 KITTI label 行，便于跨数据集训练；
- [export/writer.py](../src/export/writer.py)：完整 JSON（含 metadata、agent reason、calibration 快照），用于后期复盘。

### 14.7 关键路径速记

```
打开数据集
  → SensorProfile.load(profiles/kradar.yaml)
  → DatasetBrowser 选 seq → SceneFrameBrowser 选 frame
  → kradar_adapter.load_frame() : 图像 + LiDAR + radar + 标定 + GT
       └── _undistort_camera_images (ncm-overwrite 复刻)
  → FrameData
  → MultiViewAnnotation 渲染（投影走 K@p/z）
  ─ 用户按 Space ─
  → AutoPipeline.run(frame)
       ├── detect (YOLO/GroundingDINO, 全相机)
       ├── project (DepthAnything → 3D 中心)
       ├── lidar_fit (frustum + DBSCAN + L-shape, 可选 SAM2)
       ├── radar_map (4D radar 功率核对)
       └── agent (RuleEngine ‖ LLM ‖ Vision → DecisionMerger)
  → SessionState (boxes + decisions)
  → 人工 Accept / Reject / 拖拽编辑 (undo 栈 50)
  → 自动保存到 sessions/<hash>.json
  → Toolbar 导出 → kradar_writer / kitti_writer / json
```

整条链路的不变量：所有"3D ↔ 2D"操作都经过同一个 `CalibrationBundle.project_3d_to_image`，所有"标签 / LiDAR 帧"始终保持 K-Radar OS2-64 raw，不做任何 shift；所有相机视图的底图始终是 adapter 内 ncm-overwrite undistort 后的 LEFT 半。这三条保证了 UI 显示、auto-label pipeline、最终导出的 K-Radar 标签三者数学一致。
