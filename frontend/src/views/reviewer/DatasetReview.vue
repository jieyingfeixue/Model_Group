<template><div class="page">
  <div class="hero">
    <div>
      <h1>✅ 数据集审核</h1>
      <p>审核用户提交公开申请的数据集，检查数据质量、标注完整性和合规性。</p>
    </div>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="icon">📋</div><h2>{{ items.length }}</h2><span>待审核数据集</span></div>
    <div class="stat-card"><div class="icon">🔍</div><h2>{{ items.filter(i=>i.review_status==='reviewing').length }}</h2><span>审核中</span></div>
    <div class="stat-card"><div class="icon">✅</div><h2>{{ items.filter(i=>i.review_status==='approved').length }}</h2><span>已通过</span></div>
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
      <el-table-column label="操作" width="320" align="center">
        <template #default="{row}">
          <el-button size="small" plain @click="$router.push('/datasets/'+row.dataset_id)">查看详情</el-button>
          <el-button v-if="row.review_status==='submitted'" size="small" type="primary" @click="onClaim(row)">认领</el-button>
          <el-button v-if="row.review_status==='reviewing'" size="small" type="success" @click="onVerdict(row,'approved')">通过</el-button>
          <el-button v-if="row.review_status==='reviewing'" size="small" type="danger" @click="onVerdict(row,'rejected')">驳回</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>

  <el-dialog v-model="detailVisible" title="15项检查清单" width="750px">
    <p style="color:#64748b;margin-bottom:16px;">正在审核：<strong>{{ currentDataset?.name }}</strong></p>
    <el-table :data="checklist" size="small">
      <el-table-column prop="id" label="编号" width="60" />
      <el-table-column prop="name" label="检查项" width="220" />
      <el-table-column prop="method" label="方式" width="90" />
      <el-table-column label="结果" width="200">
        <template #default="{row}">
          <el-radio-group v-model="row.result" size="small">
            <el-radio value="pass">通过</el-radio>
            <el-radio value="na">不适用</el-radio>
            <el-radio value="fail">存在问题</el-radio>
          </el-radio-group>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button @click="detailVisible=false">取消</el-button>
      <el-button type="primary" @click="onSubmitReview">提交审核</el-button>
    </template>
  </el-dialog>
</div></template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '@/api/request'

const router = useRouter()
const items = ref([])
const loading = ref(false)
const detailVisible = ref(false)
const currentDataset = ref(null)

const checklist = reactive([
  {id:'A1',name:'文件格式合法性',method:'系统自动',result:'pass'},
  {id:'A2',name:'数据完整性',method:'人工判断',result:'pass'},
  {id:'A3',name:'图片质量',method:'人工判断',result:'pass'},
  {id:'A4',name:'标注状态标记准确性',method:'人工判断',result:'pass'},
  {id:'A5',name:'数据去重',method:'系统自动',result:'pass'},
  {id:'A6',name:'标签合法性',method:'系统自动',result:'pass'},
  {id:'A7',name:'标注框规范性',method:'系统自动',result:'pass'},
  {id:'A8',name:'深度值合理性',method:'系统自动',result:'pass'},
  {id:'A9',name:'元信息完整性',method:'系统自动',result:'pass'},
  {id:'A10',name:'数据集描述一致性',method:'人工判断',result:'pass'},
  {id:'A11',name:'命名规范',method:'系统自动',result:'pass'},
  {id:'A12',name:'数据脱敏',method:'人工判断',result:'pass'},
  {id:'A13',name:'多模态对齐检查',method:'人工判断',result:'na'},
  {id:'A14',name:'帧对齐/补齐合理性',method:'人工判断',result:'na'},
  {id:'A15',name:'标注深度来源标注',method:'人工判断',result:'pass'}
])

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
    currentDataset.value = row
    detailVisible.value = true
    ElMessage.success('已认领，请逐项检查后提交审核结果')
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '认领失败') }
}

async function onVerdict(row, verdict) {
  currentDataset.value = row
  // 直接提交（跳过清单弹窗）
  try {
    await request.post(`/review/datasets/${row.dataset_id}/verdict`, { verdict, notes: {} })
    row.review_status = verdict
    ElMessage.success(verdict === 'approved' ? '审核已通过' : '已驳回')
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '操作失败') }
}

async function onSubmitReview() {
  if (!currentDataset.value) return
  const failItems = checklist.filter(c => c.result === 'fail')
  const verdict = failItems.length > 0 ? 'rejected' : 'approved'
  const notes = { checklist: checklist.map(c => ({id:c.id, result:c.result})) }
  try {
    await request.post(`/review/datasets/${currentDataset.value.dataset_id}/verdict`, { verdict, notes })
    const row = items.value.find(i => i.dataset_id === currentDataset.value.dataset_id)
    if (row) row.review_status = verdict
    detailVisible.value = false
    ElMessage.success(verdict === 'approved' ? '审核已通过' : '已驳回，原因已记录')
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '提交失败') }
}

onMounted(fetchItems)
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