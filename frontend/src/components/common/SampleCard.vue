<template>
  <div class="sample-card" @click="$emit('select', sample)">
    <div class="card-thumbs">
      <div v-for="img in sample.images" :key="img.resource_id" class="thumb-slot"
        :class="img.modality">
        <img :src="img.thumbnail" loading="lazy" @error="e => e.target.style.display='none'" />
        <span class="mod-badge" :class="img.modality">{{ modShort(img.modality) }}</span>
        <span v-if="img.annotation_status==='annotated'" class="anno-dot" title="已标注"></span>
      </div>
      <!-- 填充空白格到 4 个 -->
      <div v-for="n in (4 - sample.images.length)" :key="'empty-'+n" class="thumb-slot empty">
        <span class="empty-text">—</span>
      </div>
    </div>
    <div class="card-info">
      <div class="sample-name">样本 #{{ sample.sample_id }}</div>
      <div class="sample-meta">
        <span>{{ sceneLabel(sample.scene) }}</span>
        <span>{{ sample.time_of_day === 'night' ? '夜间' : '白天' }}</span>
        <span>{{ sample.modality_count }} 模态</span>
      </div>
      <div class="sample-batch">{{ sample.batch_id }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({ sample: Object })
defineEmits(['select'])

function modShort(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
function sceneLabel(s) {
  const map = { daytime: '白天', night: '夜间', rainy: '雨天', foggy: '雾天' }
  return map[s] || s
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
  position: relative; height: 100px; background: #f8fafc;
  display: flex; align-items: center; justify-content: center; overflow: hidden;
}
.thumb-slot img {
  width: 100%; height: 100%; object-fit: cover;
}
.thumb-slot.empty {
  background: #f1f5f9;
}
.empty-text {
  font-size: 24px; color: #cbd5e1;
}
.mod-badge {
  position: absolute; bottom: 4px; left: 4px; font-size: 10px;
  padding: 1px 6px; border-radius: 10px; background: rgba(0,0,0,.55); color: #fff;
}
.anno-dot {
  position: absolute; top: 6px; right: 6px; width: 8px; height: 8px;
  border-radius: 50%; background: #22c55e; border: 1px solid #fff;
}
.card-info {
  padding: 14px 16px;
}
.sample-name {
  font-size: 15px; font-weight: 700; color: #1e293b; margin-bottom: 6px;
}
.sample-meta {
  display: flex; gap: 12px; font-size: 12px; color: #64748b; margin-bottom: 4px;
}
.sample-batch {
  font-size: 11px; color: #94a3b8;
}
</style>
