<template>
<div class="page">
  <div class="top-bar">
    <el-button text @click="$router.back()">← 返回</el-button>
  </div>
  <div v-if="!sample" class="loading">{{ loadError || '加载中...' }}</div>
  <div v-else>
    <div class="hero">
      <h1>样本 #{{ sample.group_no ?? sample.sample_id }}</h1>
      <p>{{ sceneLabel(sample.scene) }} · {{ sample.time_of_day === 'night' ? '夜间' : (sample.time_of_day === 'day' ? '白天' : '-') }} · {{ sample.weather }} · {{ sample.batch_id }}</p>
    </div>
    <div class="modality-grid" :class="'cols-' + Math.min(sample.images.length, 4)">
      <div v-for="img in sample.images" :key="img.resource_id" class="modality-card"
        @click="$router.push({name:'DataDetail', params:{id:img.resource_id}})" style="cursor:pointer;">
        <div class="mod-header">
          <span class="mod-badge" :class="img.modality">{{ modLabel(img.modality) }}</span>
          <el-tag v-if="img.annotation_status==='annotated'" type="success" size="small" round>已标注</el-tag>
          <el-tag v-else type="warning" size="small" round>未标注</el-tag>
        </div>
        <div class="mod-image">
          <template v-if="img.modality === 'lidar'">
            <div class="lidar-placeholder">📐 激光雷达点云</div>
          </template>
          <template v-else>
            <img :src="'/api/images/' + img.resource_id" @error="e => e.target.style.display='none'" />
          </template>
        </div>
        <div class="mod-info">
          <p>资源 ID: {{ img.resource_id }}</p>
        </div>
      </div>
    </div>
  </div>
</div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getDataList } from '@/api/data'

const route = useRoute()
const sample = ref(null)
const loadError = ref('')

function modLabel(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
function sceneLabel(s) {
  const map = { daytime: '白天', night: '夜间', rainy: '雨天', foggy: '雾天' }
  return map[s] || s
}

function parseSampleId(raw) {
  const id = decodeURIComponent(String(raw || ''))
  if (id.includes('::')) {
    const idx = id.lastIndexOf('::')
    return { batch_id: id.slice(0, idx), sample_group: id.slice(idx + 2) }
  }
  return { batch_id: null, sample_group: id }
}

onMounted(async () => {
  try {
    const { batch_id, sample_group } = parseSampleId(route.params.id)
    if (!sample_group && sample_group !== 0) {
      loadError.value = '无效的样本 ID'
      return
    }
    const params = {
      page: 1,
      size: 100,
      sample_group: Number(sample_group),
    }
    if (batch_id) params.batch_id = batch_id

    const { data } = await getDataList(params)
    const items = data?.items || []
    if (!items.length) {
      loadError.value = '未找到该样本（可能尚未导入或 ID 已失效）'
      return
    }

    const seenSensor = new Set()
    const images = []
    let meta = {}
    items.forEach(item => {
      meta = item.meta_info || meta
      const sensorKey = item.meta_info?.sensor || `${item.modality}:${item.name}`
      if (seenSensor.has(sensorKey)) return
      seenSensor.add(sensorKey)
      images.push({
        resource_id: item.resource_id,
        modality: item.modality,
        name: item.name,
        thumbnail: `/api/images/${item.resource_id}`,
        annotation_status: item.annotation_status,
      })
    })

    sample.value = {
      sample_id: route.params.id,
      group_no: meta.sample_group,
      scene: meta.scene || '-',
      weather: meta.weather,
      time_of_day: meta.time_of_day,
      batch_id: meta.batch_id || batch_id || '-',
      images,
      modality_count: images.length,
    }
  } catch {
    loadError.value = '加载失败'
  }
})
</script>

<style scoped>
.page{ padding:28px; max-width:1450px; margin:auto; min-height:100vh; }
.top-bar{ margin-bottom:16px; }
.hero{ padding:32px 40px; margin-bottom:24px; border-radius:18px;
  background: linear-gradient(135deg, #0f172a, #1e3a8a); color:white;
  box-shadow: 0 10px 30px rgba(30,64,175,.18); }
.hero h1{ font-size:28px; margin-bottom:6px; }
.hero p{ opacity:.85; }
.loading{ text-align:center; padding:60px; color:#9ca3af; }
.modality-grid{ display:grid; gap:20px; }
.modality-grid.cols-1{ grid-template-columns:1fr; max-width:700px; }
.modality-grid.cols-2{ grid-template-columns:1fr 1fr; }
.modality-grid.cols-3{ grid-template-columns:1fr 1fr 1fr; }
.modality-grid.cols-4{ grid-template-columns:1fr 1fr 1fr 1fr; }
.modality-card{ background:#fff; border-radius:14px; overflow:hidden;
  border:1px solid #e2e8f0; box-shadow:0 4px 14px rgba(15,23,42,.04); }
.mod-header{ display:flex; align-items:center; justify-content:space-between;
  padding:12px 16px; border-bottom:1px solid #f1f5f9; }
.mod-badge{ padding:4px 10px; border-radius:12px; font-size:12px; color:#fff; }
.mod-badge.visible{ background:#3b82f6; }
.mod-badge.infrared{ background:#ef4444; }
.mod-badge.mmwave{ background:#7c3aed; }
.mod-badge.lidar{ background:#0891b2; }
.mod-image{ height:320px; background:#f8fafc; display:flex; align-items:center; justify-content:center; }
.mod-image img{ max-width:100%; max-height:100%; object-fit:contain; }
.lidar-placeholder{ font-size:18px; color:#64748b; }
.mod-info{ padding:10px 16px; color:#64748b; font-size:13px; }
</style>
