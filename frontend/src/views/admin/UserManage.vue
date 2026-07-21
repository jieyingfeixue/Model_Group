<template>
  <div class="page">
    <h2>用户管理</h2>
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索用户名/邮箱" clearable style="width:220px" @clear="fetchList" />
      <el-select v-model="role" clearable placeholder="角色" style="width:140px" @change="fetchList">
        <el-option label="全部" value="" />
        <el-option label="normal" value="normal" />
        <el-option label="reviewer" value="reviewer" />
        <el-option label="admin" value="admin" />
      </el-select>
      <el-button @click="fetchList">刷新</el-button>
      <el-button type="primary" @click="createVisible=true">新建用户</el-button>
    </div>

    <div class="card" v-loading="loading">
      <el-table :data="users">
        <el-table-column prop="user_id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="email" label="邮箱" min-width="160" />
        <el-table-column prop="role" label="角色" width="110" />
        <el-table-column prop="is_active" label="状态" width="90">
          <template #default="{row}">
            <el-tag :type="row.is_active?'success':'danger'" size="small">{{ row.is_active?'启用':'停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260">
          <template #default="{row}">
            <el-button size="small" @click="onRole(row)">改角色</el-button>
            <el-button size="small" :type="row.is_active?'danger':'success'" @click="onToggle(row)">
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="createVisible" title="新建用户" width="420px">
      <el-form :model="form" label-position="top">
        <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width:100%">
            <el-option label="normal" value="normal" />
            <el-option label="reviewer" value="reviewer" />
            <el-option label="admin" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUsers, createUser, setUserRole, toggleUserStatus } from '@/api/admin'

const users = ref([])
const loading = ref(false)
const saving = ref(false)
const keyword = ref('')
const role = ref('')
const createVisible = ref(false)
const form = reactive({ username: '', email: '', password: '', role: 'normal' })

async function fetchList() {
  loading.value = true
  try {
    const { data } = await getUsers({
      page: 1,
      size: 100,
      keyword: keyword.value || undefined,
      role: role.value || undefined,
    })
    users.value = data.items || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败（需 admin）')
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  saving.value = true
  try {
    await createUser({ ...form })
    ElMessage.success('已创建')
    createVisible.value = false
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    saving.value = false
  }
}

async function onRole(row) {
  try {
    const { value } = await ElMessageBox.prompt('新角色: normal / reviewer / admin', '修改角色', {
      inputValue: row.role,
    })
    await setUserRole(row.user_id, { role: value })
    ElMessage.success('已更新角色')
    await fetchList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '更新失败')
  }
}

async function onToggle(row) {
  try {
    await toggleUserStatus(row.user_id, { is_active: !row.is_active })
    ElMessage.success('已更新状态')
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

onMounted(fetchList)
</script>

<style scoped>
.page{padding:24px;max-width:1100px;margin:0 auto}
.toolbar{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.card{background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
</style>
