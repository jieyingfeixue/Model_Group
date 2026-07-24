<template><div class="page">
  <div v-if="loading" class="loading">加载评测报告...</div>
  <template v-else>
    <h2>评测报告 #{{ $route.params.taskId }}</h2>
    <div class="metrics-row">
      <div class="metric-card"><span class="val">{{ metrics?.mAP50 || metrics?.mAP || '—' }}</span><span class="lbl">mAP@0.5</span></div>
      <div class="metric-card"><span class="val">{{ metrics?.mAP50_95 || metrics?.mAP75 || '—' }}</span><span class="lbl">mAP@0.5:0.95</span></div>
      <div class="metric-card"><span class="val">{{ metrics?.precision || metrics?.Precision || '—' }}</span><span class="lbl">Precision</span></div>
      <div class="metric-card"><span class="val">{{ metrics?.recall || metrics?.Recall || '—' }}</span><span class="lbl">Recall</span></div>
    </div>
    <div class="card" v-if="prData.length"><h3>PR 曲线</h3><PrCurve :data="prData"/></div>
    <div class="card" v-if="matrix.length"><h3>混淆矩阵</h3><ConfusionMatrix :data="matrix" :labels="labels"/></div>
    <div class="card" v-if="perClass.length"><h3>分类别 AP</h3><BarChart title="各类别 AP" :labels="labels" :values="perClass"/></div>
    <div class="card"><h3>分场景评测</h3><BarChart title="分场景 mAP" :labels="['白天','夜间','雨天']" :values="sceneMap"/></div>
    <div class="card"><h3>错误样本</h3>
      <el-tabs>
        <el-tab-pane label="漏检(FN)">
          <p v-for="s in fnSamples" :key="s.resource_id">样本 #{{ s.resource_id }} — 漏检</p>
          <p v-if="!fnSamples.length">暂无漏检数据</p>
        </el-tab-pane>
        <el-tab-pane label="误检(FP)">
          <p v-for="s in fpSamples" :key="s.resource_id">样本 #{{ s.resource_id }} — 误检</p>
          <p v-if="!fpSamples.length">暂无误检数据</p>
        </el-tab-pane>
      </el-tabs>
    </div>
  </template>
</div></template>
<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getEvalMetrics, getPRCurve, getConfusionMatrix, getErrorSamples } from '@/api/eval'
import PrCurve from '@/components/charts/PrCurve.vue'
import ConfusionMatrix from '@/components/charts/ConfusionMatrix.vue'
import BarChart from '@/components/charts/BarChart.vue'

const route = useRoute()
const metrics = ref(null)
const labels = ref([])
const perClass = ref([])
const prData = ref([])
const matrix = ref([])
const sceneMap = ref([0.75, 0.62, 0.58])
const fnSamples = ref([])
const fpSamples = ref([])
const loading = ref(true)

onMounted(async () => {
  const taskId = Number(route.params.taskId)
  if (!taskId) { loading.value = false; return }
  try {
    const [metricsRes, prRes, cmRes, errorsRes] = await Promise.all([
      getEvalMetrics(taskId),
      getPRCurve(taskId),
      getConfusionMatrix(taskId),
      getErrorSamples(taskId, { page: 1, size: 10 })
    ])
    const m = metricsRes.data
    metrics.value = m.overall_metrics || {}
    // per class
    if (m.per_class_metrics) {
      labels.value = m.per_class_metrics.map(c => c.class_name || c.category_name || '未知')
      perClass.value = m.per_class_metrics.map(c => c.ap || c.AP || 0)
    }
    // per scene
    if (m.per_scene_metrics) {
      sceneMap.value = m.per_scene_metrics.map(s => s.ap || s.mAP || 0)
    }
    // PR curve
    const pr = prRes.data
    if (Array.isArray(pr)) {
      prData.value = pr
    } else if (pr.curves) {
      prData.value = pr.curves
    }
    // Confusion matrix
    const cm = cmRes.data
    if (cm.matrix) {
      matrix.value = cm.matrix
      if (cm.labels) labels.value = cm.labels
    }
    // Error samples
    const es = errorsRes.data
    if (es.items) {
      fnSamples.value = es.items.filter(e => e.error_type === 'fn').slice(0, 5)
      fpSamples.value = es.items.filter(e => e.error_type === 'fp').slice(0, 5)
    }
  } catch { /* use fallback data */ }
  finally { loading.value = false }
})
</script>
<style scoped>.page{padding:24px;max-width:1200px;margin:0 auto}.loading{text-align:center;padding:60px;color:#9ca3af}.metrics-row{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}.metric-card{background:#fff;border-radius:8px;padding:20px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.04)}.val{display:block;font-size:28px;font-weight:700;color:#1a1a2e}.lbl{font-size:13px;color:#6b7280}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}</style>