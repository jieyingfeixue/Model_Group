<template><div class="page">
  <div class="hero">
    <div>
      <h1>🔍 标注审核</h1>
      <p>审核用户提交的标注数据，逐张检查检测框、类别、深度值的准确性和规范性。</p>
    </div>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="icon">📋</div><h2>{{ items.length }}</h2><span>待审核标注</span></div>
    <div class="stat-card"><div class="icon">✅</div><h2>{{ items.filter(i=>i.review_status==='approved').length }}</h2><span>已通过</span></div>
    <div class="stat-card"><div class="icon">❌</div><h2>{{ items.filter(i=>i.review_status==='rejected').length }}</h2><span>已驳回</span></div>
  </div>

  <div class="table-card">
    <el-table :data="items" stripe v-loading="loading">
      <el-table-column prop="resource_id" label="资源ID" width="90" align="center" />
      <el-table-column prop="review_status" label="状态" width="100" align="center">
        <template #default="{row}">
          <el-tag v-if="row.review_status==='pending'" type="warning" round size="small">待审核</el-tag>
          <el-tag v-else-if="row.review_status==='approved'" type="success" round size="small">已通过</el-tag>
          <el-tag v-else-if="row.review_status==='rejected'" type="danger" round size="small">已驳回</el-tag>
          <span v-else style="color:#94a3b8;font-size:12px">{{ row.review_status }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="bboxes" label="标注数量" width="80" align="center">
        <template #default="{row}">{{ row.bboxes?.length || 0 }} 框</template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="70" align="center" />
      <el-table-column prop="updated_at" label="提交时间" width="120" />
      <el-table-column label="操作" width="300" align="center">
        <template #default="{row}">
          <el-button size="small" plain @click="openDetail(row)">查看标注详情</el-button>
          <el-button v-if="row.review_status==='pending'" size="small" type="success" @click="onVerdict(row,'approved')">通过</el-button>
          <el-button v-if="row.review_status==='pending'" size="small" type="danger" @click="openReject(row)">驳回</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>

  <!-- 标注详情弹窗 -->
  <el-dialog v-model="detailVisible" title="标注详情" width="900px" top="5vh">
    <div class="detail-body" v-if="currentItem">
      <div class="preview-area">
        <ImagePreview
          :imageUrl="'/api/images/' + currentItem.resource_id"
          :bboxes="currentItem.bboxes || []"
          :showAnnotations="true"
          :categoryLabels="categoryLabels"
        />
      </div>
      <div class="bbox-list">
        <h4>标注框列表（{{ currentItem.bboxes?.length || 0 }} 个）</h4>
        <div v-for="(b,i) in currentItem.bboxes" :key="i" class="bbox-card">
          <div class="bbox-header">
            <span class="bbox-cat">{{ categoryName(b.category_id) }}</span>
            <span class="bbox-depth">{{ b.depth }}m</span>
          </div>
          <div class="bbox-meta">坐标: {{ b.x?.toFixed(2) }}, {{ b.y?.toFixed(2) }} — {{ (b.w)?.toFixed(2) }}×{{ (b.h)?.toFixed(2) }}</div>
          <div class="bbox-tags">
            <el-tag size="small" v-if="b.occlusion" type="warning">遮挡: {{ b.occlusion }}</el-tag>
            <el-tag size="small" v-if="b.truncation" type="info">截断: {{ b.truncation }}</el-tag>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="detailVisible=false">关闭</el-button>
      <el-button type="success" @click="onVerdict(currentItem,'approved')">通过</el-button>
      <el-button type="danger" @click="openReject(currentItem)">驳回</el-button>
    </template>
  </el-dialog>

  <!-- 驳回弹窗 -->
  <el-dialog v-model="rejectVisible" title="驳回原因" width="550px">
    <p style="color:#64748b;margin-bottom:12px">资源 #{{ currentItem?.resource_id }} — 请选择驳回原因：</p>
    <el-checkbox-group v-model="selectedRejectReasons" class="reject-list">
      <el-checkbox v-for="t in rejectOptions" :key="t.code" :label="t.code" class="reject-item">
        <strong>{{ t.code }}</strong> {{ t.label }}
      </el-checkbox>
    </el-checkbox-group>
    <template #footer>
      <el-button @click="rejectVisible=false">取消</el-button>
      <el-button type="danger" @click="submitReject">确认驳回</el-button>
    </template>
  </el-dialog>
</div></template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/api/request'
import ImagePreview from '@/components/canvas/ImagePreview.vue'

const items = ref([])
const loading = ref(false)
const detailVisible = ref(false)
const rejectVisible = ref(false)
const currentItem = ref(null)
const selectedRejectReasons = ref([])

const categoryLabels = ref([
  { id: 1, name: '电线杆' }, { id: 2, name: '桥梁' },
  { id: 3, name: '建筑物' }, { id: 4, name: '树木' }, { id: 5, name: '路灯' },
])

const rejectOptions = [
  {code:'T01',label:'检测框位置偏移，未完全包围目标'},
  {code:'T02',label:'检测框尺寸不准确（过大/过小）'},
  {code:'T03',label:'目标类别标注错误'},
  {code:'T04',label:'漏标：图片中存在未标注的障碍物'},
  {code:'T05',label:'多标：将非障碍物区域误标为目标'},
  {code:'T06',label:'深度值明显偏差（与实际距离不符）'},
  {code:'T07',label:'遮挡程度标注错误'},
  {code:'T08',label:'截断程度标注错误'},
  {code:'T09',label:'标注框坐标越界（超出图片范围）'},
  {code:'T10',label:'图片质量不可标注（过曝/模糊/全黑）'},
]

function categoryName(id) {
  return categoryLabels.value.find(c => c.id === id)?.name || `类别${id}`
}

async function fetchItems() {
  loading.value = true
  try {
    const { data } = await request.get('/review/annotation-tasks')
    items.value = data.items || []
  } catch { items.value = [] }
  finally { loading.value = false }
}

function openDetail(row) {
  currentItem.value = row
  detailVisible.value = true
}

function openReject(row) {
  currentItem.value = row
  selectedRejectReasons.value = []
  rejectVisible.value = true
}

async function onVerdict(row, verdict) {
  try {
    await request.post(`/review/annotations/${row.annotation_id}/verdict`, {
      verdict,
      reject_reasons: []
    })
    row.review_status = verdict
    ElMessage.success(verdict === 'approved' ? '已通过' : '已驳回')
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '操作失败') }
}

async function submitReject() {
  if (selectedRejectReasons.value.length === 0) { ElMessage.warning('请至少选择一个驳回原因'); return }
  try {
    await request.post(`/review/annotations/${currentItem.value.annotation_id}/verdict`, {
      verdict: 'rejected',
      reject_reasons: selectedRejectReasons.value.map(code => ({ code, label: rejectOptions.find(t => t.code === code)?.label }))
    })
    currentItem.value.review_status = 'rejected'
    rejectVisible.value = false
    ElMessage.success('已驳回')
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '操作失败') }
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
.detail-body{display:flex;gap:20px}
.preview-area{flex:1;min-height:400px;background:#f1f5f9;border-radius:12px;overflow:hidden}
.bbox-list{width:300px;overflow-y:auto;max-height:500px}
.bbox-list h4{margin-bottom:12px;font-size:14px}
.bbox-card{background:#f8fafc;border-radius:10px;padding:10px;margin-bottom:8px;border:1px solid #e2e8f0}
.bbox-header{display:flex;justify-content:space-between;margin-bottom:4px}
.bbox-cat{font-weight:700;color:#2563eb;font-size:13px}
.bbox-depth{color:#475569;font-size:13px}
.bbox-meta{font-size:12px;color:#64748b;margin-bottom:4px}
.bbox-tags{display:flex;gap:6px;flex-wrap:wrap}
.reject-list{display:flex;flex-direction:column;gap:10px}
.reject-item{font-size:14px;padding:8px 0;border-bottom:1px solid #f1f5f9}
</style>