<template>
  <div class="profile-page">
    <div class="profile-header">
      <router-link to="/home" style="color:#374151;text-decoration:none;">← 返回首页</router-link>
      <h1>个人中心</h1>
    </div>

    <div class="profile-body">
      <!-- 左侧：基本信息 -->
      <div class="info-card">
        <div class="avatar-section">
          <div class="avatar">{{ userStore.user?.username?.charAt(0)?.toUpperCase() || '?' }}</div>
          <div class="user-name">{{ userStore.user?.username }}</div>
          <div class="user-role" :style="{ color: roleColor }">{{ roleLabel }}</div>
        </div>

        <div class="info-table">
          <div class="info-row">
            <span class="label">用户名</span>
            <span class="value">{{ userStore.user?.username }}</span>
          </div>
          <div class="info-row">
            <span class="label">邮箱</span>
            <span class="value">{{ userStore.user?.email || '未设置' }}</span>
          </div>
          <div class="info-row">
            <span class="label">注册时间</span>
            <span class="value">2024-03-15</span>
          </div>
        </div>
      </div>

      <!-- 右侧：密码修改 + 操作历史 -->
      <div class="right-col">
        <!-- 功能入口 -->
        <div class="section-card">
          <h3>快捷入口</h3>
          <div class="quick-actions">
            <el-button @click="$router.push('/data')">我的数据集</el-button>
            <el-button @click="$router.push('/models')">我的模型</el-button>
            <el-button @click="$router.push('/eval')">我的评测</el-button>
          </div>
        </div>
        <div class="section-card">
          <h3>账号安全</h3>
          <el-button @click="pwDialogVisible = true">修改密码</el-button>
        </div>

        <!-- 操作历史 -->
        <div class="section-card">
          <h3>操作历史</h3>
          <el-table :data="history" style="width:100%;" size="small">
            <el-table-column prop="action" label="操作类型" width="140" />
            <el-table-column prop="target" label="操作对象" />
            <el-table-column prop="time" label="时间" width="180" />
          </el-table>
        </div>

        <!-- 修改密码弹窗 -->
        <el-dialog v-model="pwDialogVisible" title="修改密码" width="420px" center>
          <el-form :model="pwForm" :rules="pwRules" ref="pwFormRef" label-position="top">
            <el-form-item label="旧密码" prop="oldPw">
              <el-input v-model="pwForm.oldPw" type="password" show-password />
            </el-form-item>
            <el-form-item label="新密码" prop="newPw">
              <el-input v-model="pwForm.newPw" type="password" show-password />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirmPw">
              <el-input v-model="pwForm.confirmPw" type="password" show-password />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="pwDialogVisible = false">取消</el-button>
            <el-button type="primary" @click="onChangePw">确认修改</el-button>
          </template>
        </el-dialog>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

const roleLabel = computed(() => {
  const map = { normal: '普通用户', reviewer: '审核员', admin: '管理员' }
  return map[userStore.role] || '普通用户'
})
const roleColor = computed(() => {
  const map = { normal: '#3b82f6', reviewer: '#f59e0b', admin: '#ef4444' }
  return map[userStore.role] || '#3b82f6'
})

const pwDialogVisible = ref(false)
const pwFormRef = ref(null)
const pwForm = reactive({ oldPw: '', newPw: '', confirmPw: '' })
const validateConfirm = (_r, v, cb) => {
  if (v !== pwForm.newPw) return cb(new Error('两次密码不一致'))
  cb()
}
const pwRules = {
  oldPw: [{ required: true, message: '请输入旧密码', trigger: 'blur' }],
  newPw: [{ required: true, min: 8, message: '至少 8 位', trigger: 'blur' }],
  confirmPw: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
}
function onChangePw() {
  pwFormRef.value?.validate().then(() => {
    ElMessage.success('密码修改成功（Mock）')
    pwDialogVisible.value = false
    Object.assign(pwForm, { oldPw: '', newPw: '', confirmPw: '' })
  }).catch(() => {})
}

const history = [
  { action: '上传数据集', target: '可见光城市道路 v1', time: '2024-06-20 14:30' },
  { action: '发布数据集', target: '红外夜间场景 v2', time: '2024-06-18 09:15' },
  { action: '发起评测', target: 'YOLOv8-低光增强 vs 多模态检测 v1.0', time: '2024-06-15 16:42' },
  { action: '上传模型', target: 'Faster R-CNN ResNet-50 v1', time: '2024-06-12 11:08' },
  { action: '下载数据集', target: '官方红外障碍物基准 v1.0', time: '2024-06-10 08:20' },
]
</script>

<style scoped>
.profile-page { max-width: 1000px; margin: 0 auto; padding: 28px 20px; }
.profile-header { margin-bottom: 24px; }
.profile-header h1 { font-size: 22px; margin-top: 12px; }

.profile-body { display: flex; gap: 24px; align-items: flex-start; }
.info-card { width: 260px; background: #fff; border-radius: 10px; padding: 28px 20px;
  text-align: center; box-shadow: 0 1px 6px rgba(0,0,0,0.04); flex-shrink: 0; }
.avatar { width: 64px; height: 64px; border-radius: 50%; background: #3b82f6; color: #fff;
  display: flex; align-items: center; justify-content: center; font-size: 28px; font-weight: 700;
  margin: 0 auto 12px; }
.user-name { font-size: 17px; font-weight: 600; }
.user-role { font-size: 13px; margin-bottom: 16px; }
.info-table { text-align: left; border-top: 1px solid #f3f4f6; padding-top: 12px; }
.info-row { display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; }
.info-row .label { color: #6b7280; }
.info-row .value { color: #1a1a2e; font-weight: 500; }

.right-col { flex: 1; display: flex; flex-direction: column; gap: 20px; }
.section-card { background: #fff; border-radius: 10px; padding: 20px 24px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.04); }
.section-card h3 { font-size: 16px; margin-bottom: 14px; }
.quick-actions { display: flex; gap: 12px; }
</style>
