<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="card-header">
        <span class="logo">🎯</span>
        <h1>目标检测算法评测平台</h1>
        <p class="subtitle">创建新账号</p>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="onRegister">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="4-20 位字母或数字" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" placeholder="8-20 位，含大小写字母和数字"
            show-password />
          <div class="pw-strength" v-if="form.password">
            <span class="bar" :class="strengthClass"></span>
            <span class="label">{{ strengthLabel }}</span>
          </div>
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPw">
          <el-input v-model="form.confirmPw" type="password" placeholder="再次输入密码" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading" style="width:100%">
            注册
          </el-button>
        </el-form-item>
      </el-form>
      <p class="switch-link">已有账号？<router-link to="/login">返回登录</router-link></p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { register } from '@/api/auth'

const router = useRouter()
const formRef = ref(null)
const loading = ref(false)
const form = reactive({ username: '', email: '', password: '', confirmPw: '' })

const validateUser = (_rule, value, cb) => {
  if (!value) return cb(new Error('请输入用户名'))
  if (!/^[a-zA-Z0-9]{4,20}$/.test(value)) return cb(new Error('4-20 位字母或数字'))
  cb()
}
const validatePw = (_rule, value, cb) => {
  if (!value) return cb(new Error('请输入密码'))
  let score = 0
  if (value.length >= 8) score++
  if (/[a-z]/.test(value)) score++
  if (/[A-Z]/.test(value)) score++
  if (/[0-9]/.test(value)) score++
  if (score < 3) return cb(new Error('至少 8 位，包含大小写字母和数字中的两类'))
  cb()
}
const validateConfirm = (_rule, value, cb) => {
  if (value !== form.password) return cb(new Error('两次密码不一致'))
  cb()
}
const rules = {
  username: [{ required: true, validator: validateUser, trigger: 'blur' }],
  email: [{ required: true, type: 'email', message: '请输入正确的邮箱', trigger: 'blur' }],
  password: [{ required: true, validator: validatePw, trigger: 'blur' }],
  confirmPw: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
}

const strengthClass = computed(() => {
  const v = form.password
  if (!v) return ''
  let s = 0; if (v.length>=8) s++; if (/[a-z]/.test(v)) s++; if (/[A-Z]/.test(v)) s++; if (/[0-9]/.test(v)) s++
  return s <= 2 ? 'weak' : s === 3 ? 'medium' : 'strong'
})
const strengthLabel = computed(() => {
  const map = { weak: '弱', medium: '中', strong: '强' }
  return map[strengthClass.value] || ''
})

async function onRegister() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await register({ username: form.username, email: form.email, password: form.password })
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page { height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #f0f2f5 0%, #e2e8f0 100%); }
.auth-card { width: 420px; background: #fff; border-radius: 12px; padding: 40px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.08); }
.card-header { text-align: center; margin-bottom: 24px; }
.logo { font-size: 40px; }
h1 { font-size: 20px; margin: 10px 0 4px; color: #1a1a2e; }
.subtitle { font-size: 13px; color: #9ca3af; margin: 0; }
.pw-strength { display: flex; align-items: center; gap: 8px; margin-top: 6px; font-size: 12px; }
.bar { flex: 1; height: 4px; border-radius: 2px; background: #e5e7eb; }
.bar.weak { background: #ef4444; }
.bar.medium { background: #f59e0b; }
.bar.strong { background: #22c55e; }
.label { color: #6b7280; }
.switch-link { text-align: center; font-size: 13px; color: #6b7280; margin-top: 16px; }
.switch-link a { color: #3b82f6; }
</style>
