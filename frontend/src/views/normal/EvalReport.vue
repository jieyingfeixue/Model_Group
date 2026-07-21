<template>
  <div class="page" v-loading="loading">
    <h2>评测报告 #{{ taskId }}</h2>
    <p v-if="status" class="status">状态：<el-tag>{{ status }}</el-tag></p>

    <div class="metrics-row">
      <div class="metric-card">
        <span class="val">{{ fmt(overall.map50 ?? overall['mAP@0.5'] ?? overall.mAP) }}</span>
        <span class="lbl">mAP@0.5</span>
      </div>
      <div class="metric-card">
        <span class="val">{{ fmt(overall.map ?? overall['mAP@0.5:0.95'] ?? overall.mAP50_95) }}</span>
        <span class="lbl">mAP@0.5:0.95</span>
      </div>
      <div class="metric-card">
        <span class="val">{{ fmt(overall.precision ?? overall.Precision) }}</span>
        <span class="lbl">Precision</span>
      </div>
      <div class="metric-card">
        <span class="val">{{ fmt(overall.recall ?? overall.Recall) }}</span>
        <span class="lbl">Recall</span>
      </div>
    </div>

    <div class="card">
      <h3>原始指标 JSON</h3>
      <pre class="raw">{{ JSON.stringify(metrics || {}, null, 2) }}</pre>
    </div>

    <div class="card" v-if="prData.length">
      <h3>PR 曲线</h3>
      <PrCurve :data="prData" />
    </div>

    <div class="card" v-if="matrix.length">
      <h3>混淆矩阵</h3>
      <ConfusionMatrix :data="matrix" :labels="labels" />
    </div>

    <div class="card" v-if="perClassValues.length">
      <h3>分类别 AP</h3>
      <BarChart title="各类别 AP" :labels="labels" :values="perClassValues" />
    </div>

    <div class="card" v-if="errors.length">
      <h3>错误样本</h3>
      <el-tabs>
        <el-tab-pane label="样本">
          <p v-for="(e, i) in errors" :key="i">{{ summarizeError(e) }}</p>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import PrCurve from '@/components/charts/PrCurve.vue'
import ConfusionMatrix from '@/components/charts/ConfusionMatrix.vue'
import BarChart from '@/components/charts/BarChart.vue'
import {
  getEvalStatus,
  getEvalMetrics,
  getPRCurve,
  getConfusionMatrix,
  getErrorSamples,
} from '@/api/eval'

const route = useRoute()
const taskId = computed(() => Number(route.params.taskId))
const loading = ref(false)
const status = ref('')
const metrics = ref(null)
const prData = ref([])
const matrix = ref([])
const labels = ref([])
const perClassValues = ref([])
const errors = ref([])

const overall = computed(() => metrics.value?.overall_metrics || {})

function fmt(v) {
  if (v == null || Number.isNaN(Number(v))) return '-'
  return Number(v).toFixed(3)
}

function summarizeError(e) {
  if (typeof e === 'string') return e
  return JSON.stringify(e)
}

async function load() {
  if (!taskId.value) return
  loading.value = true
  try {
    const st = await getEvalStatus(taskId.value)
    status.value = st.data.status
    if (st.data.status === 'completed') {
      const m = await getEvalMetrics(taskId.value)
      metrics.value = m.data
      const pcs = m.data.per_class_metrics || []
      if (pcs.length) {
        labels.value = pcs.map((c, i) => c.class_name || c.name || `class_${c.class_id ?? i}`)
        perClassValues.value = pcs.map((c) => Number(c.ap ?? c.AP ?? c.map ?? 0))
      }
    }
    try {
      const pr = await getPRCurve(taskId.value, 0)
      const curves = pr.data?.curves || pr.data?.data || pr.data
      if (Array.isArray(curves)) {
        prData.value = curves.map((c, i) => ({
          name: c.name || labels.value[i] || `class_${i}`,
          points: c.points || c,
        }))
      }
    } catch { /* optional */ }
    try {
      const cm = await getConfusionMatrix(taskId.value)
      matrix.value = cm.data?.matrix || cm.data || []
      if (cm.data?.labels?.length) labels.value = cm.data.labels
    } catch { /* optional */ }
    try {
      const er = await getErrorSamples(taskId.value, { page: 1, size: 20 })
      errors.value = er.data?.items || er.data?.errors || (Array.isArray(er.data) ? er.data : [])
    } catch { /* optional */ }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载评测报告失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page{padding:24px;max-width:1200px;margin:0 auto}
.status{margin-bottom:16px;color:#64748b}
.metrics-row{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}
.metric-card{background:#fff;border-radius:8px;padding:20px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.val{display:block;font-size:28px;font-weight:700;color:#1a1a2e}
.lbl{font-size:13px;color:#6b7280}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
h3{margin-bottom:12px}
.raw{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;font-size:12px;overflow:auto;max-height:360px}
</style>
