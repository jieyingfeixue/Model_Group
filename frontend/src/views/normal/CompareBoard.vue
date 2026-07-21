<template>
  <div class="page">
    <h2>模型对比</h2>
    <div class="card">
      <el-form inline>
        <el-form-item label="模型 ID（逗号分隔）">
          <el-input v-model="modelIdsStr" placeholder="1,2,3" style="width:220px" />
        </el-form-item>
        <el-form-item label="数据集 ID">
          <el-input-number v-model="datasetId" :min="1" />
        </el-form-item>
        <el-button type="primary" :loading="loading" @click="onCompare">对比</el-button>
        <el-button @click="loadLeaderboard">排行榜</el-button>
      </el-form>
    </div>

    <div class="card" v-if="models.length">
      <h3>雷达图</h3>
      <RadarChart :indicators="indicators" :series="radarSeries"/>
    </div>
    <div class="card" v-if="models.length">
      <h3>指标对比</h3>
      <BarChart title="mAP@0.5 对比" :labels="models.map(m=>m.name)" :values="models.map(m=>m.map50)"/>
    </div>
    <div class="card">
      <h3>排行榜</h3>
      <el-table :data="leaderboard" v-loading="loading">
        <el-table-column prop="rank" label="排名" width="60"/>
        <el-table-column prop="name" label="模型"/>
        <el-table-column prop="map50" label="mAP@0.5"/>
        <el-table-column prop="map50_95" label="mAP@0.5:0.95"/>
      </el-table>
      <el-empty v-if="!loading && !leaderboard.length" description="选择数据集后加载排行榜" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import RadarChart from '@/components/charts/RadarChart.vue'
import BarChart from '@/components/charts/BarChart.vue'
import { compareModels, getLeaderboard } from '@/api/eval'

const modelIdsStr = ref('')
const datasetId = ref(1)
const loading = ref(false)
const models = ref([])
const leaderboard = ref([])

const indicators = [
  { name: 'mAP@0.5', max: 1 },
  { name: 'mAP@0.5:0.95', max: 1 },
  { name: 'Precision', max: 1 },
  { name: 'Recall', max: 1 },
]

const radarSeries = computed(() =>
  models.value.map((m) => ({
    name: m.name,
    values: [m.map50, m.map50_95, m.prec, m.rec],
  })),
)

function pickMetric(obj, ...keys) {
  for (const k of keys) {
    if (obj?.[k] != null) return Number(obj[k])
  }
  return 0
}

function normalizeRow(row, i) {
  const metrics = row.overall_metrics || row.metrics || row
  return {
    rank: row.rank ?? i + 1,
    name: row.name || row.model_name || `model_${row.model_id || i + 1}`,
    map50: pickMetric(metrics, 'map50', 'mAP@0.5', 'mAP', 'map'),
    map50_95: pickMetric(metrics, 'map50_95', 'mAP@0.5:0.95', 'mAP50_95'),
    prec: pickMetric(metrics, 'precision', 'Precision'),
    rec: pickMetric(metrics, 'recall', 'Recall'),
  }
}

async function onCompare() {
  const ids = modelIdsStr.value.split(',').map((s) => Number(s.trim())).filter(Boolean)
  if (!ids.length || !datasetId.value) {
    ElMessage.warning('请填写模型 ID 与数据集 ID')
    return
  }
  loading.value = true
  try {
    const { data } = await compareModels({ model_ids: ids, dataset_id: datasetId.value })
    const rows = data.results || data.items || data.models || (Array.isArray(data) ? data : [])
    models.value = rows.map(normalizeRow)
    if (!models.value.length) ElMessage.info('对比结果为空（可能尚无已完成评测）')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '对比失败')
  } finally {
    loading.value = false
  }
}

async function loadLeaderboard() {
  if (!datasetId.value) {
    ElMessage.warning('请填写数据集 ID')
    return
  }
  loading.value = true
  try {
    const { data } = await getLeaderboard({ dataset_id: datasetId.value })
    const rows = data.items || data.leaderboard || (Array.isArray(data) ? data : [])
    leaderboard.value = rows.map(normalizeRow)
    if (!models.value.length) models.value = leaderboard.value.slice(0, 5)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '排行榜加载失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.page{padding:24px;max-width:1200px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
h3{margin-bottom:12px}
</style>
