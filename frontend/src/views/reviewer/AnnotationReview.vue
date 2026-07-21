<template>
  <div class="page">
    <h2>标注审核</h2>
    <div class="card" v-loading="loading">
      <h3>待审核任务</h3>
      <el-table :data="tasks">
        <el-table-column prop="name" label="任务" />
        <el-table-column prop="task_id" label="ID" width="80" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <el-button size="small" @click="onClaim(row)">认领</el-button>
            <el-button size="small" type="primary" @click="onStartReview(row)">开始审核</el-button>
            <el-button size="small" @click="onQuality(row)">质量检查</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card" v-if="currentTask">
      <h3>抽检配置 — 任务 #{{ currentTask.task_id }}</h3>
      <p>抽检比例:
        <el-slider v-model="sampleRatioPct" :min="10" :max="100" show-input style="width:300px;display:inline-flex;margin-left:12px" />
      </p>
      <el-button type="primary" :loading="sampling" @click="onStartSampling">开始抽检</el-button>
      <el-button @click="onFinishReview">完成审核（finalize）</el-button>
    </div>

    <div class="card" v-if="sampleItems.length">
      <h3>抽检样本</h3>
      <el-table :data="sampleItems">
        <el-table-column prop="annotation_id" label="标注 ID" width="100" />
        <el-table-column prop="resource_id" label="资源 ID" width="100" />
        <el-table-column prop="review_status" label="状态" width="120" />
        <el-table-column label="裁决" width="220">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="onAnnotVerdict(row,'approved')">通过</el-button>
            <el-button size="small" type="danger" @click="onAnnotVerdict(row,'rejected')">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
      <pre v-if="summary" class="raw">{{ JSON.stringify(summary, null, 2) }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getPendingAnnotationTasks,
  claimAnnotationReview,
  setupSampling,
  reviewAnnotation,
  getSamplingResult,
  finalizeReview,
  runQualityCheck,
} from '@/api/review'

const tasks = ref([])
const loading = ref(false)
const currentTask = ref(null)
const sampleRatioPct = ref(20)
const sampling = ref(false)
const sampleItems = ref([])
const summary = ref(null)

async function fetchList() {
  loading.value = true
  try {
    const { data } = await getPendingAnnotationTasks({ page: 1, size: 50 })
    tasks.value = (data.items || []).map((t) => ({
      ...t,
      name: t.name || `任务 #${t.task_id}`,
    }))
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败（需 reviewer/admin）')
  } finally {
    loading.value = false
  }
}

async function onClaim(row) {
  try {
    await claimAnnotationReview(row.task_id)
    ElMessage.success('已认领')
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '认领失败')
  }
}

function onStartReview(row) {
  currentTask.value = row
  sampleItems.value = []
  summary.value = null
}

async function onStartSampling() {
  if (!currentTask.value) return
  sampling.value = true
  try {
    const { data } = await setupSampling(currentTask.value.task_id, {
      ratio: sampleRatioPct.value / 100,
      mode: 'random',
    })
    sampleItems.value = data.items || data.samples || data.annotation_ids?.map((id) => ({ annotation_id: id })) || []
    const sum = await getSamplingResult(currentTask.value.task_id)
    summary.value = sum.data
    ElMessage.success('抽检样本已生成')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '抽检失败')
  } finally {
    sampling.value = false
  }
}

async function onAnnotVerdict(row, action) {
  const id = row.annotation_id
  if (!id) {
    ElMessage.warning('缺少 annotation_id')
    return
  }
  try {
    let reject_codes
    if (action === 'rejected') {
      const { value } = await ElMessageBox.prompt('驳回码（逗号分隔，如 T01,T04）', '驳回')
      reject_codes = value
    }
    await reviewAnnotation(id, { action, reject_codes })
    ElMessage.success(action === 'approved' ? '已通过' : '已驳回')
    row.review_status = action
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '裁决失败')
  }
}

async function onFinishReview() {
  if (!currentTask.value) return
  try {
    await finalizeReview(currentTask.value.task_id, { action: 'approve' })
    ElMessage.success('审核已完成')
    currentTask.value = null
    sampleItems.value = []
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || 'finalize 失败')
  }
}

async function onQuality(row) {
  try {
    const { data } = await runQualityCheck(row.task_id)
    ElMessageBox.alert(`<pre style="white-space:pre-wrap">${JSON.stringify(data, null, 2)}</pre>`, '质量检查', {
      dangerouslyUseHTMLString: true,
      customClass: 'quality-box',
    })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '质量检查失败')
  }
}

onMounted(fetchList)
</script>

<style scoped>
.page{padding:24px;max-width:1200px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
h3{margin-bottom:12px}
.raw{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;font-size:12px;overflow:auto;max-height:280px}
</style>
