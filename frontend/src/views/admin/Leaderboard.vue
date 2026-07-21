<template>
  <div class="page">
    <h2>天梯榜管理</h2>
    <div class="card">
      <h3>公开排行榜</h3>
      <el-form inline>
        <el-form-item label="数据集 ID">
          <el-input-number v-model="datasetId" :min="1" />
        </el-form-item>
        <el-button type="primary" :loading="loading" @click="loadBoard">刷新排行榜</el-button>
        <el-button type="warning" @click="onLock">锁定试卷</el-button>
      </el-form>
      <el-table :data="rows" style="margin-top:12px">
        <el-table-column prop="rank" label="排名" width="70" />
        <el-table-column prop="result_id" label="Result ID" width="100" />
        <el-table-column prop="model_id" label="模型 ID" width="90" />
        <el-table-column prop="name" label="模型" />
        <el-table-column prop="map50" label="mAP@0.5" width="110" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" type="danger" @click="onInvalidate(row)" :disabled="!row.result_id">下架</el-button>
            <el-button size="small" type="success" @click="onPublish(row)" :disabled="!row.result_id">发布</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card">
      <h3>指标权重</h3>
      <p>夜间场景 mAP 权重: <el-slider v-model="weights.night_map_weight" :min="0" :max="1" :step="0.05" show-input style="width:360px;display:inline-flex;margin-left:12px" /></p>
      <p>FPS 权重: <el-slider v-model="weights.fps_weight" :min="0" :max="1" :step="0.05" show-input style="width:360px;display:inline-flex;margin-left:12px" /></p>
      <p>mAP@0.5 权重: <el-slider v-model="weights.map50_weight" :min="0" :max="1" :step="0.05" show-input style="width:360px;display:inline-flex;margin-left:12px" /></p>
      <p>mAP@0.5:0.95 权重: <el-slider v-model="weights.map5095_weight" :min="0" :max="1" :step="0.05" show-input style="width:360px;display:inline-flex;margin-left:12px" /></p>
      <el-button type="primary" @click="onSaveWeights">保存权重</el-button>
      <el-button @click="loadWeights">重新加载</el-button>
      <p class="hint">类别：{{ (weights.categories || []).join(', ') }}</p>
    </div>

    <div class="card">
      <h3>按 Result ID 操作</h3>
      <el-input-number v-model="manualResultId" :min="1" />
      <el-button type="danger" style="margin-left:12px" @click="onInvalidate({ result_id: manualResultId })">注销跑分</el-button>
      <el-button type="success" style="margin-left:8px" @click="onPublish({ result_id: manualResultId })">纳入天梯</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getLeaderboard } from '@/api/eval'
import {
  invalidateResult,
  publishEvalResult,
  lockTestset,
  getEvalWeights,
  updateWeights,
} from '@/api/admin'

const datasetId = ref(1)
const manualResultId = ref(1)
const loading = ref(false)
const rows = ref([])
const weights = reactive({
  night_map_weight: 0.3,
  fps_weight: 0.1,
  map50_weight: 0.4,
  map5095_weight: 0.2,
  categories: [],
})

function pick(obj, ...keys) {
  for (const k of keys) if (obj?.[k] != null) return obj[k]
  return null
}

async function loadBoard() {
  loading.value = true
  try {
    const { data } = await getLeaderboard({ dataset_id: datasetId.value })
    const list = data.items || data.leaderboard || (Array.isArray(data) ? data : [])
    rows.value = list.map((r, i) => {
      const m = r.overall_metrics || r.metrics || r
      return {
        rank: r.rank ?? i + 1,
        result_id: r.result_id,
        model_id: r.model_id,
        name: r.name || r.model_name || `model_${r.model_id || i + 1}`,
        map50: pick(m, 'map50', 'mAP@0.5', 'mAP', 'map') ?? '-',
      }
    })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadWeights() {
  try {
    const { data } = await getEvalWeights()
    Object.assign(weights, data)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '权重加载失败')
  }
}

async function onSaveWeights() {
  try {
    const { data } = await updateWeights({ ...weights })
    Object.assign(weights, data)
    ElMessage.success('权重已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

async function onLock() {
  try {
    const { data } = await lockTestset(datasetId.value)
    ElMessage.success(data.message || '已锁定')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '锁定失败')
  }
}

async function onInvalidate(row) {
  if (!row?.result_id) return
  try {
    await invalidateResult(row.result_id)
    ElMessage.success('已下架')
    await loadBoard()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '下架失败')
  }
}

async function onPublish(row) {
  if (!row?.result_id) return
  try {
    await publishEvalResult(row.result_id)
    ElMessage.success('已发布到天梯')
    await loadBoard()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发布失败')
  }
}

onMounted(() => {
  loadWeights()
})
</script>

<style scoped>
.page{padding:24px;max-width:1000px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
h3{margin-bottom:12px}
.hint{margin-top:12px;color:#94a3b8;font-size:13px}
</style>
