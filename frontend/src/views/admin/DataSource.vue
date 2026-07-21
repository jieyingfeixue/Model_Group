<template>
  <div class="page">
    <h2>数据源管理</h2>
    <div class="toolbar">
      <el-button type="primary" @click="createVisible=true">新建数据源</el-button>
      <el-button @click="fetchList">刷新</el-button>
    </div>
    <div class="card" v-loading="loading">
      <el-table :data="sources">
        <el-table-column prop="source_id" label="ID" width="70" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="source_type" label="类型" width="120" />
        <el-table-column prop="modality" label="模态" width="100" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column label="操作" width="360">
          <template #default="{row}">
            <el-button size="small" @click="onTest(row)">测试</el-button>
            <el-button size="small" type="primary" @click="onSync(row)">同步</el-button>
            <el-button size="small" @click="onSensors(row)">传感器</el-button>
            <el-button size="small" type="danger" @click="onClean(row)">清理</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !sources.length" description="暂无数据源" />
    </div>

    <el-dialog v-model="createVisible" title="新建数据源" width="520px">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.source_type" style="width:100%">
            <el-option label="local_dir" value="local_dir" />
            <el-option label="oss_bucket" value="oss_bucket" />
            <el-option label="s3" value="s3" />
          </el-select>
        </el-form-item>
        <el-form-item label="模态">
          <el-select v-model="form.modality" style="width:100%">
            <el-option label="visible" value="visible" />
            <el-option label="infrared" value="infrared" />
            <el-option label="mmwave" value="mmwave" />
            <el-option label="lidar" value="lidar" />
          </el-select>
        </el-form-item>
        <el-form-item label="connection_info (JSON)">
          <el-input v-model="connJson" type="textarea" :rows="5" placeholder='{"path":"D:/data"} 或 {"bucket":"xxx","endpoint":"localhost:9000"}' />
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
import {
  listDataSources,
  createDataSource,
  testConnection,
  syncSource,
  configureSensors,
  cleanSource,
} from '@/api/admin'

const sources = ref([])
const loading = ref(false)
const saving = ref(false)
const createVisible = ref(false)
const connJson = ref('{"path":""}')
const form = reactive({
  name: '',
  source_type: 'local_dir',
  modality: 'visible',
  status: 'inactive',
})

async function fetchList() {
  loading.value = true
  try {
    const { data } = await listDataSources()
    sources.value = Array.isArray(data) ? data : (data.items || [])
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败（需 admin）')
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  saving.value = true
  try {
    const connection_info = JSON.parse(connJson.value || '{}')
    await createDataSource({ ...form, connection_info })
    ElMessage.success('已创建')
    createVisible.value = false
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '创建失败')
  } finally {
    saving.value = false
  }
}

async function onTest(row) {
  try {
    const { data } = await testConnection(row.source_id)
    ElMessage[data.ok ? 'success' : 'error'](data.detail || JSON.stringify(data))
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '测试失败')
  }
}

async function onSync(row) {
  try {
    const { data } = await syncSource(row.source_id, { force: false, limit: 100 })
    ElMessage.success(`扫描 ${data.scanned} 项`)
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '同步失败')
  }
}

async function onSensors(row) {
  try {
    const { value } = await ElMessageBox.prompt('传感器配置 JSON', '配置传感器', {
      inputValue: JSON.stringify(row.connection_info?.sensors || { visible: true }, null, 2),
      inputType: 'textarea',
    })
    await configureSensors(row.source_id, { sensors: JSON.parse(value) })
    ElMessage.success('已保存')
    await fetchList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || e?.message || '保存失败')
  }
}

async function onClean(row) {
  try {
    await cleanSource(row.source_id)
    ElMessage.success('已清理')
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '清理失败')
  }
}

onMounted(fetchList)
</script>

<style scoped>
.page{padding:24px;max-width:1100px;margin:0 auto}
.toolbar{display:flex;gap:8px;margin-bottom:16px}
.card{background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
</style>
