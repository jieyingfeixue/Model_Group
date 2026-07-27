<template>
  <div class="sample-card" @click="$emit('select', sample)">
    <div class="card-thumbs">
      <div v-for="img in displayImages" :key="img.resource_id" class="thumb-slot"
        :class="img.modality">
        <span class="mod-tag">{{ modShort(img.modality, img) }}</span>
        <img :src="img.thumbnail" loading="lazy" @error="onThumbError" />
        <span v-if="img.annotation_status==='annotated'" class="anno-dot" title="已标注"></span>
      </div>
      <div v-for="n in (4 - displayImages.length)" :key="'empty-'+n" class="thumb-slot empty">
        <span class="empty-text">—</span>
      </div>
    </div>
    <div class="card-info">
      <div class="sample-name">样本 #{{ sample.group_no ?? sample.sample_id }}</div>
      <div class="sample-meta">
        <span>{{ sceneLabel(sample.scene) }}</span>
        <span>{{ sample.time_of_day === 'night' ? '夜间' : (sample.time_of_day === 'day' ? '白天' : '-') }}</span>
        <span>{{ sample.modality_count }} 模态</span>
      </div>
      <div class="sample-batch">{{ shortBatch(sample.batch_id) }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ sample: Object })
defineEmits(['select'])

// 浏览四宫格：设备1可见光、红外、毫米波、激光雷达（不含设备2）
const BROWSE_SLOTS = [
  { modality: 'visible', prefer: 'DA8679037', label: '设备1' },
  { modality: 'infrared', prefer: null, label: '红外' },
  { modality: 'mmwave', prefer: null, label: '毫米波' },
  { modality: 'lidar', prefer: null, label: '激光雷达' },
]

const displayImages = computed(() => {
  const images = props.sample?.images || []
  const used = new Set()
  const result = []
  for (const slot of BROWSE_SLOTS) {
    const candidates = images.filter(img => (img.modality || '') === slot.modality && !used.has(img.resource_id))
    if (!candidates.length) continue
    let pick = candidates[0]
    if (slot.prefer) {
      const preferred = candidates.find(img =>
        String(img.sensor || img.name || '').includes(slot.prefer)
      )
      if (preferred) pick = preferred
    }
    used.add(pick.resource_id)
    result.push({ ...pick, _slotLabel: slot.label })
  }
  return result.slice(0, 4)
})

function modShort(m, img) {
  if (img?._slotLabel) return img._slotLabel
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
function sceneLabel(s) {
  if (!s || s === '-') return '-'
  const map = { daytime: '白天', night: '夜间', rainy: '雨天', foggy: '雾天' }
  return map[s] || s
}
function shortBatch(b) {
  if (!b) return ''
  const m = String(b).match(/with_cameras_capture_(\d{8}_\d{6})/)
  return m ? m[1] : b
}
function onThumbError(e) {
  e.target.style.opacity = '0.2'
}
</script>

<style scoped>
.sample-card {
  background: #fff; border-radius: 16px; overflow: hidden; cursor: pointer;
  border: 1px solid #e2e8f0; box-shadow: 0 4px 14px rgba(15,23,42,.04);
  transition: all .25s;
}
.sample-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 28px rgba(37,99,235,.12);
  border-color: #bfdbfe;
}
.card-thumbs {
  display: grid; grid-template-columns: 1fr 1fr; gap: 2px;
  background: #e2e8f0; padding: 2px;
}
.thumb-slot {
  position: relative; aspect-ratio: 1; background: #0f172a;
  display: flex; align-items: center; justify-content: center; overflow: hidden;
}
.thumb-slot img { width:100%; height:100%; object-fit:cover; }
.thumb-slot.empty { background: #f1f5f9; }
.empty-text { font-size: 24px; color: #cbd5e1; }
.mod-tag { position:absolute; top:4px; left:4px; font-size:10px; padding:1px 6px;
  border-radius:8px; background:rgba(0,0,0,.55); color:#fff; z-index:1; }
.anno-dot {
  position: absolute; top: 6px; right: 6px; width: 8px; height: 8px;
  border-radius: 50%; background: #22c55e; border: 1px solid #fff;
}
.card-info { padding: 10px 12px; }
.sample-name { font-size: 13px; font-weight: 700; color: #1e293b; margin-bottom: 4px; }
.sample-meta { display: flex; gap: 8px; font-size: 11px; color: #64748b; margin-bottom: 2px; }
.sample-batch { font-size: 10px; color: #94a3b8; }
</style>
