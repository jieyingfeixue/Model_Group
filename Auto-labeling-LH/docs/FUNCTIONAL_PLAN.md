# 自动标注 — 功能规划与模块运行时分析

> 面向 LH（多模态数据库）数据集的多传感器半自动 3D 标注工具。
> 数据集：无人机挂载双海康相机 + 毫米波雷达 + GPS/IMU。
> 已有 K-Radar 支持（legacy），本分支聚焦 LH。

---

## 一、数据格式总览

### 1.1 LH 数据集目录结构

```
D:/Dataset/多模态数据库/
├── 4_29/  4_30/  5_9/  ...                    # 日期
│   └── with_cameras_capture_YYYYMMDD_HHMMSS/  # capture（一次飞行）
│       ├── *_mmwave_udp.bin                    # 原始毫米波 UDP 包
│       ├── {bin_stem}_radar/                   # bin 转换后的 mat 目录
│       │   └── mmwave_*_AntFrameNNN_FZxxxxx-yyyyy.mat
│       ├── match_mat_camera.csv                # W12 锚点: MAT 中间包真实相对时间
│       ├── target_depth_db.json                # 地图目标 GPS 位置 DB
│       ├── depth_labels/                       # 深度标注输出
│       │   ├── {mat_stem}.json                 # 按 MAT 的深度
│       │   └── {camera_stem}.json              # 按相机帧的 GPS 射线深度回退
│       └── {capture}_partNNN_YYYY-MM-DD-HH-MM-SS/   # part（一个 bin 可有多个）
│           └── segment_NNN_TTTTT.TTT_UUUUU.UUU/     # segment（时间切片）
│               ├── images/
│               │   ├── hikrobot_camera__DA8679037__image_raw/  # 主相机左目 (标注相机)
│               │   │   └── hikrobot_camera__DA8679037__image_raw_NNNNNN_tTTTTTT.TTT.jpg
│               │   └── hikrobot_camera__DA8679038__image_raw/  # 主相机右目 (CSV帧ID来源)
│               ├── pointclouds/at360__points/   # LiDAR（当前禁用）
│               ├── gps/nav100__fix/nav100__fix.csv
│               ├── heading/nav100__heading/nav100__heading.csv
│               ├── nav100_state/nav100__state/nav100__state.csv
│               └── radar_camera_match_ts.csv    # per-segment 相机↔MAT 匹配表
```

### 1.2 图像存储方式：NAS 上的逐帧 JPG

**服务器端没有视频文件**。原始可见光视频已在采集后预先抽帧，以连续 JPEG 序列存储在 NAS 上。
文件名内嵌 6 位帧号和相对时间戳：

```
hikrobot_camera__DA8679037__image_raw_000001_t000076.011.jpg
                                               ^^^^^   ^^^^^^^^^^^
                                               6位帧号  相对时间(秒)
```

- 帧率约 10–15 fps（对应约 70–100ms 间隔，**不需再按 1 秒抽帧**）
- 直接通过 SFTP 按需拉取单个 JPG 文件，无需 FFmpeg 解码大视频
- 帧与雷达 MAT 通过文件名时间戳做最近邻匹配

### 1.3 毫米波雷达 .mat 内部结构（1218style）

| 字段 | 含义 |
|------|------|
| `Data_Ori` | `(n_el_layers, 1)` object cell，每层是一个俯仰角波束 |
| `sub[0]` | `el_deg` — 俯仰角 (°) |
| `sub[1]` | `az_arr` — 方位角数组 `(n_az,)` |
| `sub[3]` | `sd_dB` — 频谱数据 `(n_range, n_az)` 单位 dB |
| `BeamPose` | `(n_el, 1)` → `(n_az, 7)` = `[az, el, lat, lon, alt, heading, ts]` |

**物理参数**：

| 参数 | 值 |
|------|-----|
| Range step | 6.0 m/bin |
| Max range | 4000 m |
| CA-CFAR 训练单元 | ±15（每侧） |
| CA-CFAR 保护单元 | ±2 |
| CFAR 虚警率 | 1×10⁻⁴ |
| 最低 dB 门限 | 20 dB |
| 单帧点数上限 | 20000 |

### 1.4 主相机标定

| 参数 | 值 |
|------|-----|
| 来源 | `D:/Dataset/多模态数据库/rightcam(1)` 实标文件 |
| fx / fy | 12503.99 / 12569.58 |
| cx / cy | 920.20 / 546.63 |
| distortion | `[-1.9036, 294.4366, -0.0773, -0.0291, 0.0]` |
| body→camera 偏移 | `[-0.201, -0.447, 1.023]` m（CATIA 数模量取） |

### 1.5 标注数据格式

- **LabelMe 2D 标注**：`LH_data_all_sensor_annotations/{date}/{capture}/{part}/{segment}/.../` 下 JSON 矩形框（`building`, `signal tower`）
- **深度标注**：`depth_labels/{mat_stem}.json`，字段: `depth_m`, `target_id`, `method`, `confidence`, `az_diff_deg`
- **地图目标 DB**：`target_depth_db.json`，记录近/中/远楼群 GPS 坐标

---

## 二、SSH 远程数据访问

### 2.1 已有实现

[src/io/remote_storage.py](../src/io/remote_storage.py) 已完整实现 SFTP 远程存储层：

```
RemoteDatasetStore(config)
  ├─ connect()             # paramiko SSHClient + open_sftp()
  ├─ test_connection()     # 列出远程根目录
  ├─ pull_file(rel)        # 按需下载 → 本地缓存 (size/mtime 校验, .download 临时文件)
  ├─ pull_tree(rel)        # 批量递归下载 + 可过滤
  ├─ push_file/push_tree   # 标注结果上传回服务器
  ├─ prepare_lh_index()    # 遍历远程 JSON 建本地轻量索引树
  ├─ prepare_lh_frame()    # 下载单帧图像 + GPS CSV + 匹配雷达 mat
  └─ prepare_lh_image()    # 仅下载缩略图所需的相机图像
```

### 2.2 配置

```yaml
# config/default.yaml
remote_storage:
  enabled: true
  host: "192.168.1.100"
  port: 22
  username: "labeler"
  password_env: "LH_REMOTE_PASSWORD"   # 密码从环境变量读取
  root: "/homes/LH_Dataset"
  cache_root: "./temp/remote_dataset_cache"
```

### 2.3 按需加载策略

由于服务器 NAS 上直接存储的是逐帧 JPG（而非大视频文件），远程加载策略很简单：

| 数据类型 | 单个文件大小 | 加载方式 |
|----------|-------------|----------|
| 相机 JPG | ~500 KB | 按需 SFTP `pull_file()` 单张拉取 |
| 雷达 .mat | ~30 MB | 打开帧时 `prepare_lh_frame()` 一次性下载 |
| GPS CSV | ~100 KB | 同上，批量小文件 |
| 标注 JSON | ~5 KB | `prepare_lh_index()` 建索引时批量拉取 |

无需视频 seek/分片读取，每个 JPG 独立传输，失败重试只影响单帧。

### 2.4 运行时行为

1. 启动时 `_check_remote_storage_async()` 后台测试 SFTP 连接
2. 用户点击"远程 NAS 数据集" → `prepare_lh_index()` 下载标注 JSON + 建目录索引树
3. 浏览缩略图时 `prepare_lh_image()` 按需下载单个 JPG
4. 打开帧时 `prepare_lh_frame()` 下载图像 + GPS CSV + 匹配 MAT
5. 所有文件缓存到本地，按 size/mtime 增量更新

---

## 三、启动流程

```
run.py → src/main.py:main()
  │
  ├─ _setup_file_logging()          # auto_labeling.log (5MB × 3 滚动)
  ├─ _install_global_excepthook()   # 全局异常捕获 + Qt 消息桥接
  ├─ QApplication(sys.argv)         # PyQt6 初始化
  ├─ load_config()                  # YAML 三层合并: default → local → 运行时覆盖
  └─ MainWindow(config)
       ├─ Session(config)           # 标注会话 (撤销栈 + SQLite)
       ├─ AutoPipeline(config)      # 自动标注管线 (懒加载)
       ├─ _build_ui()              # 4 页 QStackedWidget
       ├─ _check_remote_storage_async()  # 后台 SFTP 连接测试
       └─ showMaximized() → app.exec()
```

---

## 四、数据加载层 (`src/io/`) 运行时

### 4.1 FrameLoader — 适配器入口

[src/io/frame_loader.py](../src/io/frame_loader.py)

```
FrameLoader(profile, dataset_root)
  ├─ list_sequences()  → adapter.list_sequences()   # 扫描序列列表
  ├─ list_frames()     → adapter.list_frames()      # 扫描帧列表
  └─ load_frame()      → adapter.load_frame()       # 核心加载
```

根据 `profile.dataset` (`"lh"` / `"kradar"`) 静态路由到对应 adapter。
远程模式通过 `prepare_frame_callback` / `prepare_thumbnail_callback` 触发 SFTP 预下载。

### 4.2 LH Adapter — 单帧加载全链路

[src/io/adapters/lh_adapter.py](../src/io/adapters/lh_adapter.py) (~2555 行)

```
load_frame(root, profile, seq_id, frame_id) → FrameData
  │
  ├─ 1. 目录定位
  │    ├─ _segment_dir()   # seq_id → segment_NNN_... 目录
  │    └─ _capture_dir()   # seq_id → capture 目录 (含 bin + mmwave mat)
  │
  ├─ 2. 相机图像
  │    ├─ DA8679037 (主相机左目) → 精确匹配 frame_id.jpg
  │    ├─ 回退: _nearest_by_timestamp() 时间戳最近邻匹配
  │    └─ _imread_unicode()  # np.fromfile + cv2.imdecode (中文路径兼容)
  │
  ├─ 3. 毫米波雷达 (多策略 MAT 匹配)
  │    ├─ 策略1: _pick_segment_csv_mat()  # per-segment CSV 最近邻
  │    ├─ 策略2: _pick_mmwave_mat()       # W12 锚点/GPS 位置/线性插值回退
  │    ├─ _load_mmwave_layers()           # scipy.io.loadmat → Data_Ori + BeamPose
  │    ├─ _load_mmwave_pointcloud()       # CA-CFAR 检测 → ENU 转换 → body 点云
  │    │    ├─ _ca_cfar_1d()              # 向量化 CA-CFAR (15训练/2保护/Pfa=1e-4)
  │    │    └─ GPS 统一: 所有波束投影到参考束坐标系 [x_right,y_fwd,z_up,dB]
  │    └─ 航向修正: 雷达参考束航向 → 当前相机帧航向旋转
  │
  ├─ 4. GPS 导航
  │    ├─ _populate_gps_meta()    # nav100__fix.csv + heading + state 线性插值
  │    │    → fd.meta["gps_lat/lon/alt/hdg/heading_track"]
  │    └─ _rebuild_mmwave_body_from_point_gps()  # 逐点 GPS → 当前帧 body 坐标
  │
  ├─ 5. 标定
  │    ├─ _build_calibration_from_profile()   # YAML 静态内外参
  │    └─ _apply_rightcam_calibration()       # rightcam(1) 实标文件覆盖
  │
  ├─ 6. 深度标注
  │    ├─ _load_depth_labels_from_mat()       # depth_labels/{mat_stem}.json
  │    └─ _load_depth_labels_from_camera()    # GPS 射线深度回退
  │
  └─ 7. 叠加层
       ├─ _load_labelme_annotations()  # LabelMe 2D 矩形框 (最近邻时间匹配)
       └─ OSM 语义标注 (config 中 enabled: false)
```

**关键数据流**：`frame_id` 的文件名时间戳 `t_ref` 是全局锚点——图像按 `t_ref` 精确匹配，雷达按 `t_ref` 选最近 MAT，GPS 按 `t_ref` 线性插值。

### 4.3 序列枚举

`list_sequences()` 扫描逻辑：
- 遍历 `{root}/{date}/{capture}/{part}/segment_*/`（4 层）和 `{root}/{capture}/segment_*/`（2 层浅层）
- **过滤**：只列出同时有 capture BIN 和人工 LabelMe 标注的 segment
- 无 BIN 的 capture、无标注的 segment 不显示在场景浏览器中

`list_frames()` — 只返回人工标注关键帧（`labelme_root` 下的帧），不显示 autofill 帧。

---

## 五、自动标注管线 (`src/core/pipeline.py`) 运行时

`AutoPipeline.run(frame, progress)` — Space 键触发，后台线程执行。

### Stage 1: detect (2D 检测)

```
ModelManager.get_detector() → YOLOv8 (yolov8x.pt, conf=0.35, nms=0.45)
  每相机独立检测 (cam-front/left/rear/right 或 DA8679037)
  → state.detections_2d_per_cam[cam] = [Detection2D(bbox, class, score), ...]
```

- 支持多相机并行检测
- Grounding DINO 可选（`default_prompt: "car. truck. bus. pedestrian. cyclist"`）
- LH 数据集目前仅有单相机（DA8679037），实际只跑一个

### Stage 2: project (2D → 3D 投影)

```
对每个相机的每个 Detection2D:
  1. DepthEstimator 估计深度
     - LiDAR 投影优先 (sparse depth from pointcloud → dense via interpolation)
     - Depth Anything v2 回退 (torch_depth / onnx)
  2. ImageTo3DProjector.project(det, depth_map, calib, cam)
     → 2D bbox 射线投影 + 深度采样 → 初始 3D box (Label3D)
  3. 多相机 3D NMS (XY-plane AABB IoU > 0.4 去重)
```

- LH 数据集无 LiDAR（已禁用），走纯 Depth Anything 单目深度路径
- LiDAR 聚类回退（DBSCAN + RANSAC 去地面）仅在无任何相机检测时触发

### Stage 3: lidar_fit (LiDAR 点云拟合)

```
LiDARFitter.fit(box, pts)
  1. 框内点云提取 (expand=1.5)
  2. PCA 航向修正 (compute_pca_yaw)
  3. 尺寸拟合 (local min/max)
  4. 底面贴合地面 (estimate_ground_z_at)
```

- LH 数据上 skip（无 LiDAR 点云）

### Stage 4: radar_map (雷达 ROI)

```
RadarProjector.map_boxes(boxes, radar_tensor)
  → 3D box → 球坐标 → 雷达张量索引裁剪 → RadarROI.stats
```

- K-Radar 4D 张量格式适用；LH 的 radar_tensors 当前为空（雷达点云走 mmwave pointcloud 路径）

### Stage 5: agent (三路决策融合)

```
RuleEngine.check_all_boxes()    确定性规则 (每框 <1ms)
  ├─ LiDAR 点数 (0→delete, <3→warning)
  ├─ 尺寸先验 (类别均值 ± σ)
  ├─ BEV 重叠 (>0.5 IoU → delete_lower_score)
  ├─ 地面穿透 (>0.3m → adjust_center_z)
  └─ 航向一致性 (PCA yaw 偏差 >30° → adjust_yaw)

LLMAgent.review_frame()        Claude Sonnet 4 (Anthropic API)
  └─ ToolExecutor: get_box_info / adjust_box / delete_box / refit_box_to_lidar
     / merge_boxes / split_box / get_neighbours / query_class_prior
     / get_radar_signature / final_decision
  └─ 最多 20 轮 tool_use

VisionAgent.verify_boxes_on_image()   Qwen-VL-Max (DashScope API)
  └─ 3D 框投影到图像 → 渲染彩色线框 → VLM 验证对齐/类别/漏标

DecisionMerger.merge(rules, llm, vision)
  ├─ confidence ≥ 0.85 → auto     (自动应用)
  ├─ confidence ≥ 0.50 → ask_human
  └─ confidence < 0.50 → info_only
  └─ max_auto_adjustments_per_frame: 10  (防 LLM 失控)
```

---

## 六、GUI 交互层 (`src/ui/main_window.py`) 运行时

```
MainWindow (QMainWindow, QStackedWidget 4 页)
  │
  ├─ Page 0: DatasetBrowserPage          # 数据集选择
  │    └─ dataset_selected → _on_dataset_selected(root, profile)
  │         ├─ load_sensor_profile() → profiles/lh.yaml
  │         ├─ FrameLoader(profile, root)
  │         ├─ remote → prepare_lh_index() 建索引
  │         └─ → Page 1
  │
  ├─ Page 1: SceneFrameBrowserPage       # 场景树 + 帧缩略图网格
  │    ├─ 树形: date → capture → part → segment
  │    ├─ 远程/本地按需加载缩略图
  │    └─ frame_selected → _on_frame_selected(seq_id, frame_id)
  │         ├─ frame_loader.load_frame() → FrameData
  │         ├─ _prefetch_adjacent()  # 后台预加载下一帧
  │         └─ → Page 2
  │
  ├─ Page 2: MultiViewAnnotationPage     # 主标注页
  │    ├─ 快捷键: A/D 切帧, Space 自动标注, N 新建框, Tab 切换框
  │    ├─ 图像面板 + 点云面板 + 标注表格 + Agent 面板
  │    ├─ Space → _run_auto()
  │    │    └─ 后台线程: AutoPipeline.run() → signals.finished
  │    │         └─ _on_annotation_done(state) → 更新 UI + 刷新框
  │    ├─ LabelMe 2D 标注叠加 (building/signal tower 矩形框)
  │    └─ 深度叠加 (深度着色 + 置信度标记)
  │
  └─ Page 3: CompletionPage              # 完成汇总 + 导出
       └─ save + export (KITTI / K-Radar / LH 格式)
```

### 6.1 帧导航与会话

```
_navigate_frame(delta)  →  切到 prev/next 帧
  ├─ _load_and_show_frame(seq_id, frame_id)
  ├─ session.state.seq_id / frame_id 更新
  ├─ page_multiview.set_frame(frame_data, boxes)
  └─ _prefetch_adjacent()  # 后台预加载下一帧 (最多缓存3帧)
```

### 6.2 快捷键

| 快捷键 | 功能 |
|--------|------|
| `A` / `←` | 上一帧 |
| `D` / `→` | 下一帧 |
| `Space` | 一键自动标注（全管线） |
| `Ctrl+D` | 仅运行 2D 检测 |
| `R` | Agent 审查 |
| `Ctrl+S` | 保存 |
| `Ctrl+Z` | 撤销 |
| `Delete` | 删除选中框 |
| `N` | 新建手动框 |
| `Tab` | 选中下一框 |
| `F` | 聚焦选中框 |

---

## 七、Agent 系统 (`src/agent/`)

```
                    ┌──────────────┐
                    │  ToolExecutor │  ← FrameContext(seq, frame, boxes, lidar, radar, ground)
                    └──────┬───────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                  ▼
   ┌──────────┐   ┌────────────┐   ┌──────────────┐
   │RuleEngine│   │  LLMAgent  │   │ VisionAgent  │
   │ (<1ms/框)│   │(Anthropic/ │   │ (Qwen-VL-Max)│
   │ 纯numpy  │   │  OpenAI)   │   │              │
   │ 5项规则  │   │Tool Use×20 │   │ 图像审查     │
   └────┬─────┘   └─────┬──────┘   └──────┬───────┘
        │               │                 │
        ▼               ▼                 ▼
   ┌────────────────────────────────────────────┐
   │           DecisionMerger                    │
   │  auto(≥0.85) | ask_human(≥0.5) | info_only │
   └────────────────────────────────────────────┘
```

- **RuleEngine** ([rule_engine.py](../src/agent/rule_engine.py)): 纯 numpy 确定性规则，零网络延迟
- **LLMAgent** ([llm_agent.py](../src/agent/llm_agent.py)): Claude API + tool_use 多轮分析
- **VisionAgent** ([vision_agent.py](../src/agent/vision_agent.py)): 3D 框投影→VL 模型审查
- **DecisionMerger** ([decision_merger.py](../src/agent/decision_merger.py)): 三层结果加权合并

---

## 八、融合层 (`src/fusion/`)

| 模块 | 功能 | 输入 | 输出 |
|------|------|------|------|
| [geometry.py](../src/fusion/geometry.py) | 地面估计(RANSAC)、点云裁剪、BEV IoU、PCA 航向 | points (N×3/4), Label3D | plane, points_in_box, iou, yaw |
| [image_to_3d.py](../src/fusion/image_to_3d.py) | 2D bbox → 3D box 投影 | Detection2D, depth_map, calib | Label3D |
| [lidar_fitting.py](../src/fusion/lidar_fitting.py) | LiDAR 点云框拟合 | Label3D, points | refined Label3D |
| [radar_projection.py](../src/fusion/radar_projection.py) | 3D box → 雷达张量 ROI | Label3D, radar_tensor | RadarROI |

---

## 九、会话持久化 (`src/core/session.py`)

```
Session
  ├─ state: SessionState           # 当前帧的所有 boxes + stage + operations
  ├─ _undo_stack / _redo_stack     # 快照栈 (深度 50)
  ├─ operation history (deque)     # Phase 4: Operation 粒度撤销
  ├─ save()                        # JSON + SQLite (sessions.db)
  ├─ save_if_due()                 # 60s 定时自动保存
  └─ load(path)                    # 恢复会话
```

---

## 十、导出 (`src/export/`)

| 格式 | 模块 | 说明 |
|------|------|------|
| K-Radar | [formats/kradar_writer.py](../src/export/formats/kradar_writer.py) | `*,class,x,y,z,yaw,l/2,w/2,h/2` |
| KITTI | [formats/kitti_writer.py](../src/export/formats/kitti_writer.py) | `Type ... dims location rotation_y` |
| LH | (待实现) | `default_format: "lh"` |

---

## 十一、完整运行时数据流

```
                        NAS 服务器 (SFTP, 逐帧 JPG + .mat + CSV)
                                │
              ┌─────────────────┤ pull_file / prepare_lh_frame
              ▼                 ▼
        RemoteDatasetStore   本地缓存 (temp/remote_dataset_cache/)
              │                 (单帧 JPG ~500KB, 无视频文件)
              ▼
        FrameLoader.load_frame()
              │
  ┌───────────┼───────────┬──────────────┬──────────────┐
  ▼           ▼           ▼              ▼              ▼
JPG 帧     mmWave .mat  GPS CSV       标定 YAML      LabelMe JSON
(DA8679037) (Data_Ori + (nav100_fix    (rightcam(1)   (building框)
  ~500KB     BeamPose)   + heading     + profile)
              │           + state)
              ▼               │
        CA-CFAR 检测           │
        GPS → ENU → body       ▼
              │          gps_lat/lon/hdg
              ▼               │
        雷达点云 (N×4)        │
        [x,y,z,dB]            │
              │               │
              └───────┬───────┘
                      ▼
                  FrameData
                      │
              ┌───────┴───────┐
              ▼               ▼
        AutoPipeline    MultiViewAnnotationPage
        (Space键触发)    (手动标注 + 深度叠加)
              │
  ┌───────┬───┼───────┬───────┐
  ▼       ▼   ▼       ▼       ▼
detect  project lidar_fit radar  agent
(YOLO)  (2D→3D) (refine)  (ROI)  (rules+LLM+VL)
              │
              ▼
        SessionState.boxes → save / export
```

---

## 十二、SAM3 建筑物分割标注

> 详细使用指南见 [docs/SAM3_BUILDING_GUIDE.md](SAM3_BUILDING_GUIDE.md)

### 12.1 SAM2 vs SAM3

| 能力 | SAM2 (当前) | SAM3 (目标) |
|------|------------|------------|
| Box/Point prompt | ✅ | ✅ |
| Text prompt ("building") | ❌ | ✅ |
| 全景分割 + 类别标签 | ❌ 需 grid scan | ✅ 原生支持 |
| Temporal propagation | ❌ | ✅ 跨帧传播 mask |

### 12.2 端到端流程

```
用户按钮/快捷键 B
  │
  ▼
Segmentor.segment_with_text(image, text="building. structure. house")
  │
  ├─ SAM3 前向推理 (text encoder + image encoder + mask decoder)
  ├─ 输出: [{mask, bbox_xyxy, score, class_name}, ...]
  ├─ 后处理: 碎片过滤 + NMS + 形态学闭运算
  │
  ▼
每个 bbox → box_from_2d_v3.fit_box_with_sam2()
  ├─ 深度估计 (Depth Anything v2 / 雷达 GPS)
  ├─ → Label3D (class_name="building", depth_m=...)
  │
  ▼
UI 刷新 → 人工核验 → 保存/导出
```

### 12.3 集成方式

- `Segmentor` 新增 `segment_with_text()` 和 `propagate_to_next()` 方法
- `_try_load_sam3()` 后端加载 SAM3 模型
- 配置 `models.segmentor.name: "sam3"` 切换
- 回退链: SAM3 → SAM2 → MobileSAM → stub(bbox-only)

### 12.4 注意事项

- SAM3 截至 2026-07 尚未正式发布，API 基于 SAM2 架构预估
- GPU 显存需求 ~4-6 GB，大图需 resize 到 1024×1024
- 建筑深度仍以 GPS 目标匹配 (`target_depth_db.json`) 为最可靠来源，SAM3 只提供 2D mask

---

## 十三、雷达点云深度估计（已部分实现 + 规划增强）

### 13.1 当前状态

深度赋值已有两条路径：

1. **MAT 级深度** — `assign_depth_azimuth.py` 产出 `depth_labels/{mat_stem}.json`
2. **GPS 射线深度** — `assign_depth_gps.py` 产出 `depth_labels/{camera_stem}.json`

深度计算核心公式（[TEMPORAL_DEPTH_WORKFLOW.md](TEMPORAL_DEPTH_WORKFLOW.md)）：
```
depth_m = distance(drone_gps_at_frame, target_gps)
```

### 13.2 深度标注数据字段

```json
{
  "depth_m": 1234.5,
  "target_id": "manual_01234",
  "method": "gps_db_temporal",
  "confidence": 0.91,
  "az_diff_deg": 1.8,
  "camera_yaw_offset_deg": -3.5
}
```

### 13.3 规划增强

| 模块 | 说明 |
|------|------|
| **坐标系转换** | body(camera) ↔ radar 外参已配置 (rightcam(1) + profile YAML) |
| **深度提取** | 雷达 CA-CFAR 点云中，框对应 ROI 内最强回波点的 range |
| **置信度** | `confidence = f(max_power, num_points, az_spread)` |
| **多点云融合** | 一个 capture 内多 MAT 的深度取时序中值 |
| **回退** | 雷达回波为空时用 Depth Anything v2 单目估计填充 |
| **核验标记** | `confidence < 0.65` / `az_diff > 12°` / `target_id` 跳变 → GUI 高亮 |

---

## 十四、实施路线

| 阶段 | 内容 | 涉及模块 | 状态 |
|------|------|----------|------|
| **Phase 1** | SSH 远程连接 + 远程文件浏览 | `remote_storage.py` | ✅ 已实现 |
| **Phase 2** | LH 数据集 adapter + JPG 帧加载 | `lh_adapter.py` | ✅ 已实现 |
| **Phase 3** | MAT→点云 CA-CFAR + GPS 统一 | `lh_adapter.py:_load_mmwave_pointcloud` | ✅ 已实现 |
| **Phase 4** | 深度标注 (MAT级 + GPS 射线) | `depth_labels/` + `assign_depth_*.py` | ✅ 已实现 |
| **Phase 5** | 连续帧时序深度 (`target_depth_db.json`) | `TEMPORAL_DEPTH_WORKFLOW.md` 方案 | ✅ 已实现 |
| **Phase 6** | SAM3 模型集成 (segmentor 升级) | `segmentor.py`, `ModelManager` | 🔲 待 SAM3 发布 |
| **Phase 7** | 雷达深度提取增强 (框级 ROI) | `radar_projection.py` | 🔲 待增强 |
| **Phase 8** | 批量自动标注 + 时序传播 | `pipeline.py`, SAM3 propagation | 🔲 待实施 |
| **Phase 9** | LH 格式导出 writer | `export/formats/lh_writer.py` | 🔲 待实施 |

---

## 十五、关键依赖

```text
paramiko >= 3.0            # SSH/SFTP 远程连接
opencv-python >= 4.8       # 图像处理 + imdecode
numpy >= 1.24              # 数值计算
scipy >= 1.10              # .mat 加载 + 空间变换
torch >= 2.1               # SAM2 / Depth Anything 推理
PyQt6 >= 6.5               # GUI 框架
pyvista / pyvistaqt        # 3D 点云可视化
shapely                    # BEV IoU 计算
segment-anything-3         # SAM3 (待发布)
depth-anything-v2          # 单目深度估计
```
