<template>
<div class="page" v-if="dataset">
  <div class="top-bar"><el-button text @click="$router.back()">← 返回</el-button></div>
  <div class="hero">
      <div>
          <h1>📂 {{ dataset.name }}</h1>
          <p>
              数据集详情 · 共 {{ dataset.sample_count }} 个样本
              ·
              {{ dataset.visibility==='public' ? '公开数据集' : '私有数据集' }}
          </p>
      </div>
      <el-tag
          size="large"
          round
          :type="dataset.visibility==='public'?'success':'info'"
      >
          {{ dataset.visibility==='public'?'PUBLIC':'PRIVATE' }}
      </el-tag>
  </div>

  <div class="stats">
    <div class="stat-card">

    <div class="icon">📦</div>

    <h2>{{ dataset.sample_count }}</h2>

    <span>样本数量</span>

    </div>

    <div class="stat-card">

    <div class="icon">✅</div>

    <h2>{{ dataset.annotated_count }}</h2>

    <span>已标注</span>

    </div>

    <div class="stat-card">

    <div class="icon">📈</div>

    <h2>

    {{ Math.round(dataset.annotated_count*100/dataset.sample_count) }}%

    </h2>

    <span>完成率</span>

    </div>

    <div class="stat-card">

    <div class="icon">

    {{ dataset.visibility==='public'?'🌍':'🔒' }}

    </div>

    <h2>

    {{ dataset.visibility==='public'?'公开':'私有' }}

    </h2>

    <span>权限</span>

    </div>

  </div>

  <div class="card">
    <h3>数据集信息</h3>
    <div class="info-list">
      <div class="info-item">
      <span>数据集名称</span>
      <strong>{{ dataset.name }}</strong>
      </div>

      <div class="info-item">

      <span>样本数量</span>

      <strong>{{ dataset.sample_count }}</strong>

      </div>

      <div class="info-item">

      <span>创建时间</span>

      <strong>{{ dataset.created_at }}</strong>

      </div>

      <div class="info-item">

      <span>可见范围</span>

      <el-tag
      round
      type="success"
      v-if="dataset.visibility==='public'"
      >

      公开

      </el-tag>

      <el-tag
      round
      v-else
      >

      私有

      </el-tag>

      </div>

      </div>
  </div>
  <div class="card" v-if="sampleData.length > 0">
    <h3>包含样本 ({{ sampleData.length }})</h3>
    <div class="sample-grid">
      <div v-for="s in sampleData" :key="s.sample_id" class="sample-item">
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
import { getDatasetDetail } from '@/api/dataset'
import { getDataList } from '@/api/data'

const route = useRoute()
function modShort(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
const dataset = ref(null)
const sampleData = ref([])

onMounted(async () => {
  try {
    const { data } = await getDatasetDetail(route.params.id)
    dataset.value = data
    // 从后端获取数据集的样本图片
    try {
      const res = await getDataList({ page: 1, size: 6000 })
      const items = (res.data.items || []).filter(item => item.meta_info?.sample_group)
      // 后端会通过 dataset_items 表关联，这里先展示前20个样本
      const groupMap = {}
      items.slice(0, 80).forEach(item => {
        const gid = item.meta_info.sample_group
        if (!gid) return
        if (!groupMap[gid]) groupMap[gid] = { sample_id: gid, scene: item.meta_info.scene || '-', images: [], modality_count: 0 }
        groupMap[gid].images.push({
          resource_id: item.resource_id, modality: item.modality, name: item.name,
          thumbnail: `/api/images/${item.resource_id}/thumbnail`, annotation_status: item.annotation_status
        })
        groupMap[gid].modality_count = groupMap[gid].images.length
      })
      sampleData.value = Object.values(groupMap).slice(0, 12)
    } catch { /* sample data optional */ }
  } catch {
    dataset.value = null
  }
})
</script>

<style scoped>
.page{
    padding:30px;
    max-width:1450px;
    margin:auto;
    background:#f8fafc;
    min-height:100vh;
}
.top-bar{ margin-bottom:12px; }
.hero{
display:flex;
justify-content:space-between;
align-items:center;

padding:45px 50px;

border-radius:18px;

background:
linear-gradient(
135deg,
#0f172a,
#1e3a8a
);

color:white;

margin-bottom:28px;

box-shadow:
0 10px 30px rgba(30,64,175,.18);

}
.hero h1{ font-size:34px; font-weight:700; margin-bottom:12px; }
.hero p{ font-size:16px; opacity:.92; line-height:1.8; }
.stats{
display:grid;
grid-template-columns:
repeat(4,1fr);
gap:22px;
margin-bottom:30px;
}

.info-list{
margin-top:18px;
}

.info-item{
display:flex;
justify-content:space-between;
align-items:center;
padding:15px 18px;
margin-bottom:10px;
background:#f8fafc;
border-radius:12px;
transition:.25s;
}

.info-item:hover{
background:#eff6ff;
transform:translateX(4px);
}

.stat-card{ background:#fff; border-radius:18px; padding:28px; text-align:center;
  box-shadow:0 8px 22px rgba(15,23,42,.05); transition:.3s; }
.stat-card:hover{ transform:translateY(-6px); }
.stat-card .icon{ font-size:30px; margin-bottom:12px; }
.stat-card h2{ font-size:34px; color:#2563eb; margin:8px 0; }
.stat-card span{ color:#64748b; font-size:14px; }
.card{

background:white;

padding:26px;

border-radius:20px;

box-shadow:
0 8px 24px rgba(15,23,42,.06);

margin-bottom:24px;

transition:.3s;

}

.card:hover{

transform:translateY(-3px);

box-shadow:
0 12px 30px rgba(15,23,42,.08);

}
.card h3{ margin-bottom:14px; }
.kv td{ padding:8px 12px 8px 0; font-size:14px; }
.kv td:first-child{ color:#6b7280; width:100px; }
.actions{ display:flex; gap:12px; }
.loading{ text-align:center; padding:60px; color:#9ca3af; }
.sample-grid{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; }
.sample-item{

background:white;

border-radius:16px;

padding:12px;

border:1px solid #e5e7eb;

transition:.3s;

box-shadow:
0 4px 12px rgba(15,23,42,.04);

}

.sample-item:hover{

transform:translateY(-6px);

box-shadow:
0 12px 28px rgba(15,23,42,.12);

}
.thumb-row{ display:grid; grid-template-columns:1fr 1fr; gap:2px; margin-bottom:8px; }
.mini-thumb{ height:60px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:12px; color:#fff; }
.mini-thumb.visible{ background:#3b82f6; }
.mini-thumb.infrared{ background:#ef4444; }
.mini-thumb.mmwave{ background:#7c3aed; }
.mini-thumb.lidar{ background:#0891b2; }
.mod-label{ font-weight:600; }
.sample-meta{ display:flex; gap:8px; font-size:12px; color:#6b7280; }
</style>
