<template>
<div class="page" v-if="dataset">
  <div class="top-bar"><el-button text @click="$router.back()">← 返回</el-button></div>
  <div class="hero">
    <h1>{{ dataset.name }}</h1>
    <p>版本 {{ dataset.version }} · {{ dataset.sample_count }} 个样本 · {{ dataset.visibility === 'public' ? '公开' : '私有' }}</p>
  </div>
  <div class="stats">
    <div class="stat-card"><div class="icon">📦</div><h2>{{ dataset.sample_count }}</h2><span>样本总数</span></div>
    <div class="stat-card"><div class="icon">🏷</div><h2>{{ dataset.version }}</h2><span>当前版本</span></div>
    <div class="stat-card"><div class="icon">{{ dataset.visibility === 'public' ? '🌐' : '🔒' }}</div><h2>{{ dataset.visibility === 'public' ? '公开' : '私有' }}</h2><span>可见范围</span></div>
  </div>
  <div class="card">
    <h3>数据集信息</h3>
    <table class="kv"><tr><td>数据集名称</td><td>{{ dataset.name }}</td></tr>
    <tr><td>版本</td><td>{{ dataset.version }}</td></tr>
    <tr><td>样本数量</td><td>{{ dataset.sample_count }}</td></tr>
    <tr><td>状态</td><td><el-tag :type="dataset.status==='published'?'success':dataset.status==='frozen'?'warning':'info'" round size="small">{{ dataset.status }}</el-tag></td></tr>
    <tr><td>可见范围</td><td>{{ dataset.visibility === 'public' ? '公开' : '私有' }}</td></tr>
    <tr><td>创建时间</td><td>{{ dataset.created_at }}</td></tr></table>
  </div>
  <div class="card" v-if="dataset.samples && dataset.samples.length > 0">
    <h3>包含样本 ({{ dataset.samples.length }})</h3>
    <div class="sample-grid">
      <div v-for="s in dataset.samples" :key="s.sample_id" class="sample-item">
        <div class="thumb-row">
          <div v-for="img in s.images.slice(0,4)" :key="img.resource_id" class="mini-thumb" :class="img.modality">
            <span class="mod-label">{{ modShort(img.modality) }}</span>
          </div>
        </div>
        <div class="sample-meta">
          <span>#{{ s.sample_id }}</span>
          <span>{{ s.scene }}</span>
          <span>{{ s.modality_count }}模态</span>
        </div>
      </div>
    </div>
  </div>
</div>
<div v-else class="loading">加载中...</div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { sharedDatasets } from '@/mock/data'
import { getDataList } from '@/api/data'

const route = useRoute()
function modShort(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
const dataset = ref(null)

onMounted(async () => {
  dataset.value = sharedDatasets.find(d => d.dataset_id === Number(route.params.id))
  // 从后端获取数据集的真实样本
  try {
    const { data } = await getDataList({ page: 1, size: 6000 })
    const items = (data.items || []).filter(item => item.meta_info?.sample_group)
    // 如果数据集有 samples 字段，过滤匹配的样本
    if (dataset.value?.samples) {
      const sampleIds = new Set(dataset.value.samples.map(s => s.sample_id))
      const groupMap = {}
      items.filter(item => sampleIds.has(item.meta_info.sample_group)).forEach(item => {
        const gid = item.meta_info.sample_group
        if (!groupMap[gid]) groupMap[gid] = { sample_id: gid, scene: item.meta_info.scene || '-', images: [], modality_count: 0 }
        groupMap[gid].images.push({
          resource_id: item.resource_id, modality: item.modality, name: item.name,
          thumbnail: `/api/images/${item.resource_id}/thumbnail`, annotation_status: item.annotation_status
        })
        groupMap[gid].modality_count = groupMap[gid].images.length
      })
      dataset.value.samples = Object.values(groupMap)
    }
  } catch { /* backend not ready */ }
})
</script>

<style scoped>
.page{ padding:28px; max-width:900px; margin:auto; min-height:100vh; }
.top-bar{ margin-bottom:12px; }
.hero{ padding:32px 40px; margin-bottom:24px; border-radius:18px;
  background: linear-gradient(135deg, #0f172a, #1e3a8a); color:white;
  box-shadow: 0 10px 30px rgba(30,64,175,.18); }
.hero h1{ font-size:26px; margin-bottom:6px; }
.hero p{ opacity:.85; }
.stats{ display:grid; grid-template-columns:repeat(3,1fr); gap:20px; margin-bottom:24px; }
.stat-card{ background:#fff; border-radius:16px; padding:24px; text-align:center;
  border:1px solid #e2e8f0; box-shadow:0 4px 12px rgba(15,23,42,.04); }
.stat-card h2{ font-size:28px; color:#2563eb; margin:8px 0; }
.stat-card span{ color:#64748b; font-size:14px; }
.card{ background:#fff; border-radius:16px; padding:24px; margin-bottom:20px;
  border:1px solid #e2e8f0; box-shadow:0 4px 12px rgba(15,23,42,.04); }
.card h3{ margin-bottom:14px; }
.kv td{ padding:8px 12px 8px 0; font-size:14px; }
.kv td:first-child{ color:#6b7280; width:100px; }
.actions{ display:flex; gap:12px; }
.loading{ text-align:center; padding:60px; color:#9ca3af; }
.sample-grid{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; }
.sample-item{ background:#f8fafc; border-radius:10px; padding:10px; border:1px solid #e2e8f0; }
.thumb-row{ display:grid; grid-template-columns:1fr 1fr; gap:2px; margin-bottom:8px; }
.mini-thumb{ height:60px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:12px; color:#fff; }
.mini-thumb.visible{ background:#3b82f6; }
.mini-thumb.infrared{ background:#ef4444; }
.mini-thumb.mmwave{ background:#7c3aed; }
.mini-thumb.lidar{ background:#0891b2; }
.mod-label{ font-weight:600; }
.sample-meta{ display:flex; gap:8px; font-size:12px; color:#6b7280; }
</style>
