<template>
  <div class="profile-page">

    <!-- Hero -->
    <div class="hero">
      <div class="hero-content">
        <div>
          <h1>👤 个人中心</h1>
          <p>
            管理个人账户信息、账号安全、资源使用情况及历史操作，
            快速进入数据集、模型和评测模块。
          </p>
        </div>

        <div class="hero-user">
          <div class="hero-avatar">
            {{ userStore.user?.username?.charAt(0)?.toUpperCase() || '?' }}
          </div>

          <div class="hero-info">
            <h2>{{ userStore.user?.username }}</h2>

            <el-tag
              round
              effect="dark"
              :color="roleColor"
            >
              {{ roleLabel }}
            </el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- 顶部统计 -->
    <div class="stats">

      <div class="stat-card">
        <div class="icon">📂</div>
        <h2>{{ statistics.datasetCount }}</h2>
        <span>我的数据集</span>
      </div>

      <div class="stat-card">
        <div class="icon">🧠</div>
        <h2>{{ statistics.modelCount }}</h2>
        <span>我的模型</span>
      </div>

      <div class="stat-card">
        <div class="icon">📈</div>
        <h2>{{ statistics.evalCount }}</h2>
        <span>模型评测</span>
      </div>

    </div>

    <!-- 主体 -->
    <div class="main-layout">

      <!-- 左侧 -->
      <div class="left-panel">

        <!-- 基本信息 -->
        <div class="card profile-card">

          <div class="avatar">
            {{ userStore.user?.username?.charAt(0)?.toUpperCase() || '?' }}
          </div>

          <h2 class="user-name">
            {{ userStore.user?.username }}
          </h2>

          <el-tag
            round
            effect="dark"
            :color="roleColor"
            class="role-tag"
          >
            {{ roleLabel }}
          </el-tag>

          <div class="info-list">

            <div class="info-item">
              <span>用户名</span>
              <strong>{{ userStore.user?.username }}</strong>
            </div>

            <div class="info-item">
              <span>邮箱</span>
              <strong>{{ userStore.user?.email || '未设置' }}</strong>
            </div>

            <div class="info-item">
              <span>注册时间</span>
              <strong>2024-03-15</strong>
            </div>

            <div class="info-item">
              <span>账号状态</span>

              <el-tag
                type="success"
                round
              >
                正常
              </el-tag>
            </div>

          </div>
        
        <!-- 我的资源 -->
        <div class="resource-panel">

          <div class="panel-title">
            📊 我的资源
          </div>

          <div class="resource-item">
            <span>数据集</span>
            <strong>{{ statistics.datasetCount }}</strong>
          </div>

          <div class="resource-item">
            <span>模型</span>
            <strong>{{ statistics.modelCount }}</strong>
          </div>

          <div class="resource-item">
            <span>评测任务</span>
            <strong>{{ statistics.evalCount }}</strong>
          </div>

        </div>
        </div>
      </div>

      <!-- 右侧 -->
      <div class="right-panel">

        <!-- 账号安全 -->
        <div class="card">

          <div class="card-title">
            <span>🔒 账号安全</span>

            <el-button
              type="primary"
              @click="pwDialogVisible = true"
            >
              修改密码
            </el-button>
          </div>

          <div class="security-item">
            <span>安全等级</span>

            <el-progress
              :percentage="90"
              status="success"
              :stroke-width="10"
            />
          </div>

          <div class="security-item">
            <span>最近登录</span>

            <strong>2026-07-17 15:20</strong>
          </div>

          <div class="security-item">
            <span>登录设备</span>

            <strong>Windows · Chrome</strong>
          </div>

          <div class="security-item">
            <span>登录IP</span>

            <strong>127.0.0.1（Mock）</strong>
          </div>

        </div>

        <!-- 最近操作 -->
        <div class="card">

          <div class="card-title">
            <span>🕒 最近操作</span>
          </div>

          <el-timeline>

            <el-timeline-item
              v-for="(item,index) in history"
              :key="index"
              :timestamp="item.time"
              placement="top"
            >
              <h4>{{ item.action }}</h4>

              <p>{{ item.target }}</p>

            </el-timeline-item>

          </el-timeline>

        </div>

      </div>

    </div>

    <!-- 修改密码 -->
    <el-dialog
      v-model="pwDialogVisible"
      title="🔐 修改密码"
      width="520px"
    >

      <el-form
        ref="pwFormRef"
        :model="pwForm"
        :rules="pwRules"
        label-position="top"
      >

        <el-form-item
          label="旧密码"
          prop="oldPw"
        >
          <el-input
            v-model="pwForm.oldPw"
            type="password"
            show-password
          />
        </el-form-item>

        <el-form-item
          label="新密码"
          prop="newPw"
        >
          <el-input
            v-model="pwForm.newPw"
            type="password"
            show-password
          />
        </el-form-item>

        <el-form-item
          label="确认密码"
          prop="confirmPw"
        >
          <el-input
            v-model="pwForm.confirmPw"
            type="password"
            show-password
          />
        </el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="pwDialogVisible=false">
          取消
        </el-button>

        <el-button
          type="primary"
          @click="onChangePw"
        >
          保存修改
        </el-button>

      </template>

    </el-dialog>

  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

/* ---------------- 用户角色 ---------------- */

const roleLabel = computed(() => {
  const map = {
    normal: '普通用户',
    reviewer: '审核员',
    admin: '管理员'
  }
  return map[userStore.role] || '普通用户'
})

const roleTagType = computed(() => {
  const map = {
    normal: 'primary',
    reviewer: 'warning',
    admin: 'danger'
  }
  return map[userStore.role] || 'primary'
})

/* ---------------- 统计数据（Mock） ---------------- */

const statistics = reactive({
  datasetCount: 12,
  modelCount: 8,
  evalCount: 21
})

/* ---------------- 修改密码 ---------------- */

const pwDialogVisible = ref(false)

const pwFormRef = ref()

const pwForm = reactive({
  oldPw: '',
  newPw: '',
  confirmPw: ''
})

const validateConfirm = (rule, value, callback) => {
  if (!value) {
    callback(new Error('请再次输入密码'))
    return
  }

  if (value !== pwForm.newPw) {
    callback(new Error('两次密码输入不一致'))
  } else {
    callback()
  }
}

const pwRules = {
  oldPw: [
    {
      required: true,
      message: '请输入旧密码',
      trigger: 'blur'
    }
  ],

  newPw: [
    {
      required: true,
      message: '请输入新密码',
      trigger: 'blur'
    },
    {
      min: 8,
      message: '密码不少于8位',
      trigger: 'blur'
    }
  ],

  confirmPw: [
    {
      validator: validateConfirm,
      trigger: 'blur'
    }
  ]
}

function onChangePw() {
  pwFormRef.value.validate((valid) => {

    if (!valid) return

    ElMessage.success('密码修改成功（Mock）')

    pwDialogVisible.value = false

    pwForm.oldPw = ''
    pwForm.newPw = ''
    pwForm.confirmPw = ''
  })
}

/* ---------------- 最近操作 ---------------- */

const history = ref([
  {
    action: '上传数据集',
    target: '可见光城市道路 v1',
    time: '2026-07-16 14:30'
  },
  {
    action: '发布数据集',
    target: '红外夜间场景 v2',
    time: '2026-07-15 10:12'
  },
  {
    action: '上传模型',
    target: 'YOLOv11-LowLight',
    time: '2026-07-14 16:20'
  },
  {
    action: '发起模型评测',
    target: 'YOLOv11 VS RT-DETR',
    time: '2026-07-13 20:18'
  },
  {
    action: '下载官方数据集',
    target: 'LowAltitude Benchmark v1.0',
    time: '2026-07-12 09:42'
  }
])
</script>

<style scoped>
.profile-page{
    padding:28px;
    max-width:1450px;
    margin:auto;
    background:#f8fafc;
    min-height:100vh;
}

/* Hero */
.hero{
  padding:45px 50px;
  margin-bottom:28px;
  border-radius:18px;
  color:white;
  background: linear-gradient(135deg, #0f172a, #1e3a8a);
  box-shadow: 0 10px 30px rgba(30,64,175,.18);
}

.hero h1{
    font-size:34px;
    font-weight:700;
    margin-bottom:10px;
}

.hero p{
    font-size:16px;
    line-height:1.8;
    opacity:.92;
    max-width:700px;
}

/* 统计卡 */

.stats{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:22px;
    margin-bottom:28px;
}

.stat-card{
    background:#fff;
    border-radius:18px;
    padding:28px;
    text-align:center;
    border:1px solid #e2e8f0;
    box-shadow:
        0 8px 22px rgba(15,23,42,.05);
    transition:.3s;
}

.stat-card:hover{
    transform:translateY(-4px);
}

.icon{
    font-size:30px;
    margin-bottom:10px;
}

.stat-card h2{
    font-size:34px;
    color:#2563eb;
    margin-bottom:8px;
}

.stat-card span{
    color:#64748b;
}

/* 主布局 */

.main-layout{
    display:grid;
    grid-template-columns:340px 1fr;
    gap:24px;
}

.left-panel,
.right-panel{
    display:flex;
    flex-direction:column;
    gap:24px;
}

/* 卡片 */

.card{
    background:#fff;
    border-radius:20px;
    padding:26px;
    border:1px solid #e2e8f0;
    box-shadow:
        0 8px 24px rgba(15,23,42,.05);
}

/* 头像 */

.profile-card{
    text-align:center;
    min-height:520px;
}

.avatar{
    width:96px;
    height:96px;
    border-radius:50%;
    margin:auto;
    margin-bottom:18px;

    display:flex;
    align-items:center;
    justify-content:center;

    font-size:38px;
    font-weight:700;
    color:#fff;

    background:
        linear-gradient(
            135deg,
            #2563eb,
            #60a5fa
        );

    box-shadow:
        0 10px 28px rgba(37,99,235,.28);
}

.profile-card h2{
    font-size:24px;
    margin-bottom:14px;
    color:#0f172a;
}

.role-tag{
    margin-bottom:20px;
}

/* 信息 */

.info-list{
    margin-top:20px;
}

.info-item{
    display:flex;
    justify-content:space-between;
    align-items:center;

    padding:14px 16px;
    margin-bottom:12px;

    border-radius:12px;

    background:#f8fafc;

    transition:.25s;
}

.info-item:hover{
    background:#eff6ff;
}

.info-item span{
    color:#64748b;
}

.info-item strong{
    color:#0f172a;
}

/* =======================
   我的资源
======================= */

.resource-panel{

    margin-top:28px;

    padding-top:22px;

    border-top:1px solid #e2e8f0;

}

.panel-title{

    font-size:16px;

    font-weight:700;

    color:#1e293b;

    margin-bottom:18px;

}

.resource-item{

    display:flex;

    justify-content:space-between;

    align-items:center;

    padding:12px 14px;

    margin-bottom:12px;

    border-radius:12px;

    background:#f8fafc;

    transition:.3s;

}

.resource-item:hover{

    background:#eff6ff;

    transform:translateX(4px);

}

.resource-item span{

    color:#64748b;

}

.resource-item strong{

    color:#2563eb;

    font-size:18px;

    font-weight:700;

}

/* 标题 */

.card-title{
    display:flex;
    justify-content:space-between;
    align-items:center;

    margin-bottom:18px;

    font-size:18px;
    font-weight:700;

    color:#1e293b;
}

/* 安全 */

.security-row{
    margin-bottom:20px;
}

.security-row span{
    display:block;
    margin-bottom:8px;
    color:#64748b;
}

/* Dialog */

:deep(.el-dialog){
    border-radius:18px;
    overflow:hidden;
}

:deep(.el-dialog__header){
    background:#f8fafc;
    padding:20px 24px;
    font-weight:700;
}

:deep(.el-dialog__body){
    padding:24px;
}

/* Timeline */

:deep(.el-timeline-item__node){
    background:#2563eb;
}

:deep(.el-progress-bar__outer){
    border-radius:20px;
}

:deep(.el-button){
    border-radius:10px;
}

:deep(.el-input__wrapper){
    border-radius:10px;
}

/* 响应式 */

@media (max-width:1100px){

.main-layout{
    grid-template-columns:1fr;
}

.stats{
    grid-template-columns:1fr;
}

}
</style>