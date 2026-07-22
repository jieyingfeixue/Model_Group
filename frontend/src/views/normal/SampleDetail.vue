<template>
<div class="page">
  <div class="top-bar">
    <el-button text @click="$router.back()">← 返回</el-button>
  </div>
  <div v-if="!sample" class="loading">加载中...</div>
  <div v-else>
    <div class="hero">
      <h1>样本 #{{ sample.sample_id }}</h1>
      <p>{{ sceneLabel(sample.scene) }} · {{ sample.time_of_day === 'night' ? '夜间' : '白天' }} · {{ sample.weather }} · {{ sample.batch_id }}</p>
    </div>
    <div class="modality-grid" :class="'cols-' + sample.images.length">
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

function modLabel(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
function sceneLabel(s) {
  const map = { daytime: '白天', night: '夜间', rainy: '雨天', foggy: '雾天' }
  return map[s] || s
}

onMounted(async () => {
  try {
    const { data } = await getDataList({ page: 1, size: 6000 })
    const items = (data.items || []).filter(item => item.meta_info?.sample_group)
    // 按 sample_group 分组
    const groupMap = {}
    items.forEach(item => {
      const gid = item.meta_info.sample_group
      if (!groupMap[gid]) groupMap[gid] = { sample_id: gid, scene: item.meta_info.scene || '-', images: [], batch_id: item.meta_info.batch_id || '-', modality_count: 0 }
      groupMap[gid].images.push({
        resource_id: item.resource_id,
        modality: item.modality,
        name: item.name,
        thumbnail: `/api/images/${item.resource_id}`,
        annotation_status: item.annotation_status,
      })
      groupMap[gid].modality_count = groupMap[gid].images.length
    })
    sample.value = groupMap[Number(route.params.id)]
  } catch { /* backend not ready */ }
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
.mod-image img{ width:100%; height:100%; object-fit:contain; }
.mod-info{ padding:12px 16px; font-size:13px; color:#64748b; }
.lidar-placeholder{ display:flex; align-items:center; justify-content:center;
  height:100%; font-size:18px; font-weight:600; color:#fff; background:#0891b2; }
</style>
