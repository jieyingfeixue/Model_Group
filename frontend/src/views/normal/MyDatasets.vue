<template>
<div class="page">
  <div class="hero">
    <div>
      <h1>我的数据集</h1>
      <p>管理个人创建的数据集，支持冻结、发布、归档及版本管理。</p>
    </div>
  </div>
  <div class="stats">
    <div class="stat-card">
      <div class="icon">📦</div>
      <h2>{{ allDatasets.length }}</h2>
      <span>数据集总数</span>
    </div>
    <div class="stat-card">
      <div class="icon">🚀</div>
      <h2>{{ allDatasets.filter(d=>d.status==='published').length }}</h2>
      <span>已发布</span>
    </div>
    <div class="stat-card">
      <div class="icon">📝</div>
      <h2>{{ allDatasets.filter(d=>d.status==='draft').length }}</h2>
      <span>草稿</span>
    </div>
  </div>

  <div class="toolbar">
      <div class="left">
          <el-button type="primary" size="large" @click="$router.push('/datasets/build')">+ 构建数据集</el-button>
      </div>
      <div class="right">
          <el-select v-model="filter.status" placeholder="状态筛选" clearable style="width:160px" @change="fetchList">
              <el-option label="全部" value=""/>
              <el-option label="草稿" value="draft"/>
              <el-option label="已冻结" value="frozen"/>
              <el-option label="已发布" value="published"/>
          </el-select>
      </div>
  </div>

  <div class="table-card" v-loading="loading">
    <el-table :data="datasets" style="margin-top:12px;">
      <el-table-column prop="name" label="数据集名称" />
      <el-table-column prop="version" label="版本" width="80" header-align="center" align="center" />
      <el-table-column prop="sample_count" label="样本数" width="100" header-align="center" align="center" />
      <el-table-column prop="status" label="状态" width="100" header-align="center" align="center">
        <template #default="{row}"><el-tag :type="statusType(row.status)" round effect="light">{{row.status}}</el-tag></template>
      </el-table-column>
      <el-table-column prop="visibility" label="可见范围" width="100" header-align="center" align="center" />
      <el-table-column prop="created_at" label="创建时间" width="160" header-align="center" align="center">
        <template #default="{row}">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="300" header-align="center" align="center">
        <template #default="{ row }">
          <el-button size="small" plain @click="$router.push('/datasets/' + row.dataset_id)">详情</el-button>
          <el-button v-if="row.status === 'draft'" size="small" type="success" round @click="onFreeze(row)">冻结</el-button>
          <el-button v-if="row.status === 'frozen'" size="small" type="warning" round @click="onPublish(row)">发布</el-button>
          <el-button size="small" type="danger" plain round @click="onArchive(row)">归档</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
  <el-empty v-if="!loading && datasets.length===0" description="暂无数据集，点击上方构建第一个数据集" />
</div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getMyDatasets,
  freezeDataset,
  publishDataset,
  archiveDataset,
} from '@/api/dataset'

const filter = reactive({ status: '' })
const allDatasets = ref([])
const datasets = ref([])
const loading = ref(false)

function statusType(s){ const map={draft:'info',frozen:'warning',published:'success'}; return map[s]||'info' }
function formatDate(v){ return v ? String(v).replace('T',' ').slice(0,19) : '-' }

async function fetchList() {
  loading.value = true
  try {
    const { data } = await getMyDatasets({
      page: 1,
      size: 100,
      status: filter.status || undefined,
    })
    datasets.value = data.items || []
    if (!filter.status) allDatasets.value = datasets.value
    else {
      const all = await getMyDatasets({ page: 1, size: 100 })
      allDatasets.value = all.data.items || []
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function onFreeze(row) {
  try {
    await freezeDataset(row.dataset_id)
    ElMessage.success('已冻结')
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '冻结失败')
  }
}

async function onPublish(row) {
  try {
    await publishDataset(row.dataset_id, { visibility: 'public' })
    ElMessage.success('已发布')
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发布失败')
  }
}

async function onArchive(row) {
  try {
    await ElMessageBox.confirm(`确认归档「${row.name}」？`, '提示', { type: 'warning' })
    await archiveDataset(row.dataset_id)
    ElMessage.success('已归档')
    await fetchList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '归档失败')
  }
}

onMounted(fetchList)
</script>

<style scoped>
.page{padding:28px;max-width:1450px;margin:auto;background:#f8fafc;min-height:100vh}
.hero{padding:45px 50px;margin-bottom:28px;border-radius:18px;color:white;background:linear-gradient(135deg,#0f172a,#1e3a8a);box-shadow:0 10px 30px rgba(30,64,175,.18)}
.hero h1{font-size:34px;margin-bottom:10px;font-weight:700}
.hero p{font-size:16px;line-height:1.8;opacity:.9;max-width:650px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-bottom:30px}
.stat-card{background:white;border-radius:18px;padding:28px;text-align:center;box-shadow:0 8px 22px rgba(15,23,42,.05)}
.icon{font-size:30px;margin-bottom:12px}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
.table-card{background:white;padding:20px;border-radius:20px;box-shadow:0 8px 24px rgba(15,23,42,.06)}
</style>
