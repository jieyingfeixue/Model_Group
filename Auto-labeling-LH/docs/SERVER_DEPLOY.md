# 服务器部署指南

## 架构

```
本地/远程电脑 (浏览器)                   服务器 (Linux)
────────────────────                    ─────────────
                                       ~/nas_write/            ← 程序目录
                                       │  ├── run.py           ← 桌面版入口
                                       │  ├── src/             ← 核心代码
                                       │  ├── web_server/      ← Web 服务 (新增)
                                       │  ├── config/
                                       │  ├── profiles/
                                       │  └── models/          ← 模型权重
                                       │
浏览器 ──── HTTP/WebSocket ──────────▶  FastAPI (端口 8080)
                                       │
                                       ▼ 直接文件系统读取
                                       ~/nas/LH_Dataset/
                                       ├── LH_data_all_sensor/
                                       ├── LH_data_all_sensor_annotations/
                                       ├── LH_data_all_sensor_annotations_autofill/
                                       └── LH_data_all_sensor_annotations_depth/
```

---

## 访问方式

### 方案 A：Web 浏览器（推荐）

```bash
cd ~/nas_write
pip install fastapi uvicorn aiofiles

# 启动 Web 服务
uvicorn web_server.app:app --host 0.0.0.0 --port 8080
```

然后从任意电脑浏览器访问：
- `http://<服务器IP>:8080/browser` — 图片浏览器 + 标注系统
- `http://<服务器IP>:8080/docs` — API 文档

### 方案 B：VNC（桌面版 GUI）

```bash
sudo apt install tigervnc-standalone-server
vncpasswd
vncserver :1 -geometry 1920x1080 -depth 24
# VNC Viewer 连接: <服务器IP>:5901
python run.py
```

### 方案 C：X11 Forwarding

```bash
ssh -X user@server
cd ~/nas_write && python run.py
```

---

## 部署步骤

### 1. 安装依赖

```bash
pip install fastapi uvicorn aiofiles numpy opencv-python-headless pyyaml scipy
```

### 2. 配置文件

编辑 `config/local.yaml`，确保路径正确：

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

### 3. 模型权重

确认 `models/` 目录包含：
- `yolov8x.pt` (137 MB) — 2D 检测
- `depth_anything_v2_vits.pth` (99 MB) — 深度估计
- `mobile_sam.pt` (41 MB) — SAM 分割

### 4. 启动

```bash
cd ~/nas_write
uvicorn web_server.app:app --host 0.0.0.0 --port 8080
```

后台运行：
```bash
nohup uvicorn web_server.app:app --host 0.0.0.0 --port 8080 > /tmp/web.log 2>&1 &
```

---

## Web 模块结构

```
web_server/
├── app.py                    # FastAPI 主程序
├── config.py                 # 服务配置
├── dependencies.py           # 共享依赖
├── websocket_manager.py      # WebSocket 管理
├── static/index.html         # 图片浏览器 + 标注前端
└── routes/
    ├── browse.py             # 文件浏览、图片服务、标注CRUD、建筑检测
    ├── datasets.py           # 数据集/序列/帧 API
    ├── frames.py             # 帧数据 API
    ├── sessions.py           # 会话 API
    ├── pipeline.py           # 流水线 + WebSocket
    ├── annotation.py         # 2D检测 + 2D→3D
    └── export.py             # 导出
```

---

## 改动汇总

| 文件 | 修改内容 |
|------|---------|
| `config/local.yaml` | 路径修正为 `/data1/LHO/nas/...` |
| `config/default.yaml` | 路径注释更新 |
| `src/io/adapters/lh_adapter.py` | rightcam(1) 搜索路径改为相对 dataset root |
| `src/models/depth_estimator.py` | 移除硬编码 Windows 路径 |
| `web_server/` | **新增** Web 服务模块 |
