<template>
<div class="page">
  <div class="fx-bg" aria-hidden="true">
    <span class="orb orb-a"></span>
    <span class="orb orb-b"></span>
    <span class="orb orb-c"></span>
    <span class="mesh"></span>
  </div>

  <div class="top-bar">
    <el-button text @click="$router.back()">← 返回</el-button>
    <el-button type="primary" plain size="small" @click="openAnnotateHub">打开标注工具</el-button>
  </div>

  <div v-if="!sample" class="loading">{{ loadError || '加载中...' }}</div>
  <div v-else class="content">
    <div class="hero">
      <div class="hero-aurora" aria-hidden="true"></div>
      <div class="hero-sparkles" aria-hidden="true">
        <i v-for="n in 12" :key="n" :style="sparkStyle(n)"></i>
      </div>
      <div class="hero-copy">
        <div class="hero-chip">Multi-Sensor Sample</div>
        <h1>样本 #{{ sample.group_no }}</h1>
        <p>
          {{ sceneLabel(sample.scene) }} ·
          {{ sample.time_of_day === 'night' ? '夜间' : (sample.time_of_day === 'day' ? '白天' : '-') }} ·
          {{ sample.weather }} · {{ sample.batch_id }}
        </p>
      </div>
      <div class="hero-ring" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
    </div>

    <div class="modality-grid" :class="'cols-' + Math.min(sample.images.length, 5)">
      <div
        v-for="(img, idx) in sample.images"
        :key="img.resource_id"
        class="modality-card"
        :style="{ '--delay': `${idx * 70}ms` }"
        @click="openDetail(img.resource_id)"
      >
        <div class="card-sheen" aria-hidden="true"></div>
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

    <!-- 底部装饰带：只做氛围，不堆功能 -->
    <footer class="decor-band" aria-hidden="true">
      <svg class="wave" viewBox="0 0 1440 120" preserveAspectRatio="none">
        <defs>
          <linearGradient id="waveGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.15" />
            <stop offset="50%" stop-color="#6366f1" stop-opacity="0.35" />
            <stop offset="100%" stop-color="#22d3ee" stop-opacity="0.15" />
          </linearGradient>
        </defs>
        <path fill="url(#waveGrad)" d="M0,64 C240,120 480,0 720,48 C960,96 1200,16 1440,64 L1440,120 L0,120 Z">
          <animate
            attributeName="d"
            dur="8s"
            repeatCount="indefinite"
            values="
              M0,64 C240,120 480,0 720,48 C960,96 1200,16 1440,64 L1440,120 L0,120 Z;
              M0,48 C240,0 480,96 720,64 C960,32 1200,100 1440,48 L1440,120 L0,120 Z;
              M0,64 C240,120 480,0 720,48 C960,96 1200,16 1440,64 L1440,120 L0,120 Z
            "
          />
        </path>
      </svg>
      <div class="constellation">
        <span v-for="n in 18" :key="'s'+n" class="star" :style="starStyle(n)"></span>
      </div>
      <p class="decor-caption">传感器对齐 · 多模态一帧</p>
    </footer>
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

function sparkStyle(n) {
  const left = 8 + ((n * 17) % 84)
  const top = 12 + ((n * 29) % 70)
  const delay = (n * 0.35) % 4
  const size = 2 + (n % 3)
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${size}px`,
    height: `${size}px`,
    animationDelay: `${delay}s`,
  }
}

function starStyle(n) {
  const left = ((n * 37) % 100)
  const top = 10 + ((n * 19) % 70)
  const delay = (n * 0.22) % 3
  const size = 1.5 + (n % 4) * 0.6
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${size}px`,
    height: `${size}px`,
    animationDelay: `${delay}s`,
  }
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

    const idsRaw = route.query.ids ? String(route.query.ids) : ''
    if (idsRaw) {
      const allow = new Set(
        idsRaw.split(',').map(Number).filter(n => Number.isFinite(n))
      )
      if (allow.size) {
        items = items.filter(it => allow.has(it.resource_id))
      }
    }

    const modsRaw = route.query.modalities ? String(route.query.modalities) : ''
    if (modsRaw) {
      const mods = new Set(modsRaw.split(',').filter(Boolean))
      if (mods.size) {
        items = items.filter(it => mods.has(it.modality))
      }
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
.page {
  position: relative;
  padding: 28px;
  max-width: 1450px;
  margin: auto;
  min-height: 100vh;
  overflow: hidden;
  background: #f4f7fc;
}

.fx-bg {
  pointer-events: none;
  position: absolute;
  inset: 0;
  z-index: 0;
}
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(40px);
  opacity: 0.55;
  animation: floaty 12s ease-in-out infinite alternate;
}
.orb-a {
  width: 420px; height: 420px;
  left: -120px; top: -80px;
  background: radial-gradient(circle, rgba(56,189,248,.45), transparent 70%);
}
.orb-b {
  width: 360px; height: 360px;
  right: -80px; top: 120px;
  background: radial-gradient(circle, rgba(99,102,241,.35), transparent 70%);
  animation-delay: -3s;
}
.orb-c {
  width: 480px; height: 280px;
  left: 30%; bottom: 40px;
  background: radial-gradient(circle, rgba(34,211,238,.22), transparent 70%);
  animation-delay: -6s;
}
.mesh {
  position: absolute;
  inset: 0;
  opacity: 0.35;
  background-image:
    linear-gradient(rgba(148,163,184,.12) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148,163,184,.12) 1px, transparent 1px);
  background-size: 36px 36px;
  mask-image: radial-gradient(ellipse at 50% 20%, black 20%, transparent 75%);
}
@keyframes floaty {
  from { transform: translate(0, 0) scale(1); }
  to { transform: translate(24px, 18px) scale(1.06); }
}

.top-bar,
.content,
.loading {
  position: relative;
  z-index: 1;
}

.top-bar {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.hero {
  position: relative;
  padding: 36px 42px;
  margin-bottom: 24px;
  border-radius: 20px;
  color: white;
  overflow: hidden;
  isolation: isolate;
  background: linear-gradient(125deg, #0b1220 0%, #1e3a8a 48%, #0ea5e9 120%);
  box-shadow:
    0 10px 30px rgba(30, 64, 175, 0.2),
    inset 0 1px 0 rgba(255,255,255,0.12);
}
.hero-aurora {
  position: absolute;
  inset: -40% -20%;
  background:
    radial-gradient(circle at 20% 40%, rgba(56,189,248,.35), transparent 40%),
    radial-gradient(circle at 80% 20%, rgba(165,180,252,.28), transparent 35%),
    radial-gradient(circle at 60% 80%, rgba(34,211,238,.22), transparent 40%);
  animation: aurora 9s ease-in-out infinite alternate;
  z-index: -1;
}
@keyframes aurora {
  from { transform: translateX(-2%) rotate(0deg); }
  to { transform: translateX(3%) rotate(4deg); }
}
.hero-sparkles {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.hero-sparkles i {
  position: absolute;
  border-radius: 50%;
  background: white;
  box-shadow: 0 0 8px rgba(255,255,255,.9);
  opacity: 0;
  animation: twinkle 3.6s ease-in-out infinite;
}
@keyframes twinkle {
  0%, 100% { opacity: 0; transform: scale(0.6); }
  40% { opacity: 0.9; transform: scale(1); }
  70% { opacity: 0.2; }
}
.hero-copy { position: relative; max-width: 78%; }
.hero-chip {
  display: inline-block;
  margin-bottom: 12px;
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #e0f2fe;
  background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.18);
  backdrop-filter: blur(6px);
}
.hero h1 {
  font-size: 32px;
  margin: 0 0 10px;
  letter-spacing: 0.02em;
  text-shadow: 0 8px 30px rgba(14,165,233,.35);
}
.hero p {
  margin: 0;
  opacity: 0.88;
  line-height: 1.7;
  font-size: 14px;
}
.hero-ring {
  position: absolute;
  right: -30px;
  top: 50%;
  width: 210px;
  height: 210px;
  transform: translateY(-50%);
  pointer-events: none;
}
.hero-ring span {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.18);
  animation: spin 18s linear infinite;
}
.hero-ring span:nth-child(2) {
  inset: 18px;
  border-color: rgba(125,211,252,0.35);
  animation-duration: 12s;
  animation-direction: reverse;
}
.hero-ring span:nth-child(3) {
  inset: 38px;
  border-style: dashed;
  border-color: rgba(165,180,252,0.45);
  animation-duration: 22s;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading { text-align: center; padding: 60px; color: #9ca3af; }

.modality-grid { display: grid; gap: 20px; }
.modality-grid.cols-1 { grid-template-columns: 1fr; max-width: 700px; }
.modality-grid.cols-2 { grid-template-columns: 1fr 1fr; }
.modality-grid.cols-3 { grid-template-columns: 1fr 1fr 1fr; }
.modality-grid.cols-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
.modality-grid.cols-5 { grid-template-columns: repeat(5, 1fr); }
@media (max-width: 1200px) {
  .modality-grid.cols-5 { grid-template-columns: repeat(3, 1fr); }
  .hero-ring { opacity: 0.35; }
}
@media (max-width: 768px) {
  .modality-grid.cols-4,
  .modality-grid.cols-5 { grid-template-columns: 1fr 1fr; }
  .hero { padding: 28px 22px; }
  .hero-copy { max-width: 100%; }
  .hero-ring { display: none; }
}

.modality-card {
  position: relative;
  background: rgba(255,255,255,0.92);
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid rgba(226,232,240,0.95);
  box-shadow: 0 4px 14px rgba(15,23,42,.05);
  cursor: pointer;
  animation: cardIn .45s ease both;
  animation-delay: var(--delay, 0ms);
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(12px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.modality-card:hover {
  transform: translateY(-4px);
  border-color: rgba(56,189,248,0.45);
  box-shadow:
    0 16px 34px rgba(30,64,175,.12),
    0 0 0 3px rgba(56,189,248,.12);
}
.card-sheen {
  pointer-events: none;
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, transparent 35%, rgba(255,255,255,.45) 48%, transparent 62%);
  transform: translateX(-120%);
  transition: transform .6s ease;
  z-index: 2;
  mix-blend-mode: soft-light;
}
.modality-card:hover .card-sheen { transform: translateX(120%); }

.mod-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
  position: relative;
  z-index: 1;
}
.mod-badge { padding: 4px 10px; border-radius: 12px; font-size: 12px; color: #fff; }
.mod-badge.visible { background: linear-gradient(135deg, #3b82f6, #60a5fa); }
.mod-badge.infrared { background: linear-gradient(135deg, #ef4444, #fb7185); }
.mod-badge.mmwave { background: linear-gradient(135deg, #7c3aed, #a78bfa); }
.mod-badge.lidar { background: linear-gradient(135deg, #0891b2, #22d3ee); }
.mod-image {
  height: 320px;
  background:
    radial-gradient(circle at 30% 20%, rgba(56,189,248,.12), transparent 45%),
    #0b1220;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 1;
}
.mod-image img { max-width: 100%; max-height: 100%; object-fit: contain; }
.mod-info {
  padding: 10px 16px;
  color: #64748b;
  font-size: 13px;
  position: relative;
  z-index: 1;
}

.decor-band {
  position: relative;
  margin-top: 28px;
  min-height: 160px;
  border-radius: 20px;
  overflow: hidden;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(15,23,42,.98));
  border: 1px solid rgba(148,163,184,.16);
  box-shadow: 0 12px 30px rgba(15,23,42,.12);
}
.wave {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  width: 100%;
  height: 100px;
}
.constellation {
  position: absolute;
  inset: 0;
}
.star {
  position: absolute;
  border-radius: 50%;
  background: #e0f2fe;
  box-shadow: 0 0 10px rgba(125,211,252,.9);
  animation: twinkle 4s ease-in-out infinite;
}
.decor-caption {
  position: absolute;
  left: 50%;
  top: 42%;
  transform: translate(-50%, -50%);
  margin: 0;
  color: rgba(226,232,240,.55);
  letter-spacing: 0.28em;
  font-size: 12px;
  text-transform: uppercase;
  text-align: center;
  white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
  .orb,
  .hero-aurora,
  .hero-sparkles i,
  .hero-ring span,
  .modality-card,
  .card-sheen,
  .star,
  .wave path {
    animation: none !important;
    transition: none !important;
  }
}
</style>
