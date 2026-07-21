<template>
  <div class="page">
    <div class="hero">
      <div>
        <h1>模型评测</h1>
        <p>基于测试数据集评估模型性能，对接后端评测任务与指标接口。</p>
      </div>
    </div>

    <div class="stats">
      <div class="stat-card">
        <div class="icon">🤖</div>
        <h2>{{ models.length }}</h2>
        <span>可评测模型</span>
      </div>
      <div class="stat-card">
        <div class="icon">📂</div>
        <h2>{{ form.dataset_id || '-' }}</h2>
        <span>当前数据集 ID</span>
      </div>
      <div class="stat-card">
        <div class="icon">📈</div>
        <h2>{{ progressLabel }}</h2>
        <span>评测进度</span>
      </div>
    </div>

    <div class="content-card">
      <div class="card">
        <h3>发起评测任务</h3>
        <el-form label-position="top" class="eval-form" v-loading="loadingModels">
          <el-form-item label="模型">
            <el-select v-model="form.model_id" style="width:100%" filterable>
              <el-option
                v-for="m in models"
                :key="m.model_id"
                :label="`${m.name} (#${m.model_id})`"
                :value="m.model_id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="测试数据集">
            <el-select v-model="form.dataset_id" style="width:100%" filterable allow-create>
              <el-option
                v-for="d in datasets"
                :key="d.dataset_id"
                :label="`${d.name} (#${d.dataset_id})`"
                :value="d.dataset_id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="置信度阈值（前端展示，后端按 metric_config）">
            <el-slider v-model="form.conf" :min="0" :max="1" :step="0.05" show-input />
          </el-form-item>
          <el-form-item label="IoU 阈值">
            <el-slider v-model="form.iou" :min="0.1" :max="0.95" :step="0.05" show-input />
          </el-form-item>
          <el-button type="primary" size="large" :loading="submitting" @click="onSubmit">
            开始评测
          </el-button>
        </el-form>
      </div>

      <div class="card" v-if="task">
        <h3>评测进度</h3>
        <el-progress :percentage="progress" :status="task.status === 'completed' ? 'success' : undefined" />
        <p style="margin-top:12px">
          Task #{{ task.task_id }} —
          <el-tag>{{ task.status }}</el-tag>
        </p>
        <el-button size="small" @click="refresh">刷新</el-button>
      </div>

      <div class="success-card" v-if="completed">
        <h3>评测完成</h3>
        <div v-if="metrics" class="metrics">
          <pre>{{ JSON.stringify(metrics.overall_metrics || metrics, null, 2) }}</pre>
        </div>
        <div class="action-bar">
          <el-button type="primary" size="large" @click="goReport">查看评测报告</el-button>
          <el-button size="large" @click="$router.push('/compare')">模型对比</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMyModels } from '@/api/model'
import { getMyDatasets } from '@/api/dataset'
import { submitEval, getEvalStatus, getEvalMetrics } from '@/api/eval'

const route = useRoute()
const router = useRouter()
const models = ref([])
const datasets = ref([])
const loadingModels = ref(false)
const submitting = ref(false)
const task = ref(null)
const metrics = ref(null)
let pollTimer = null

const form = reactive({
  model_id: null,
  dataset_id: 1,
  conf: 0.25,
  iou: 0.5,
})

const completed = computed(() => task.value?.status === 'completed')
const progress = computed(() => {
  const s = task.value?.status
  if (!s) return 0
  if (s === 'pending' || s === 'queued') return 15
  if (s === 'running') return 55
  if (s === 'completed') return 100
  if (s === 'failed') return 100
  return 30
})
const progressLabel = computed(() => (completed.value ? '100%' : `${progress.value}%`))

async function loadModels() {
  loadingModels.value = true
  try {
    const [{ data: modelData }, dsRes] = await Promise.all([
      getMyModels({ page: 1, size: 100 }),
      getMyDatasets({ page: 1, size: 100 }).catch(() => ({ data: { items: [] } })),
    ])
    models.value = modelData.items || []
    datasets.value = dsRes.data?.items || []
    const qid = Number(route.query.model_id)
    if (qid) form.model_id = qid
    else if (models.value.length) form.model_id = models.value[0].model_id
    const qds = Number(route.query.dataset_id)
    if (qds) form.dataset_id = qds
    else if (datasets.value.length) form.dataset_id = datasets.value[0].dataset_id
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载模型失败')
  } finally {
    loadingModels.value = false
  }
}

async function refresh() {
  if (!task.value?.task_id) return
  try {
    const { data } = await getEvalStatus(task.value.task_id)
    task.value = data
    if (data.status === 'completed') {
      clearInterval(pollTimer)
      pollTimer = null
      try {
        const m = await getEvalMetrics(data.task_id)
        metrics.value = m.data
      } catch {
        metrics.value = null
      }
    }
    if (data.status === 'failed') {
      clearInterval(pollTimer)
      pollTimer = null
      ElMessage.error('评测失败')
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '刷新失败')
  }
}

async function onSubmit() {
  if (!form.model_id) {
    ElMessage.warning('请选择模型')
    return
  }
  submitting.value = true
  metrics.value = null
  try {
    const { data } = await submitEval({
      model_id: form.model_id,
      dataset_id: form.dataset_id,
      metric_config: {
        iou_thresholds: [form.iou, 0.75],
        conf_threshold: form.conf,
        max_detections: 100,
      },
    })
    task.value = data
    ElMessage.success(`评测任务已提交 #${data.task_id}`)
    clearInterval(pollTimer)
    pollTimer = setInterval(refresh, 2500)
    await refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

function goReport() {
  if (task.value?.task_id) router.push(`/eval/${task.value.task_id}`)
}

onMounted(loadModels)
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.page{padding:28px;max-width:1450px;margin:auto;background:#f8fafc;min-height:100vh}
.hero{
  padding:45px 50px;margin-bottom:28px;border-radius:18px;color:white;
  background:linear-gradient(135deg,#0f172a,#1e3a8a);box-shadow:0 10px 30px rgba(30,64,175,.18)
}
.hero h1{font-size:34px;font-weight:700;margin-bottom:12px}
.hero p{max-width:700px;line-height:1.8;opacity:.9}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-bottom:30px}
.stat-card{
  background:white;border-radius:18px;padding:28px;text-align:center;
  box-shadow:0 8px 24px rgba(15,23,42,.05)
}
.icon{font-size:30px;margin-bottom:12px}
.stat-card h2{font-size:34px;color:#2563eb}
.stat-card span{color:#64748b}
.content-card{background:white;border-radius:22px;padding:28px;box-shadow:0 8px 24px rgba(15,23,42,.05)}
.card{padding:24px;border:1px solid #e5e7eb;border-radius:18px;margin-bottom:24px}
.card h3{margin-bottom:20px;font-size:18px;font-weight:700}
.eval-form{max-width:650px}
.success-card{padding:28px;background:#f0fdf4;border:1px solid #86efac;border-radius:18px}
.metrics{margin:16px 0;background:#0f172a;color:#e2e8f0;border-radius:12px;padding:16px;overflow:auto;max-height:320px}
.metrics pre{margin:0;font-size:12px}
.action-bar{display:flex;justify-content:flex-end;gap:16px;margin-top:20px}
</style>
