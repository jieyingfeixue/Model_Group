<template><div class="page">
  <div class="hero">
    <div>
      <h1>✅ 数据集审核</h1>
      <p>审核用户提交公开申请的数据集，检查数据质量、标注完整性和合规性。</p>
    </div>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="icon">📋</div><h2>{{ stats.pending_datasets }}</h2><span>待审核</span></div>
    <div class="stat-card"><div class="icon">🔍</div><h2>{{ stats.claimed_datasets }}</h2><span>审核中</span></div>
    <div class="stat-card"><div class="icon">✅</div><h2>{{ stats.approved_datasets }}</h2><span>已通过</span></div>
  </div>

  <div class="table-card">
    <el-table :data="items" stripe v-loading="loading">
      <el-table-column prop="name" label="数据集名称" min-width="200" />
      <el-table-column prop="owner_name" label="提交者" width="120" />
      <el-table-column prop="sample_count" label="样本数" width="80" align="center" />
      <el-table-column prop="review_status" label="审核状态" width="110" align="center">
        <template #default="{row}">
          <el-tag v-if="row.review_status==='submitted'" type="warning" round size="small">待审核</el-tag>
          <el-tag v-else-if="row.review_status==='reviewing'" type="primary" round size="small">审核中</el-tag>
          <el-tag v-else-if="row.review_status==='approved'" type="success" round size="small">已通过</el-tag>
          <el-tag v-else-if="row.review_status==='rejected'" type="danger" round size="small">已驳回</el-tag>
          <span v-else style="color:#94a3b8;font-size:12px">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="提交时间" width="120" />
      <el-table-column label="操作" width="280" align="center">
        <template #default="{row}">
          <el-button size="small" plain @click="$router.push('/datasets/'+row.dataset_id)">查看详情</el-button>
          <el-button v-if="row.review_status==='submitted'" size="small" type="primary" @click="onClaim(row)">认领</el-button>
          <el-button v-if="row.review_status==='reviewing'" size="small" type="warning" @click="$router.push('/review/datasets/'+row.dataset_id)">审核</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</div></template>

<script setup>
import { ref, onMounted, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/api/request'

const items = ref([])
const loading = ref(false)
const stats = ref({ pending_datasets: 0, claimed_datasets: 0, approved_datasets: 0 })

async function fetchStats() {
  try {
    const { data } = await request.get('/review/stats')
    stats.value = data
  } catch { /* ignore */ }
}

async function fetchItems() {
  loading.value = true
  try {
    const { data } = await request.get('/review/datasets')
    items.value = data.items || []
  } catch { items.value = [] }
  finally { loading.value = false }
}

async function onClaim(row) {
  try {
    await request.post(`/review/datasets/${row.dataset_id}/claim`)
    row.review_status = 'reviewing'
    stats.value.pending_datasets = Math.max(0, stats.value.pending_datasets - 1)
    stats.value.claimed_datasets += 1
    ElMessage.success('已认领，点击"审核"开始审核')
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '认领失败') }
}

onMounted(() => { fetchStats(); fetchItems() })
onActivated(() => { fetchStats(); fetchItems() })
</script>

<style scoped>
.page{padding:28px;max-width:1450px;margin:auto;background:#f8fafc;min-height:100vh}
.hero{padding:45px 50px;margin-bottom:28px;border-radius:18px;color:white;
  background:linear-gradient(135deg,#0f172a,#1e3a8a);
  box-shadow:0 10px 30px rgba(30,64,175,.18)}
.hero h1{font-size:34px;font-weight:700;margin-bottom:12px}
.hero p{font-size:16px;opacity:.92;line-height:1.8;max-width:650px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-bottom:30px}
.stat-card{background:white;border-radius:18px;padding:28px;text-align:center;
  box-shadow:0 8px 22px rgba(15,23,42,.05);transition:.3s}
.stat-card:hover{transform:translateY(-6px)}
.stat-card .icon{font-size:30px;margin-bottom:12px}
.stat-card h2{font-size:34px;color:#2563eb;margin:8px 0}
.stat-card span{color:#64748b}
.table-card{background:white;padding:22px;border-radius:20px;
  box-shadow:0 8px 24px rgba(15,23,42,.06)}
</style>