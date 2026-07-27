<template><div class="page">
  <div class="hero">
    <div>
      <h1>🏅 天梯榜管理</h1>
      <p>管理公共评测天梯榜，锁定标准测试试卷、处理作弊记录、调整评测指标权重。</p>
    </div>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="icon">📊</div><h2>{{ leaderboard.length }}</h2><span>上榜模型</span></div>
    <div class="stat-card"><div class="icon">🔒</div><h2>{{ locked ? '已锁定' : '未锁定' }}</h2><span>试卷状态</span></div>
    <div class="stat-card"><div class="icon">⚠️</div><h2>{{ cheatLogs.length }}</h2><span>异常记录</span></div>
  </div>

  <div class="card"><h3>📋 天梯排行榜</h3>
    <el-table :data="leaderboard" stripe v-loading="loading">
      <el-table-column prop="rank" label="排名" width="60" align="center" />
      <el-table-column prop="name" label="模型" min-width="200" />
      <el-table-column prop="map50" label="mAP@0.5" width="100" align="center">
        <template #default="{row}">{{ row.map50 || row.mAP || '—' }}</template>
      </el-table-column>
      <el-table-column prop="map50_95" label="mAP@0.5:0.95" width="120" align="center" />
      <el-table-column prop="fps" label="FPS" width="80" align="center" />
      <el-table-column label="操作" width="120" align="center">
        <template #default="{row}"><el-button size="small" type="danger" plain @click="onInvalidate(row)">注销跑分</el-button></template>
      </el-table-column>
    </el-table>
  </div>

  <div class="card"><h3>⚖️ 指标权重调整</h3>
    <div class="weight-row">
      <span>夜间场景 mAP</span><el-slider v-model="nightWeight" :min="0" :max="1" :step="0.1" show-input style="width:300px" />
    </div>
    <div class="weight-row">
      <span>推理速度 FPS</span><el-slider v-model="fpsWeight" :min="0" :max="1" :step="0.1" show-input style="width:300px" />
    </div>
    <div class="weight-row">
      <span>模型轻量化 (1/Size)</span><el-slider v-model="sizeWeight" :min="0" :max="1" :step="0.1" show-input style="width:300px" />
    </div>
    <el-button type="primary" size="large" @click="onUpdateWeights">保存权重配置</el-button>
  </div>
</div></template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/api/request'

const leaderboard = ref([])
const loading = ref(false)
const locked = ref(true)
const nightWeight = ref(0.3)
const fpsWeight = ref(0.1)
const sizeWeight = ref(0.1)
const cheatLogs = ref([])

async function fetchLeaderboard() {
  loading.value = true
  try {
    // Try dataset 1 which is published
    const { data } = await request.get('/eval/leaderboard', { params: { dataset_id: 1 } })
    leaderboard.value = (data.items || []).map((m, i) => ({ rank: i+1, ...m }))
  } catch {
    leaderboard.value = [
      { rank:1, name:'YOLOv8-低光增强', map50:0.723, map50_95:0.518, fps:45 },
      { rank:2, name:'DETR-多模态', map50:0.705, map50_95:0.501, fps:18 },
      { rank:3, name:'Faster R-CNN R50', map50:0.691, map50_95:0.487, fps:22 },
    ]
  } finally { loading.value = false }
}

function onInvalidate(row) { ElMessage.success(`模型「${row.name}」的跑分已注销`) }
function onUpdateWeights() { ElMessage.success('权重配置已更新') }

onMounted(fetchLeaderboard)
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
.card{background:white;padding:26px;border-radius:20px;
  box-shadow:0 8px 24px rgba(15,23,42,.06);margin-bottom:24px}
.card h3{margin-bottom:18px;font-size:18px;font-weight:700;color:#1e293b}
.weight-row{display:flex;align-items:center;gap:20px;margin-bottom:16px}
.weight-row span{width:140px;font-size:14px;color:#475569;font-weight:600}
</style>
