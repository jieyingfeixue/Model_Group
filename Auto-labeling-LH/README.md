# LH 多传感器半自动 3D 标注工具（Web 版）

基于 LH 多模态数据集（可见光双目 + 红外 + 毫米波雷达 + GPS/IMU）的半自动标注系统。纯 Web 前端，浏览器访问即可使用。

## 目录结构

```
Auto-labeling-LH/
├── pyproject.toml               # 项目依赖与构建配置
│
├── src/                         # 核心代码
│   ├── core/                    # 核心框架（配置/管线/会话/类型）
│   ├── io/                      # 数据 I/O 层（帧加载/标定/传感器配置/适配器）
│   ├── models/                  # AI 模型封装（YOLOv8/Depth Anything V2/Mobile SAM/SAM3）
│   ├── fusion/                  # 多传感器融合（2D→3D/深度估计/雷达投影）
│   ├── agent/                   # AI 审查（LLM/VLM/规则引擎/决策融合）
│   ├── export/                  # 数据导出（KITTI/JSON）
│   └── eval/                    # 评估模块
│
├── web_server/                  # Web 服务（FastAPI + WebSocket）
│   ├── app.py                   # 应用入口
│   ├── config.py                # 服务端配置
│   ├── websocket_manager.py     # WebSocket 管理
│   ├── routes/                  # REST API 路由（数据集/帧/标注/管线/导出）
│   └── static/                  # 前端页面（浏览器/标注/首页）
│
├── sam3-main/sam3/              # SAM3 模型源码
├── config/                      # 配置文件（default.yaml / local.yaml）
├── profiles/                    # 传感器配置（lh.yaml + 标定/采集覆盖）
├── models/                      # 模型权重（YOLOv8x, Mobile SAM, Depth Anything V2）
├── tools/                       # 独立数据处理脚本（26 个）
├── tests/                       # 单元测试（20 个）
├── docs/                        # 项目文档（14 篇）
└── sessions/                    # 会话持久化（sessions.db）
```

## Web 服务

浏览器访问，无需安装客户端。

### 快速启动

```bash
cd /data1/LHO/nas_write/Auto-labeling-LH

# 方式 1：直接启动
python -m web_server.app

# 方式 2：uvicorn 启动
uvicorn web_server.app:app --host 0.0.0.0 --port 8080

# 方式 3：后台运行
nohup python -m web_server.app > /tmp/web.log 2>&1 &
```

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WEB_HOST` | 绑定地址 | `0.0.0.0` |
| `WEB_PORT` | 绑定端口 | `8080` |
| `LH_DATASET_ROOT` | 数据集根目录 | `/data1/LHO/nas/LH_Dataset/LH_data_all_sensor` |
| `SAM3_SOURCE_ROOT` | SAM3 源码路径 | `../sam3-main` |
| `SAM3_CHECKPOINT` | SAM3 权重文件 | `../sam3-main/sam3.pt` |
| `MODEL_DEVICE` | 推理设备 | `cuda` |
| `ANTHROPIC_API_KEY` | Claude API key（Agent 系统） | — |

### 页面访问

| 地址 | 功能 |
|------|------|
| `/` `/home` | 首页 |
| `/browser` | 图片浏览器（文件树 + 帧浏览） |
| `/annotate` | 标注页面（画框标注 + IR 匹配） |
| `/app` | React SPA（前端构建版） |
| `/docs` | Swagger API 文档 |
| `/api` | API 端点列表 |
| `/health` | 健康检查 |

### REST API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/datasets` | 列出数据集 |
| GET | `/api/sequences` | 列出序列 |
| GET | `/api/frames` | 查询帧列表 |
| GET | `/api/frames/metadata` | 帧元数据 |
| GET | `/api/frames/image` | 获取图像 |
| GET | `/api/frames/thumb` | 获取缩略图 |
| GET | `/api/frames/pointcloud` | 获取点云 |
| GET | `/api/frames/radar` | 获取雷达数据 |
| GET | `/api/frames/calibration` | 获取标定参数 |
| POST | `/api/detect` | 触发目标检测 |
| POST | `/api/box-from-2d` | 2D 框 → 3D 框 |
| POST | `/api/pipeline/run` | 运行自动标注管线 |
| POST | `/api/export` | 导出标注结果 |
| GET/POST | `/api/sessions/` | 会话管理 |
| GET | `/api/browse/lidar_bev_map` | 毫米波雷达检测 + 卫星地图叠加 |

### WebSocket

- 支持实时管线进度推送（`websocket_manager.py`）

### 标注功能

- **文件树浏览**：日期 → 捕获 → 部件 → 片段 → 相机（037/038/IR）
- **三栏 IR 匹配**：选中 IR 图片，自动匹配时间戳最近的 037/038 可见光
- **四宫格布局**：左上 037 可见光、右上 IR 红外、左下 038 可见光、右下雷达检测地图
- **标注模式**（`Ctrl+Enter`）：鼠标拖动画框，支持三路同步
- **CSV 记录**：三图时间戳存入 `sessions/triple_csvs/`
- **标注保存**：存入 `sessions/annotations/`

## 毫米波雷达检测地图

右下角面板将毫米波雷达 UDP 数据包（`.bin`）中的检测目标直接标注到高德卫星实拍地图上，无需预处理。

### 数据流

```
{date}/{capture}/{capture}_mmwave_udp.bin     ← 原始 UDP 数据包 (8624 字节/包)
    │
    ├─ 帧头 (256B) → GPS经纬度 + 航向角 + 天线方位/俯仰角 + 时间戳
    │
    ├─ 回波数据体 (5376B) → 和路 672 距离门 (float32) 信号强度
    │
    └─ 阈值检测 (>80 dB) → 信号峰值 → 距离 × 方位 → GPS坐标
            │
            └─ WGS84 → GCJ-02 → 高德瓦片坐标 → 卫星地图标注
```

### Bin 包格式（8624 字节/包）

| 偏移 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0 | 同步头 | uint32×2 | `0xABABABAB` |
| 12 | FZ 帧序号 | uint32 | 网络发送帧号 |
| 24 | 天线帧起始标志 | uint32 | `1` = AntFrame 第一包 |
| 32 | 距离量程 | float32 | 单位 km（默认 4.0） |
| 44 | 时间戳 | uint32 | 相对秒数编码 |
| 48 | 载机经度 | float32 | WGS-84, 正东 |
| 52 | 载机纬度 | float32 | WGS-84, 正北 |
| 56 | 载机真航向角 | float32 | 0=北, 顺时针 |
| 60 | GPS 高度 | float32 | 米 |
| 80 | 天线方位角 | float32 | 度 |
| 84 | 天线俯仰角 | float32 | 度 |
| 256 | 回波数据体 | float32×672 | 和路信号强度 (dB) |
| 5632 | 地形点数据 | float32×36 | 雷达硬件检测结果 |
| 5776 | 天线帧检测 | float32×712 | 目标检测结果 |

### 检测参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 信号阈值 | 80 dB | 低于此值的回波被过滤 |
| 采样包数 | 600 | 从 bin 文件中均匀采样 |
| 每包保留 | 前 3 强信号 | 避免杂波过多 |
| 地图范围 | 10 km | 约 5 km 半径 |
| 瓦片级别 | 自适应 (13-18) | 根据范围自动选择 |

### 目标 GPS 计算

```
bearing = heading + ant_azimuth
east  = range_m × sin(bearing)
north = range_m × cos(bearing)
lat = sensor_lat + north / 111320
lon = sensor_lon + east / (111320 × cos(lat))
```

### 适用数据

使用**不含 `_radar/` 目录**的原始 capture（bin 文件直接在 Web 服务中解析，无需 `batch_convert_bins.py` 预处理）。

```bash
# 查看哪些 capture 可直接使用
find /data1/LHO/nas/LH_Dataset/LH_data_all_sensor/ \
  -name '*_mmwave_udp.bin' -type f \
  ! -execdir test -d '{}.radar' \; -print
```

## 依赖

```bash
# 核心依赖
pip install -e .

# 含 ML 模型（torch, transformers, groundingdino, segment-anything-2）
pip install -e ".[ml]"

# 含开发工具（pytest, ruff）
pip install -e ".[dev]"
```

或手动安装：

```bash
pip install fastapi uvicorn numpy scipy opencv-python-headless PyYAML open3d \
            pillow matplotlib scikit-learn httpx paramiko pydantic anthropic openai \
            "torch>=2.0" torchvision transformers
```

## 数据集

```
/data1/LHO/nas/LH_Dataset/LH_data_all_sensor/
├── 4_27/  4_29/  4_30/  5_9/  5_19/  6_5/  6_8/    # 日期目录
├── 6-11导出-缺611night3/  6-11导出-缺611night3_new/  6-12_export/
└── extract_image*/   train_*/   数据-场景对应表.xlsx

# 每段图片目录结构：
segment_*/images/
├── hikrobot_camera__DA8679037__image_raw/    # 037 可见光左目
├── hikrobot_camera__DA8679038__image_raw/    # 038 可见光右目
└── usb_ir__image_raw/                        # IR 红外

# 标注数据（与主数据集分离）：
/data1/LHO/nas/LH_Dataset/
├── LH_data_all_sensor_annotations/           # 人工标注
├── LH_data_all_sensor_annotations_autofill/  # 自动标注
└── LH_data_all_sensor_annotations_depth/     # 深度标注
```

## 配置

`config/local.yaml`：

```yaml
dataset:
  root: "/data1/LHO/nas/LH_Dataset/LH_data_all_sensor"
annotations:
  labelme_root: "/data1/LHO/nas/LH_Dataset/LH_data_all_sensor_annotations"
  autofill_root: "/data1/LHO/nas/LH_Dataset/LH_data_all_sensor_annotations_autofill"
  depth_root: "/data1/LHO/nas/LH_Dataset/LH_data_all_sensor_annotations_depth"
remote_storage:
  enabled: false
```

