<template>
<div class="page">
  <div class="top-bar">
    <el-button text @click="$router.back()">← 返回</el-button>
  </div>
  <div v-if="!sample" class="loading">{{ loadError || '加载中...' }}</div>
  <div v-else>
    <div class="hero">
      <h1>样本 #{{ sample.group_no }}</h1>
      <p>
        {{ sceneLabel(sample.scene) }} ·
        {{ sample.time_of_day === 'night' ? '夜间' : (sample.time_of_day === 'day' ? '白天' : '-') }} ·
        {{ sample.weather }} · {{ sample.batch_id }}
      </p>
    </div>
    <div class="modality-grid" :class="'cols-' + Math.min(sample.images.length, 5)">
      <div v-for="img in sample.images" :key="img.resource_id" class="modality-card"
        @click="openDetail(img.resource_id)" style="cursor:pointer;">
        <div class="mod-header">
          <span class="mod-badge" :class="img.modality">{{ cardTitle(img) }}</span>
          <el-tag v-if="img.annotation_status==='annotated'" type="success" size="small" round>已标注</el-tag>
          <el-tag v-else type="warning" size="small" round>未标注</el-tag>
        </div>
        <div class="mod-image">
          <img :src="'/api/images/' + img.resource_id" @error="e => e.target.style.opacity='0.2'" />
        </div>
        <div class="mod-info">
          <p>{{ cardSubtitle(img) }}</p>
        </div>
      </div>
    </div>
  </div>
</div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDataList } from '@/api/data'

const route = useRoute()
const router = useRouter()
const sample = ref(null)
const loadError = ref('')

function modLabel(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
function sceneLabel(s) {
  if (!s || s === '-') return '-'
  const map = { daytime: '白天', night: '夜间', rainy: '雨天', foggy: '雾天' }
  return map[s] || s
}

/** hikrobot DA8679037 → 设备1；DA8679038 → 设备2 */
function deviceLabel(img) {
  const sensor = String(img.sensor || img.name || '')
  if (sensor.includes('DA8679037')) return '设备1'
  if (sensor.includes('DA8679038')) return '设备2'
  return ''
}

function cardTitle(img) {
  const device = deviceLabel(img)
  if (device) return device
  return modLabel(img.modality)
}

function cardSubtitle(img) {
  const device = deviceLabel(img)
  if (device) return `${device} · 可见光`
  return modLabel(img.modality)
}

// 详情五图：设备1、设备2、红外、毫米波、激光雷达
const SENSOR_ORDER = [
  'hikrobot_camera__DA8679037__image_raw',
  'hikrobot_camera__DA8679038__image_raw',
  'usb_ir__image_raw',
  'mmwave_udp_radar',
  'at360__points',
]
const MOD_ORDER = ['visible', 'infrared', 'mmwave', 'lidar']

function sensorRank(item) {
  const sensor = item.meta_info?.sensor || ''
  const idx = SENSOR_ORDER.indexOf(sensor)
  if (idx >= 0) return idx
  const mod = MOD_ORDER.indexOf(item.modality)
  return mod < 0 ? 99 : 10 + mod
}

async function loadSample() {
  sample.value = null
  loadError.value = ''
  try {
    const groupRaw = route.params.id
    const batch_id = route.query.batch ? String(route.query.batch) : null
    const sample_group = Number(groupRaw)
    if (!Number.isFinite(sample_group)) {
      loadError.value = '无效的样本 ID'
      return
    }

    const params = {
      page: 1,
      size: 100,
      sample_group,
    }
    if (batch_id) params.batch_id = batch_id

    const { data } = await getDataList(params)
    let items = data?.items || []

    if (batch_id) {
      items = items.filter(it => (it.meta_info?.batch_id || '') === batch_id)
    }
    items = items.filter(it => Number(it.meta_info?.sample_group) === sample_group)

    if (!items.length) {
      loadError.value = `未找到样本 #${sample_group}`
      return
    }

    const seenSensor = new Set()
    const images = []
    let meta = items[0].meta_info || {}
    const sorted = [...items].sort((a, b) => sensorRank(a) - sensorRank(b))
    sorted.forEach(item => {
      meta = item.meta_info || meta
      const sensorKey = item.meta_info?.sensor || `${item.modality}:${item.name}`
      if (seenSensor.has(sensorKey)) return
      seenSensor.add(sensorKey)
      images.push({
        resource_id: item.resource_id,
        modality: item.modality,
        name: item.name,
        sensor: item.meta_info?.sensor || '',
        annotation_status: item.annotation_status,
      })
    })

    sample.value = {
      group_no: sample_group,
      scene: meta.scene || '-',
      weather: meta.weather,
      time_of_day: meta.time_of_day,
      batch_id: meta.batch_id || batch_id || '-',
      images,
    }
  } catch {
    loadError.value = '加载失败'
  }
}

watch(() => [route.params.id, route.query.batch], loadSample, { immediate: true })

function openDetail(resourceId) {
  const ids = (sample.value?.images || []).map(i => i.resource_id).join(',')
  router.push({
    name: 'DataDetail',
    params: { id: String(resourceId) },
    query: ids ? { ids } : {},
  })
}
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
.modality-grid.cols-5{ grid-template-columns:repeat(5, 1fr); }
@media (max-width: 1200px) {
  .modality-grid.cols-5{ grid-template-columns:repeat(3, 1fr); }
}
@media (max-width: 768px) {
  .modality-grid.cols-4,
  .modality-grid.cols-5{ grid-template-columns:1fr 1fr; }
}
.modality-card{ background:#fff; border-radius:14px; overflow:hidden;
  border:1px solid #e2e8f0; box-shadow:0 4px 14px rgba(15,23,42,.04); }
.mod-header{ display:flex; align-items:center; justify-content:space-between;
  padding:12px 16px; border-bottom:1px solid #f1f5f9; }
.mod-badge{ padding:4px 10px; border-radius:12px; font-size:12px; color:#fff; }
.mod-badge.visible{ background:#3b82f6; }
.mod-badge.infrared{ background:#ef4444; }
.mod-badge.mmwave{ background:#7c3aed; }
.mod-badge.lidar{ background:#0891b2; }
.mod-image{ height:320px; background:#0f172a; display:flex; align-items:center; justify-content:center; }
.mod-image img{ max-width:100%; max-height:100%; object-fit:contain; }
.mod-info{ padding:10px 16px; color:#64748b; font-size:13px; }
</style>
