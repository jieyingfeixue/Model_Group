# Model_Group

目标检测数据与算法评测平台 —— **模型组图片访问兼容层 Demo**

本项目是暑期实习「模型组」的第一阶段交付：实现一个可运行的图片兼容层，为后续云服务器部署、多模态推理与评测引擎打基础。业务代码通过统一 API 访问图片，不直接依赖本地路径或云 URL。

完整平台概要设计见仓库内文档：`模型组-概要设计报告v4.0.docx`。

---

## 当前进度

| 阶段 | 状态 | 说明 |
|------|------|------|
| 图片兼容层 Demo | ✅ 已完成 | FastAPI + 本地图片自动扫描 + 预览页 |
| 用户鉴权 / JWT | ⏳ 待开发 | 第一阶段（Day1–4） |
| MySQL 数据底座 | ⏳ 待开发 | 替换当前文件夹扫描 |
| Canvas 在线标注 | ⏳ 待开发 | 第二阶段（Day5–9） |
| ONNX 推理 / 评测引擎 | ⏳ 待开发 | 第三阶段（Day10–15） |

---

## 技术栈

- **后端**：Python 3.11、FastAPI、Uvicorn、Pillow
- **前端（Demo）**：原生 HTML + JavaScript
- **环境管理**：Anaconda（推荐）或 venv
- **后续规划**：Vue3、MySQL、Redis、Celery、Docker、MinIO

---

## 项目结构

```
Model_Group-main/
├── backend/
│   ├── main.py                      # FastAPI 入口
│   ├── config.py                    # 环境配置
│   ├── routers/
│   │   ├── images.py                # 图片访问 API
│   │   └── resources.py             # 资源列表 API
│   └── services/
│       ├── resource_service.py      # 自动扫描 demo_assets
│       └── image/
│           ├── provider.py          # ImageProvider 抽象接口
│           ├── local_provider.py    # 本地文件实现（当前使用）
│           ├── factory.py           # 按配置切换 Provider
│           └── decoder.py           # 图片格式解码器
├── demo_assets/images/              # 本地图片目录（按模态分子文件夹）
│   ├── visible/
│   ├── infrared/
│   ├── mmwave/
│   └── lidar/
├── demo_data/                       # 说明文件
├── frontend/index.html              # Demo 预览页面
├── scripts/seed_demo_assets.py      # 生成占位样例图（可选）
├── requirements.txt
├── .env.example
└── 模型组-概要设计报告v4.0.docx
```

---

## 开发环境搭建

### 1. 克隆仓库

```powershell
git clone https://github.com/jieyingfeixue/Model_Group.git
cd Model_Group
```

### 2. 创建 Conda 虚拟环境（推荐）

```powershell
conda create -n model-group python=3.11 -y
conda activate model-group
pip install -r requirements.txt
```

### 3. 配置环境变量

```powershell
copy .env.example .env
```

默认配置即可本地运行：

```env
IMAGE_STORAGE_MODE=local
IMAGE_LOCAL_ROOT=./demo_assets/images
```

### 4. 生成样例图（可选）

如果 `demo_assets/images/` 下还没有图片，可运行：

```powershell
python scripts/seed_demo_assets.py
```

---

## 本地运行

### 启动服务

```powershell
conda activate model-group
cd Model_Group
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 访问地址

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:8000/ | Demo 预览页（列表 + 图片展示） |
| http://127.0.0.1:8000/docs | Swagger API 文档 |
| http://127.0.0.1:8000/health | 健康检查 |

### 停止服务

在运行 uvicorn 的终端按 `Ctrl + C`。

---

## 日常开发流程

### 添加 / 删除图片

1. 将图片放入 `demo_assets/images/` 对应模态子目录：

   ```
   demo_assets/images/
   ├── visible/      # 可见光
   ├── infrared/     # 红外
   ├── mmwave/       # 毫米波
   └── lidar/        # 激光雷达
   ```

2. 支持格式：`.jpg`、`.jpeg`、`.png`、`.webp`

3. 在网页点击 **刷新**，或重新请求 API —— **无需改代码、无需维护 JSON**

4. 空文件夹不会出现在列表中，目录里必须有图片文件

### 模态筛选

Demo 页顶部下拉框可按 `visible` / `infrared` / `mmwave` / `lidar` 筛选。模态由**文件夹名**自动识别；若图片直接放在 `images/` 根目录，则标记为 `unknown`。

### 修改兼容层代码

| 需求 | 修改文件 |
|------|----------|
| 切换存储后端（本地 → 云服务器 / MinIO） | `backend/services/image/factory.py`、新增 Provider |
| 支持新的图片格式（如 `.raw` 红外原图） | `backend/services/image/decoder.py` |
| 调整扫描 / 列表逻辑 | `backend/services/resource_service.py` |
| 新增 API 端点 | `backend/routers/` |
| 修改 Demo 页面 | `frontend/index.html` |

### 提交到 GitHub

```powershell
git add .
git commit -m "描述本次修改"
git push
```

仓库地址：https://github.com/jieyingfeixue/Model_Group

---

## API 说明

### 资源列表

```
GET /api/data/resources?modality=visible&page=1&page_size=50
```

返回自动扫描到的图片资源，`resource_id` 按文件路径排序生成。

### 获取图片（核心接口）

```
GET /api/images/{resource_id}
```

返回可直接在浏览器 / Canvas 中展示的图片。前端和后续推理模块**只应调用此接口**，不要直接访问 `file_path` 或云 URL。

### 缩略图

```
GET /api/images/{resource_id}/thumbnail?size=240
```

### 调试信息

```
GET /api/images/{resource_id}/meta
```

返回 `file_path`、文件是否存在、展示 URL 等。

---

## 兼容层设计

```
业务代码（前端 / 推理 / 评测）
        ↓  只调用 /api/images/{id}
   ImageProvider 兼容层
        ↓  按 IMAGE_STORAGE_MODE 切换
  LocalDemoProvider  |  HttpUrlProvider（预留）  |  MinIOProvider（预留）
        ↓
   ImageDecoder（格式解码，以后只改这里）
        ↓
  浏览器可展示的 JPEG  /  模型可用的图像数据
```

**设计原则：**

- 数据库（未来）只存逻辑路径 `file_path`，不存图片二进制
- 切换云服务器时只改 Provider 和 `.env`，业务 API 不变
- 图片格式确定后只在 `decoder.py` 注册解码器

---

## 常见问题

### 1. 启动报错 `[WinError 10013]`

端口被占用。先查占用进程：

```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

或换端口启动：

```powershell
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8001
```

### 2. 网页刷新后看不到新图片

通常是旧 uvicorn 进程还在运行。关掉旧进程后重新启动服务，浏览器 `Ctrl + F5` 强制刷新。

### 3. push 到 GitHub 失败

多为网络问题。可开代理后重试：

```powershell
git push -u origin main
```

---

## 后续开发路线

依据概要设计报告，三阶段规划如下：

1. **第一阶段（Day1–4）**：基础框架、API 契约、JWT 鉴权、MySQL 数据底座
2. **第二阶段（Day5–9）**：多模态时间戳对齐、Fabric.js 标注画布、审核流程
3. **第三阶段（Day10–15）**：数据集虚拟打包、ONNX 推理、PyCOCO 评测引擎、可视化看板

当前 Demo 对应第一阶段的**图片兼容层前置验证**，后续将 `LocalDemoProvider` 替换为云存储实现，并接入数据库 `data_resources` 表。

---

## 团队成员

| 成员 | 职责 |
|------|------|
| 赵善奇 | 前端架构、Canvas 标注、ECharts 可视化 |
| 杨子杰 | 数据底座、MySQL、标注与审核 API |
| 张胤萌 | MLOps、ONNX 推理、评测引擎、Celery 调度 |

---

## License

内部实习项目，暂不对外开源。
