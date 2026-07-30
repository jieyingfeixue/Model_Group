<template>
<div class="page">
  <div class="top-bar">
    <el-button text @click="$router.back()">← 返回</el-button>
    <el-button type="primary" plain size="small" @click="openAnnotateHub">打开标注工具</el-button>
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
      <div
        v-for="img in sample.images"
        :key="img.resource_id"
        class="modality-card"
        @click="openDetail(img.resource_id)"
      >
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

    <div class="meta-panel">
      <div class="meta-head">
        <div class="meta-title">图片元信息</div>
        <div class="meta-hint">本样本各传感器资源的技术字段（分辨率、时间戳、文件等）</div>
      </div>
      <el-table :data="sample.images" stripe size="small" class="meta-table" empty-text="暂无资源">
        <el-table-column label="视图" min-width="100">
          <template #default="{ row }">{{ cardTitle(row) }}</template>
        </el-table-column>
        <el-table-column label="模态" min-width="90">
          <template #default="{ row }">{{ modLabel(row.modality) }}</template>
        </el-table-column>
        <el-table-column label="分辨率" min-width="110">
          <template #default="{ row }">{{ resolutionText(row) }}</template>
        </el-table-column>
        <el-table-column label="时间戳" min-width="110">
          <template #default="{ row }">{{ timestampText(row) }}</template>
        </el-table-column>
        <el-table-column label="大小" min-width="90">
          <template #default="{ row }">{{ row.file_size || '-' }}</template>
        </el-table-column>
        <el-table-column prop="resource_id" label="Resource ID" min-width="110" />
        <el-table-column label="传感器" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.sensor || '-' }}</template>
        </el-table-column>
        <el-table-column label="文件名" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.name || '-' }}</template>
        </el-table-column>
        <el-table-column label="标注" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.annotation_status==='annotated'" type="success" size="small" round>已标注</el-tag>
            <el-tag v-else type="warning" size="small" round>未标注</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row.resource_id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
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

function resolutionText(img) {
  const w = Number(img.width)
  const h = Number(img.height)
  if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) return `${w} × ${h}`
  return '-'
}

function timestampText(img) {
  const raw = img.timestamp ?? img.timestamp_offset ?? img.ts
  if (raw != null && raw !== '') {
    const n = Number(raw)
    return Number.isFinite(n) ? n.toFixed(3) : String(raw)
  }
  const m = String(img.name || '').match(/_t(\d+\.\d+)/)
  return m ? m[1] : '-'
}

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

    const params = { page: 1, size: 100, sample_group }
    if (batch_id) params.batch_id = batch_id

    const { data } = await getDataList(params)
    let items = data?.items || []

    if (batch_id) {
      items = items.filter(it => (it.meta_info?.batch_id || '') === batch_id)
    }
    items = items.filter(it => Number(it.meta_info?.sample_group) === sample_group)

    const idsRaw = route.query.ids ? String(route.query.ids) : ''
    if (idsRaw) {
      const allow = new Set(idsRaw.split(',').map(Number).filter(n => Number.isFinite(n)))
      if (allow.size) items = items.filter(it => allow.has(it.resource_id))
    }

    const modsRaw = route.query.modalities ? String(route.query.modalities) : ''
    if (modsRaw) {
      const mods = new Set(modsRaw.split(',').filter(Boolean))
      if (mods.size) items = items.filter(it => mods.has(it.modality))
    }

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
        width: item.meta_info?.width,
        height: item.meta_info?.height,
        channels: item.meta_info?.channels,
        file_size: item.meta_info?.file_size,
        timestamp: item.meta_info?.timestamp_offset ?? item.meta_info?.timestamp ?? item.meta_info?.ts,
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

watch(() => [route.params.id, route.query.batch, route.query.ids], loadSample, { immediate: true })

function openDetail(resourceId) {
  const ids = (sample.value?.images || []).map(i => i.resource_id).join(',')
  router.push({
    name: 'DataDetail',
    params: { id: String(resourceId) },
    query: ids ? { ids } : {},
  })
}

function openAnnotateHub() {
  router.push({ name: 'AnnotationHub' })
}
</script>

<style scoped>
.page{ padding:28px; max-width:1450px; margin:auto; min-height:100vh; }
.top-bar{ margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; gap:12px; }
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
.modality-card{ background:#fff; border-radius:14px; overflow:hidden; cursor:pointer;
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

.meta-panel{
  margin-top:24px;
  background:#fff;
  border:1px solid #e2e8f0;
  border-radius:14px;
  padding:18px 20px 12px;
  box-shadow:0 4px 14px rgba(15,23,42,.04);
}
.meta-head{ margin-bottom:12px; }
.meta-title{ font-size:16px; font-weight:700; color:#1e293b; }
.meta-hint{ margin-top:4px; font-size:13px; color:#94a3b8; }
.meta-table{ width:100%; }
</style>
