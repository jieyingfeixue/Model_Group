# Docker 使用指南

>只需跟着做就能在本机启动 PostgreSQL 数据库。

---

## 一、Docker 在我们项目里干什么？（最基础的解释）

### 一句话版本

**Docker 就是一个"即用即抛"的软件安装器。** 你不用在电脑上装 PostgreSQL、装 Redis、装 MinIO，Docker 帮你装好、跑起来，不用了就关掉，电脑干干净净。

### 打个比方

想象你要做一道菜，需要用到烤箱、蒸锅、搅拌机。

- **传统方式**：去商场一个一个买回来，装厨房里，占地方，搬家还得拆
- **Docker 方式**：有人给你一个"厨房集装箱"，里面烤箱、蒸锅、搅拌机都配好了，拉到后院插上电就能用，用完整个箱子拖走

我们这个项目里，Docker 就是那个"厨房集装箱"。

### 具体到本项目，Docker 管三样东西

| 服务 | 干什么的 | 不用 Docker 的话 |
|------|---------|-----------------|
| **PostgreSQL（数据库）** | 存储所有数据：用户信息、图片路径、标注结果…… | 得去官网下载安装包 → 配置环境变量 → 设置密码 → 创建数据库，每个队友电脑不同还可能踩坑 |
| **Redis（缓存）** | 存临时的东西：登录黑名单、标注缓存…… | 同上，又要单独安装 |
| **MinIO（文件存储）** | 存图片和模型文件本身（数据库只存文件路径） | 又要再装一个 |

**有了 Docker，以上三个东西各只需一条命令。**

### 为什么对团队协作特别有用？

```
队友A（Windows 11）：docker run ... → 环境好了
队友B（macOS）：   docker run ... → 完全一样的环境
队友C（Linux）：   docker run ... → 完全一样的环境
服务器部署：       docker run ... → 和开发时一模一样
```

不会出现"我电脑上能跑啊"这种情况。大家的 PostgreSQL 都是同一个版本、同一个配置。

### 总结

Docker 在这个项目里就做一件事：**让你不用折腾环境，把时间花在写代码上。**

---

## 二、安装 Docker Desktop

### Windows

1. 打开 https://www.docker.com/products/docker-desktop/
2. 下载 **Docker Desktop for Windows**，按提示安装
3. 安装完成后，启动 Docker Desktop（在开始菜单找）
4. 等它右下角状态变绿（`Engine running`）
5. 打开终端（PowerShell / Git Bash / CMD），输入以下命令验证：

```bash
docker --version
```

如果输出类似 `Docker version 27.x.x` 就说明安装成功。

### macOS

1. 打开 https://www.docker.com/products/docker-desktop/
2. 下载对应芯片版本（Apple Silicon 选 Apple Chip，Intel 选 Intel Chip）
3. 拖入 Applications 文件夹，启动 Docker Desktop
4. 顶部菜单栏出现鲸鱼图标，等它变成静止状态
5. 终端输入 `docker --version` 验证

### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install docker.io docker-compose -y
sudo systemctl enable docker --now
sudo usermod -aG docker $USER   # 免 sudo 运行，需重新登录生效
```

---

## 三、本项目数据库启动命令

### 3.1 启动 PostgreSQL（一条命令）

打开终端，复制以下整条命令执行：

```bash
docker run --name pg-local \
  -e POSTGRES_PASSWORD=123456 \
  -e POSTGRES_DB=detection_platform \
  -p 5432:5432 \
  -d postgres:16
```

**参数解释**：

| 参数 | 含义 |
|------|------|
| `--name pg-local` | 给容器起个名字，方便后续操作 |
| `-e POSTGRES_PASSWORD=123456` | 设置数据库密码 |
| `-e POSTGRES_DB=detection_platform` | 自动创建名为 `detection_platform` 的数据库 |
| `-p 5432:5432` | 把容器的 5432 端口映射到本机 5432，这样代码通过 `localhost:5432` 就能连接 |
| `-d postgres:16` | 使用 PostgreSQL 16 镜像，后台运行 |

### 3.2 创建 16 张业务表

数据库启动后，进入 `backend/` 目录执行：

```bash
docker exec -i pg-local psql -U postgres -d detection_platform < backend/scripts/init_db.sql
```

输出 `CREATE TABLE` × 16 即成功。

### 3.3 验证

```bash
docker exec pg-local psql -U postgres -d detection_platform -c "\dt"
```

应看到 16 张表。

---

## 四、常用操作速查

### 查看容器状态

```bash
docker ps                     # 只看运行中的
docker ps -a                  # 包含已停止的
```

### 启动/停止/重启

```bash
docker start pg-local         # 启动（容器已存在但停止时）
docker stop pg-local          # 停止
docker restart pg-local       # 重启
```

### 进入数据库命令行

```bash
docker exec -it pg-local psql -U postgres -d detection_platform
```

进入后在 `detection_platform=#` 提示符下可以执行 SQL：

```sql
SELECT * FROM users;           -- 查用户表
\d                             -- 列出所有表
\q                             -- 退出
```

### 删除容器（从头再来）

```bash
docker rm -f pg-local          # 强制删除容器（数据会丢失！）
```

然后重新执行 3.1 的命令即可重建。

### 查看容器日志

```bash
docker logs pg-local           # 查看全部日志
docker logs -f pg-local        # 实时跟踪日志（Ctrl+C 退出）
```

---

## 五、配置 .env 连接数据库

在 `backend/` 目录下创建 `.env` 文件（不要提交 Git）：

```
DATABASE_URL=postgresql://postgres:123456@localhost:5432/detection_platform
SECRET_KEY=dev-secret-key-change-in-production
ACCESS_TOKEN_EXPIRE_HOURS=24
REFRESH_TOKEN_EXPIRE_DAYS=7
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=detection-platform
```

模板文件 `.env.example` 已提交到仓库，可参考格式。

---

## 六、常见问题

### Q1: 启动时提示端口被占用

```
Error: port is already allocated
```

**解决**：说明 5432 端口已被占用（可能是本地装了 PostgreSQL）。改映射端口：

```bash
docker run --name pg-local -e POSTGRES_PASSWORD=123456 -e POSTGRES_DB=detection_platform -p 5433:5432 -d postgres:16
```

同时把 `.env` 中的 `DATABASE_URL` 端口也改为 `5433`。

### Q2: Docker Desktop 启动后一直转圈

**解决**：
1. 重启电脑
2. 检查是否开启了 Windows 虚拟化（BIOS 中启用 Hyper-V / WSL2）
3. Windows 家庭版可能需要 WSL2：管理员终端运行 `wsl --install`

### Q3: `docker ps` 看不到容器

**解决**：容器可能已经停止了。试 `docker ps -a`。如果状态是 `Exited`，用 `docker start pg-local` 重新启动。

### Q4: 电脑重启后数据库还在吗？

**在**。Docker 容器的数据是持久化的，重启电脑后：
```bash
docker start pg-local        # 重新启动容器即可
```

### Q5: 想完全清空数据库重新建表

```bash
docker exec -i pg-local psql -U postgres -d detection_platform -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker exec -i pg-local psql -U postgres -d detection_platform < backend/scripts/init_db.sql
```

### Q6: 密码 `123456` 太简单了

这只是本地开发用的，不会暴露到公网。如果介意，改掉后同步更新 `.env` 中的 `DATABASE_URL`。

### Q7: Docker 占用多少磁盘？

PostgreSQL 16 镜像约 450MB，加上空数据库基本不占额外空间。如果担心磁盘，定期运行：

```bash
docker system prune -a      # 清理所有未使用的镜像和容器
```

---

## 七、后续任务 6 预告

当前是手动一条条敲命令。等任务 6 完成后，会提供一个 `docker-compose.yml` 文件，届时一条命令就能同时启动 PostgreSQL + Redis + MinIO：

```bash
docker-compose up -d
```

队友拿到代码后只需这一条命令，所有环境就全部就绪。
