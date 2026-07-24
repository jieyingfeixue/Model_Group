<template><div class="page">
  <h2>模型对比</h2>
  <div class="card selector-card">
    <h3>选择模型与数据集</h3>
    <div class="selector-row">
      <el-select v-model="selectedModelIds" multiple placeholder="选择模型（可多选，最多5个）" style="flex:1" :multiple-limit="5">
        <el-option v-for="m in myModels" :key="m.model_id" :label="m.name" :value="m.model_id"/>
      </el-select>
      <el-select v-model="selectedDatasetId" placeholder="选择测试数据集" style="width:300px">
        <el-option v-for="d in datasets" :key="d.dataset_id" :label="d.name" :value="d.dataset_id"/>
      </el-select>
      <el-button type="primary" @click="onCompare" :disabled="selectedModelIds.length<2">开始对比</el-button>
    </div>
  </div>
  <div class="card" v-if="radarSeries.length"><h3>雷达图</h3><RadarChart :indicators="indicators" :series="radarSeries"/></div>
  <div class="card" v-if="barLabels.length"><h3>指标对比</h3><BarChart title="mAP@0.5 对比" :labels="barLabels" :values="barValues"/></div>
  <div class="card" v-if="leaderboard.length"><h3>排行榜</h3>
    <el-table :data="leaderboard">
      <el-table-column prop="rank" label="排名" width="60"/>
      <el-table-column prop="name" label="模型"/>
      <el-table-column prop="map50" label="mAP@0.5"><template #default="{row}">{{ row.map50 || row.mAP || row.score || '—' }}</template></el-table-column>
      <el-table-column prop="map50_95" label="mAP@0.5:0.95"><template #default="{row}">{{ row.map50_95 || row.mAP75 || '—' }}</template></el-table-column>
      <el-table-column prop="fps" label="FPS"><template #default="{row}">{{ row.fps || row.FPS || '—' }}</template></el-table-column>
    </el-table>
  </div>
</div></template>
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { getMyModels } from '@/api/model'
import { getDatasetList } from '@/api/dataset'
import { compareModels, getLeaderboard } from '@/api/eval'
import RadarChart from '@/components/charts/RadarChart.vue'
import BarChart from '@/components/charts/BarChart.vue'

const myModels = ref([])
const datasets = ref([])
const selectedModelIds = ref([])
const selectedDatasetId = ref(null)
const compareData = ref([])
const radarSeries = ref([])
const indicators = [
  {name:'mAP@0.5',max:1},{name:'mAP@0.5:0.95',max:1},
  {name:'Precision',max:1},{name:'Recall',max:1},{name:'FPS',max:60},{name:'轻量化(1/Size)',max:0.05}
]
const leaderboard = ref([])
const barLabels = ref([])
const barValues = ref([])

onMounted(async () => {
  try {
    const [mRes, dRes] = await Promise.all([
      getMyModels(),
      getDatasetList({ visibility: 'public' })
    ])
    myModels.value = mRes.data?.items || []
    datasets.value = dRes.data?.items || []
  } catch { /* ignore */ }
})

async function onCompare() {
  if (selectedModelIds.value.length < 2 || !selectedDatasetId.value) return
  try {
    const { data } = await compareModels({
      model_ids: selectedModelIds.value,
      dataset_id: selectedDatasetId.value
    })
    // Build radar data
    const models = data.models || data.items || []
    radarSeries.value = models.map(m => ({
      name: m.name || m.model_name,
      values: [
        m.mAP50 || m.mAP || 0, m.mAP50_95 || 0,
        m.precision || m.Precision || 0, m.recall || m.Recall || 0,
        m.fps || m.FPS || 0, m.size ? (1/m.size) : 0.01
      ]
    }))
    barLabels.value = models.map(m => m.name || m.model_name)
    barValues.value = models.map(m => m.mAP50 || m.mAP || 0)
    // Load leaderboard
    const lb = await getLeaderboard({ dataset_id: selectedDatasetId.value })
    leaderboard.value = (lb.data.items || []).map((m, i) => ({ rank: i+1, ...m }))
  } catch { /* ignore */ }
}

onMounted(() => {
  // auto-load if models and datasets available
  if (myModels.value.length >= 2 && datasets.value.length > 0) {
    selectedModelIds.value = myModels.value.slice(0, 3).map(m => m.model_id)
    selectedDatasetId.value = datasets.value[0]?.dataset_id
    onCompare()
  }
})
</script>
<style scoped>.page{padding:24px;max-width:1200px;margin:0 auto}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}.selector-card .selector-row{display:flex;gap:16px;align-items:center}</style>