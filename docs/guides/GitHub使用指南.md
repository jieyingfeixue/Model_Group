# GitHub 使用指南

> 适用场景：三人小组协作，都是 GitHub 新手
> 仓库地址：https://github.com/jieyingfeixue/Model_Group.git

---

## 一、核心工作流（每天必做）

```
打开电脑 → git pull（拉取队友最新代码）→ 写自己的代码 → git add + commit + push（提交自己的代码）
```

### 四步走

| 步骤 | 命令 | 含义 |
|------|------|------|
| ① 拉取 | `git pull origin main` | 把队友最新代码拉到本地 |
| ② 暂存 | `git add .` 或 `git add 具体文件名` | 告诉 Git 哪些文件要提交 |
| ③ 提交 | `git commit -m "做了什么"` | 在本地创建一次记录 |
| ④ 推送 | `git push origin main` | 把记录同步到 GitHub |

> ⚠️ **最重要的习惯：每天早上开工前先 `git pull`，每天收工前一定 `git push`。**

---

## 二、什么是分支

把 `main` 分支想象成**正式版**代码，其他分支是你的**草稿本**。你在草稿本上随便写，写得满意了再誊到正式版上。

```
main ────●────●────●────●────●  （永远是稳定的、能跑的代码）
              \
你的分支 ──────●────●────●  （你在这里随便折腾，不影响别人）
```

### 分支不是只包含你改的文件

你创建分支的那一刻，**整个项目都被完整复制到了新分支**：

```
main 分支：                  你的分支：
├── data/                    ├── data/              ← 一模一样
├── models/                  ├── models/            ← 一模一样
├── utils/                   ├── utils/             ← 一模一样
├── train.py  ← 旧版        ├── train.py  ← 你改的新版
├── predict.py               ├── predict.py         ← 一模一样
└── main.py                  └── main.py            ← 一模一样
```

> 所以测试完全没问题——你在自己分支上照样能跑 `python main.py`，所有依赖文件都在。

---

## 三、分支怎么用

### 第一步：创建并切换到新分支

```bash
git checkout -b 你的名字/功能名称
```

命名建议：`名字/功能`，例如 `jie/数据预处理`、`yang/模型训练`、`zhang/结果分析`

### 第二步：确认自己在哪里

```bash
git branch
```

输出中前面带 `*` 的就是你当前所在的分支。

### 第三步：正常写代码 & 提交

```bash
git add .
git commit -m "feat: 完成了数据清洗"
git push origin 你的分支名              # ← 注意！push 到你自己的分支，不是 main
```

> ⚠️ **你在哪个分支，`git push` 就推到哪个分支。只要你不 push 到 main，main 就永远是安全的。**

### 第四步：写完了，合并回 main

**方法 A：在 GitHub 网页上操作（推荐新手）**

1. `git push origin 你的分支名` 推送你的分支
2. 打开 GitHub 仓库页面，会看到绿色的 **"Compare & pull request"** 按钮
3. 点击，写个说明，点 **"Create pull request"**
4. 让队友看一眼，点 **"Merge pull request"** 就合并了

**方法 B：纯命令行**

```bash
git checkout main
git pull origin main                  # 先拉最新
git merge 你的分支名                   # 把你的分支合进来
git push origin main                  # 推上去
```

### 第五步：清理已合并的分支

```bash
git branch -d 你的分支名               # 删除本地分支
```

---

## 四、中途同步 main 的更新（重要）

当你在分支上写了一段时间，队友可能已经往 main 合并了新代码。把你的分支和 main 同步：

```bash
git checkout main                     # 切回 main
git pull origin main                  # 拉取最新
git checkout 你的分支名                # 切回你的分支
git merge main                        # 把 main 的新东西合进来
```

> 这就像：队友在正式版加了些东西，你先抄过来，然后继续在你的草稿本上写。这样最后合并时不会有冲突。

---

## 五、多人分支的工作流程

```
main ────●────●────────────●─────────●────  （稳定版）
          \                \         /
jie/预处理  ●────●──────────●───   /
                              \   /
yang/模型训练  ●────●────●────●───
```

三个人各开一个分支，同时推进，互不干扰：

| 你 | 分支名 | 做的事 |
|----|--------|--------|
| 队友A | `jie/数据预处理` | 数据清洗 |
| 队友B | `yang/模型训练` | 训练脚本 |
| 队友C | `zhang/结果分析` | 可视化 |

---

## 六、你合并到 main 后，队友的分支会怎样

> **队友的分支不会自动更新，不会自动崩溃，什么都不变。**

他们的分支还是合并之前的样子，你的新代码不在他们分支上。

### 场景图解

**初始状态：三个人分别从 main 拉分支**

```
main ──────●────────────────────
            │
jie/预处理  └──── ●──── ●──── ●  （在改 data_clean.py）
            
yang/模型训练└──── ●──── ●──── ●  （在改 train.py）
```

**jie 先把分支合并到 main：**

```
            jie 合并到 main
                  ↓
main ──────●────────────────●  ← main 现在包含 jie 的新代码了
            │                └── jie/预处理 的改动
jie/预处理  └──── ●──── ●────●
            
yang/模型训练└──── ●──── ●──── ●  ← 分支还是旧 main，没有 jie 的代码
```

### 队友写完了，也要合并时怎么办

队友必须先把你的代码同步到自己的分支：

```bash
# yang 的操作
git checkout main
git pull origin main               # main 现在有 jie 的 data_clean.py 了

git checkout yang/模型训练
git merge main                     # 把 main（含 jie 的改动）合进自己的分支
```

执行 `git merge main` 之后，队友的分支变成：

```
yang/模型训练（同步后）：
├── data_clean.py   ← jie 的代码，现在也有了 ✅
├── train.py        ← yang 改的新版
└── plot.py         ← 旧版
```

### 两种情况

**情况一：你们改的是不同文件**（jie 改 data_clean.py，yang 改 train.py）

```
Git 自动合并，毫无冲突 ✅
```

**情况二：你们改了同一个文件的同一行**

```
Git 发现冲突，标记出来让队友解决 ⚠️
```

队友会看到 `<<<<<<` `======` `>>>>>>` 标记，决定保留谁的版本。详细处理方法见第十章。

### 时间线总结

```
                        jie 合并到 main
                             ↓
main  ────●────────●─────────●────────────────●────
          │         \       /                  \
jie       └──●──●──●──●───┘                    \
                                                \
yang      └──●──●────●──●──●──●──  merge main  ──●──→ 合并
                            ↑
                         yang 同步 main 时，
                         jie 的代码进入 yang 的分支
```

> **一句话：你合并到 main 之后，队友的分支不会自动变化。他们需要在合并前用 `git merge main` 把你的代码同步到自己的分支里。**

---

## 七、你的分支，队友怎么测试

### 方法一：拉到本地跑

```bash
git fetch origin                          # 先看看远程有什么新分支
git checkout -b 分支名 origin/分支名       # 把队友的分支拉到本地
# 然后正常跑代码测试
git checkout main                         # 测试完切回 main
```

### 方法二：在 GitHub Pull Request 上看（更简单）

当你创建 Pull Request 后，队友在网页上就能看到：
- 你改了哪些文件、哪些行
- 绿色背景 = 新增的行，红色背景 = 删除的行
- 队友可以直接在网页上评论某一行代码

> 新手建议：Pull Request 上肉眼 review + 你自己跑的结果截图，对于现阶段来说就够了。

---

## 八、直接 push main vs 分支合并，有什么区别

| | 直接 push main | 分支 → 合并 |
|---|---|---|
| **代码审核** | ❌ 没人检查就直接生效 | ✅ 队友可以 review 再合并 |
| **出错后回滚** | 😰 要 `git revert` 回退，全队受影响 | 😊 不合并就行，分支删了重来 |
| **队友正在用 main** | 💥 你的 bug 直接炸到他们 | ✅ main 始终安全 |
| **能否反悔** | 已经进了 main，反悔很麻烦 | 随时可以删分支重做 |

> 一句话：**直接 push main = 你的草稿直接变成正式版，全队都用。**
> **分支合并 = 草稿写好 → 给队友看 → 确认无误 → 才变成正式版。**

---

## 九、如何避免冲突

1. **先 pull 再 push** —— 永远不要在没拉取最新代码的情况下直接 push
2. **小步提交** —— 写完一个小功能就 commit + push，不要攒一整天
3. **沟通分工** —— 在群里说一声"我在改 xxx 文件"，避免两个人同时改同一个文件

---

## 十、万一冲突了怎么办

如果 `git pull` 或 `git merge` 时报 "CONFLICT"：

1. VS Code 会高亮显示冲突的文件
2. 打开冲突文件，看到 `<<<<<<`、`======`、`>>>>>>` 标记
3. 和队友商量保留谁的代码，删除这些标记
4. 保存后执行：
   ```bash
   git add .
   git commit -m "fix: 解决合并冲突"
   git push origin main
   ```

---

## 十一、提交信息规范

```bash
git commit -m "feat: 添加了数据预处理模块"    # 新功能
git commit -m "fix: 修复了模型加载报错的问题"   # 修 bug
git commit -m "docs: 更新了readme说明"        # 文档
git commit -m "refactor: 重构了训练循环"      # 改代码结构但不改功能
```

---

## 十二、常用命令速查

```bash
# 查看状态
git status                     # 当前改了哪些文件
git branch                     # 查看本地分支
git branch -a                  # 查看所有分支（含远程）
git log --oneline              # 查看提交历史

# 基本操作
git pull origin main           # 拉取最新代码
git add .                      # 暂存所有修改
git commit -m "提交信息"        # 提交
git push origin 分支名          # 推送到远程

# 分支操作
git checkout -b 新分支名        # 创建 + 切换分支
git checkout main              # 切换到 main
git checkout 分支名             # 切换到某个分支
git merge 分支名                # 把"分支名"的代码合到当前分支
git branch -d 分支名            # 删除本地分支（合并完后清理）

# 拉取队友分支
git fetch origin                          # 查看远程新分支
git checkout -b 分支名 origin/分支名       # 拉取队友分支到本地
```

---

## 十三、每个人的日常操作流程

```bash
# === 早上来 ===
git checkout main             # 确保在 main
git pull origin main          # 拉取队友昨晚的更新

# === 开新功能 ===
git checkout -b 我的名字/功能名  # 创建自己的分支
# 写代码...

# === 写了一阵 ===
git add .
git commit -m "feat: 完成了xx功能"
git push origin 我的分支名

# === 收工前（如果功能做完了）===
# 到 GitHub 网页上创建 Pull Request
# 通知队友 review
# 队友确认后合并

# === 如果没做完，但想保存进度 ===
git add .
git commit -m "WIP: 日终保存进度"
git push origin 我的分支名       # 推到你的分支，不影响别人
```

---

## 十四、企业级仓库结构（参考）

> 这部分是企业的标准做法，了解即可，不需要现在就做到。

### 单仓库目录结构

```
project-name/
├── src/                        # 源代码
│   ├── controllers/            # 接口层（接收请求、返回响应）
│   ├── services/               # 业务逻辑层
│   ├── models/                 # 数据模型
│   └── utils/                  # 工具函数
├── tests/                      # 测试代码
├── docs/                       # 文档
├── scripts/                    # 脚本（部署、数据迁移等）
├── config/                     # 配置文件模板
├── .github/                    # GitHub 专属配置
│   ├── workflows/              # CI/CD 流水线
│   │   ├── test.yml            #   自动跑测试
│   │   └── deploy.yml          #   自动部署
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE/
│   └── CODEOWNERS              # 指定谁负责审查哪些代码
├── .gitignore
├── README.md                   # 项目说明
├── CONTRIBUTING.md             # 贡献规范
├── CHANGELOG.md                # 版本变更记录
├── LICENSE
├── Makefile                    # 常用命令入口
└── docker-compose.yml          # 本地开发环境
```

### 必须存在的四个文件

| 文件 | 作用 |
|------|------|
| `README.md` | 项目是干什么的、怎么安装、怎么跑 |
| `.gitignore` | 哪些文件不上传 Git（临时文件、密钥、依赖包等） |
| `LICENSE` | 开源协议（MIT、Apache 等） |
| `CONTRIBUTING.md` | 怎么写代码、怎么提 PR、代码风格要求 |

### 三种分支策略

**1. GitHub Flow（最简单，你们现在适合）**

```
main ──●────●────●────●  （随时可部署）
        \    \    /
feature1 ●──●──   /
feature2    ●──●──
```

- 只有 main 一个长期分支
- 新功能拉分支 → 开发 → PR → 合并

**2. Git Flow（最经典的企业模式）**

```
main     ──●─────────────────●────────●  （生产环境）
            \               /        /
release      ●────●────────●        /
              \                    /
develop  ──────●──●──●──●──●─────●  （开发主线）
                \    \    /
feature1         ●────●──/
feature2              ●──●──/
```

| 分支 | 用途 |
|------|------|
| `main` | 生产环境代码 |
| `develop` | 开发主线，日常集成 |
| `feature/*` | 新功能，从 develop 拉，合回 develop |
| `release/*` | 发布准备，从 develop 拉，合回 main + develop |
| `hotfix/*` | 紧急修复，从 main 拉，合回 main + develop |

**3. Trunk-Based（谷歌/脸书）**

- 所有人直接在 main 上小步提交
- 新功能用功能开关隐藏，做好了再打开
- 需要强大的 CI/CD 体系支撑

### 分支保护规则

企业仓库在 GitHub 上设置这些来保护 main：

| 规则 | 作用 |
|------|------|
| Require Pull Request | 禁止直接 push，必须走 PR |
| Require Approvals | 至少 1~2 人点 ✅ 同意才能合并 |
| Require status checks | CI 测试必须全部通过 |
| Require conversation resolution | 所有评论解决后才能合并 |

### PR 描述模板

```markdown
## 改动内容
<!-- 简述你做了什么 -->

## 改动原因
<!-- 为什么这么做 -->

## 测试方式
<!-- 怎么验证改动正确 -->

## Checklist
- [ ] 本地测试通过
- [ ] 文档已更新
```

### 提交信息规范（Conventional Commits）

```
<type>: <subject>

feat: 添加JWT令牌刷新机制
fix: 修复登录超时未重定向的问题
docs: 更新API接口文档
refactor: 重构用户认证模块
perf: 优化数据库查询性能
test: 补充登录模块单元测试
chore: 更新依赖包版本
ci: 添加自动部署流水线
```

### 版本号（Semantic Versioning）

格式：`主版本.次版本.修订号`，如 `v2.1.3`

| 数字 | 什么时候加 |
|------|------------|
| 主版本 (2.x.x) | 不兼容的 API 修改 |
| 次版本 (x.1.x) | 新增功能，向后兼容 |
| 修订号 (x.x.3) | 向后兼容的 bug 修复 |

### 你们现在 vs 企业级

| 方面 | 企业级 | 你们现在 |
|------|--------|----------|
| 分支 | main + develop + feature/* | main + 功能分支 |
| PR | 强制走 PR，必须 review | 可选，建议走 |
| 分支保护 | 多项规则锁死 main | 无 |
| CI/CD | 自动测试 + 自动部署 | 无 |
| 提交格式 | Conventional Commits | 自由格式 |
| 版本 | 语义化版本 + Tag + Release | 无 |
| 文档 | README + CONTRIBUTING + CHANGELOG | README |

> 可以逐步添加：先加 `.gitignore` 和分支保护，再加 PR 模板，最后上 CI 自动测试。

---

## 总结

| 建议 | 重要程度 |
|------|----------|
| 开工先 pull，收工必 push | 🔴 最重要 |
| 用分支开发，不要直接 push main | 🔴 最重要 |
| 及时沟通谁在改什么 | 🔴 最重要 |
| 小步提交，别攒代码 | 🟡 重要 |
| 统一提交信息格式 | 🟡 重要 |
| 定期用 `git merge main` 同步主分支 | 🟡 重要 |
