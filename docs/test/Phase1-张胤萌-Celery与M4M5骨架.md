# Phase1 · 张胤萌：Celery 框架 + M4/M5 骨架使用说明

> **适用对象**：本人复盘、杨子杰 / 赵善奇 拉取后本地复现  
> **交付对应**：API 契约 v1.0 + Redis/Celery 异步框架 + `/models` `/train` `/infer` `/eval` 路由骨架  
> **配套契约**：[`docs/api/RESTful-API-契约-v1.0.md`](../api/RESTful-API-契约-v1.0.md)  
> **最后更新**：2026-07-14（含 Docker Desktop 实战踩坑）

---

## 1. 本阶段做了什么（交付清单）

| 交付物 | 路径 / 说明 | 状态 |
|--------|-------------|------|
| API 契约文档 | `docs/api/RESTful-API-契约-v1.0.md` | ✅ |
| Celery 异步框架 | `backend/app/tasks/` | ✅ |
| M4 模型 / 训练 / 推理 API | `backend/app/api/v1/models.py` 等 | ✅ |
| M5 评测 API | `backend/app/api/v1/eval.py` | ✅ |
| Compose 扩展 | `docker-compose.yml` 增加 `api` + `celery-worker` | ✅ |
| 本地 Docker 联调跑通 | postgres / redis / minio / api / celery-worker | ✅ |

**Phase1 Worker 不跑真实 GPU / ONNX**：只做 `queued → running → completed`，并写入模拟 progress / metrics。真正推理与 mAP 计算放在第三阶段。

### 1.1 新增 / 重点代码一览

| 路径 | 说明 |
|------|------|
| `backend/app/tasks/celery_app.py` | Celery 实例，Broker = `REDIS_URL` |
| `backend/app/tasks/train_tasks.py` | `tasks.train.run` |
| `backend/app/tasks/infer_tasks.py` | `tasks.infer.run` |
| `backend/app/tasks/eval_tasks.py` | `tasks.eval.run` |
| `backend/app/api/v1/models.py` | 模型注册 / 列表 / 版本 / 基线 |
| `backend/app/api/v1/train.py` | 训练任务 + Phase1 `enqueue` |
| `backend/app/api/v1/infer.py` | 推理 / 结果 / 可视化占位 |
| `backend/app/api/v1/eval.py` | 评测全套路由 |
| `backend/app/services/normal_model_service.py` | M4 Service |
| `backend/app/services/normal_eval_service.py` | M5 Service |
| `docker-compose.yml` | 基础设施 + API + Worker |

Celery 任务名（与契约一致）：

- `tasks.train.run`
- `tasks.infer.run`
- `tasks.eval.run`

### 1.2 和杨同学工作的关系

| 角色 | 提供内容 |
|------|----------|
| 杨子杰 | 鉴权、数据上传、16 表 DDL/ORM、postgres/redis/minio 配方 |
| 张胤萌 | 契约、Celery、M4/M5 路由、compose 中的 api/worker |

杨同学把**数据底座**建好；本阶段在同一套 `backend/app` 与 Docker 配方上，接上**异步任务管道**和**评测相关 API 骨架**。

---

## 2. Docker 是什么、本地在干什么

| 概念 | 通俗理解 | 本项目例子 |
|------|----------|------------|
| 镜像 Image | 安装包 | `postgres:16`、`model_group-main-api` |
| 容器 Container | 用安装包开出来的进程环境 | `pg-local`、`api-local` |
| Compose | 一键起多套服务的剧本 | 根目录 `docker-compose.yml` |

**本机默认会启动的 5 个容器：**

| 容器名 | 服务 | 本机端口 | 用途 |
|--------|------|----------|------|
| `pg-local` | postgres | 5432 | 业务数据库 |
| `redis-local` | redis | 6379 | JWT 黑名单 + Celery 队列 |
| `minio-local` | minio | 9000 / 9001 | 模型与图片文件；控制台 9001 |
| `api-local` | api | 8000 | FastAPI（含鉴权、数据、M4/M5） |
| `celery-worker-local` | celery-worker | （内部） | 消费 train/infer/eval 任务 |

浏览器访问的是映射到本机的端口，例如：http://127.0.0.1:8000/docs

**和 conda 的关系：**

- **全程 `docker compose up`**：日常联调**不必** `conda activate`
- **只 Docker 起中间件、本机跑 uvicorn/celery**：需要 `conda activate model-group`

---

## 3. 环境准备（第一次必看）

### 3.1 安装 Docker Desktop（Windows）

1. 下载：https://www.docker.com/products/docker-desktop/  
2. 安装（程序多在 C 盘；可之后把 WSL 数据盘迁到其它盘，见 Docker 文档）  
3. 勾选使用 **WSL 2**（推荐）  
4. 安装后**重启电脑**，打开 Docker Desktop，等到引擎就绪（可为 Resource Saver，不必慌）  
5. **完全退出并重启 VS Code / Cursor**（装完 Docker 后旧终端 PATH 可能还没有 `docker`）

验证（在**新开的**终端里）：

```powershell
docker -v
docker compose version
```

若提示 `'docker' 不是内部或外部命令`：

- 先确认 Docker Desktop 已打开  
- **关掉 VS Code 再重新打开**（最常见原因）  
- 仍不行：检查 PATH 是否包含  
  `C:\Program Files\Docker\Docker\resources\bin`  
- 临时可用全路径验证：  
  `& "C:\Program Files\Docker\Docker\resources\bin\docker.exe" -v`

> **注意：** 项目在 E 盘、Docker 装在 C 盘**完全正常**，互不影响。`docker` 能否找到只取决于 PATH，与当前工作目录无关。

### 3.2 国内网络：拉镜像失败时

若出现 `registry-1.docker.io` / `auth.docker.io` 连接超时：

1. Docker Desktop → **Settings → Docker Engine**  
2. 配置可用的 `registry-mirrors`（镜像源会变，需用当时可用的源）  
3. **Apply & Restart** 后再执行 `docker compose up -d --build`

postgres / redis / minio 拉成功、但构建 `api` 时卡在 `FROM python:3.11-slim`，也是同一类网络问题，可重试 `docker compose build` 或暂用下文「混合模式」。

### 3.3 克隆 / 拉取代码

```powershell
git clone https://github.com/jieyingfeixue/Model_Group.git
cd Model_Group
# 或已有仓库：
git pull
```

---

## 4. 推荐启动方式（全 Docker）

终端建议使用 **PowerShell**（不要用 CMD 跑 `Get-Content`）。

```powershell
cd "E:\学校有关\暑期岗位实习\Model_Group-main"   # 按你的实际路径修改

# 构建并后台启动全部 5 个服务（首次较慢）
docker compose up -d --build

# 查看是否都为 Up
docker compose ps
```

期望看到：`api-local`、`celery-worker-local`、`minio-local`、`pg-local`、`redis-local` 均为 **Up**。

关于提示 `version` is obsolete：可忽略，不影响运行。

### 4.1 首次初始化数据库（只做一次）

**PowerShell：**

```powershell
Get-Content backend\scripts\init_db.sql -Raw | docker exec -i pg-local psql -U postgres -d detection_platform
```

**CMD（若坚持用命令提示符）：**

```cmd
type backend\scripts\init_db.sql | docker exec -i pg-local psql -U postgres -d detection_platform
```

- Postgres 密码（compose 内）：`123456`  
- 数据库名：`detection_platform`  
- 若表已存在可能报错，属重复执行；日常**不要**用 `docker compose down -v`（会清空数据卷）

### 4.2 打开接口文档

浏览器访问：**http://127.0.0.1:8000/docs**

MinIO 控制台（可选）：http://127.0.0.1:9001  
默认账号密码：`minioadmin` / `minioadmin`

### 4.3 查看日志（排错）

```powershell
docker compose logs api --tail 80
docker compose logs celery-worker --tail 80
docker compose logs postgres --tail 40
```

---

## 5. 混合模式（Docker 只起中间件）

当 `api`/`celery-worker` 镜像构建因网络失败时，可先：

```powershell
docker compose up -d postgres redis minio

conda activate model-group
cd backend
pip install -r requirements.txt
copy .env.example .env
```

编辑 `backend/.env`，至少保证（本机连容器要用 `localhost`）：

```env
DATABASE_URL=postgresql://postgres:123456@localhost:5432/detection_platform
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=detection-platform
```

两个终端：

```powershell
# 终端 A — API
cd backend
uvicorn app.main:app --reload --port 8000

# 终端 B — Celery
cd backend
celery -A app.tasks.celery_app.celery_app worker --loglevel=info
```

数据库初始化仍可用上一节的 `docker exec ... psql` 命令。

---

## 6. 联调冒烟流程（Swagger）

1. 打开 http://127.0.0.1:8000/docs  
2. `POST /api/auth/register` 注册用户  
3. `POST /api/auth/login`，复制返回的 `access_token`  
4. 点击右上角 **Authorize**，输入：`Bearer <access_token>`（`Bearer` 后有空格）  
5. `GET /api/health` 应返回 ok  
6. `POST /api/models`（multipart：上传任意小文件 + name + framework）  
7. `GET /api/models` 应能看到刚注册的模型  

训练 / 评测额外要求：

- 数据集 `status` 必须为 **`frozen`**  
- 若暂时没有冻结接口，可手动：

```powershell
docker exec -i pg-local psql -U postgres -d detection_platform -c "UPDATE datasets SET status='frozen' WHERE dataset_id=1;"
```

（需先有对应 `dataset_id` 记录，否则请先插入或改用已有 id。）

训练 Phase1 联调：

1. `POST /api/train/tasks` → 得到 `pending_approval`  
2. `POST /api/train/tasks/{id}/enqueue` → 入队 Celery  
3. 轮询 `GET /api/train/tasks/{id}` → `running` → `completed`  
4. `GET /api/train/tasks/{id}/logs` → 可见 Redis 中的日志行  

推理：

1. `POST /api/infer/tasks`（提供 `image_id` 或 `dataset_id`）  
2. `GET /api/infer/tasks/{id}/results`  

评测：

1. `POST /api/eval/tasks`（需 frozen 数据集）  
2. `GET /api/eval/tasks/{id}/metrics`  

---

## 7. Phase1 额外端点

| 端点 | 作用 |
|------|------|
| `POST /api/train/tasks/{id}/enqueue` | 绕过管理员审批，直接 `queued` + Celery（仅开发联调） |

第二阶段应改为：管理员审批 → 自动入队；届时可限制 `enqueue` 仅 `admin` 或废弃。

---

## 8. 日常开关机（关机前必看）

### 8.1 下班 / 关机前

```powershell
cd "E:\学校有关\暑期岗位实习\Model_Group-main"
docker compose down
```

- 停止并移除容器  
- **数据仍保留**在 Docker volume 中  
- **不要**加 `-v`（会删除 postgres/minio 数据）  

然后可退出 Docker Desktop，再关电脑。

### 8.2 下次开机

1. 打开 Docker Desktop，等到引擎就绪  
2. 执行（一般**无需**再 `--build`，也**无需**再跑 `init_db.sql`）：

```powershell
cd "E:\学校有关\暑期岗位实习\Model_Group-main"
docker compose up -d
docker compose ps
```

3. 打开 http://127.0.0.1:8000/docs  

### 8.3 常用命令速查

| 命令 | 作用 |
|------|------|
| `docker compose up -d --build` | 构建并后台启动 |
| `docker compose up -d` | 启动已有镜像 |
| `docker compose ps` | 查看运行状态 |
| `docker compose down` | 停止并删除容器（保留卷） |
| `docker compose down -v` | 停止并**清空数据卷**（慎用） |
| `docker compose logs -f api` | 跟踪 API 日志 |

---

## 9. 队友拉取后如何复现（杨 / 赵）

前提：本仓库含更新后的 `docker-compose.yml` 与 `backend/app` **已 push 到 GitHub**。

1. 安装 Docker Desktop，新开终端确认 `docker -v`  
2. `git pull`  
3. （如需要）配置镜像加速  
4. 项目根目录：`docker compose up -d --build`  
5. `docker compose ps` 确认 5 个 Up  
6. **首次**执行 `init_db.sql`（见 §4.1）  
7. 打开 http://127.0.0.1:8000/docs  

默认连接约定（与当前 compose 一致）：

| 项 | 值 |
|----|-----|
| Postgres | `localhost:5432` / 用户 `postgres` / 密码 `123456` / 库 `detection_platform` |
| Redis | `localhost:6379` |
| MinIO | API `9000`，控制台 `9001`，`minioadmin`/`minioadmin` |
| API 文档 | `http://127.0.0.1:8000/docs` |

前端同学还可继续用 Vite `npm run dev`（端口 3000），`/api` 代理到 8000。

---

## 10. 常见问题

### `'docker' 不是内部或外部命令`

装完 Docker 后未重启 IDE；完全退出 VS Code/Cursor 再开。见 §3.1。

### `'Get-Content' 不是内部或外部命令`

当前是 **CMD** 不是 PowerShell。换 PowerShell，或用 §4.1 的 `type ... | docker exec`。

### 拉镜像 / build 超时

国内访问 Docker Hub 不稳定。配 registry-mirrors 或开代理，见 §3.2。

### `version` is obsolete

警告，可忽略；不影响容器运行。

### 训练 / 评测报「仅冻结数据集可用」

把对应数据集 `status` 设为 `frozen`，见 §6。

### 端口被占用（8000 / 5432 等）

```powershell
netstat -ano | findstr :8000
```

结束占用进程，或改 compose 端口映射。

### Resource Saver mode

Docker Desktop 闲置省电模式，属正常。有容器在跑或执行 compose 时会唤醒引擎。

---

## 11. 下一阶段不要在 Phase1 做

- ONNX Runtime 真实推理  
- pycocotools / torchmetrics 真实 mAP  
- Docker GPU 训练容器与调度  
- 管理员审批队列正式接口（替代临时 `enqueue`）  

---

## 12. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-07-14 | 初版：Celery + M4/M5 骨架与简要启动说明 |
| 2026-07-14 | 详化：Docker Desktop / PATH / 镜像加速 / PowerShell 与 CMD / 开关机 / 队友复现 / 冒烟与 FAQ |
