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
      <div class="icon">📈</div>
      <h2>{{ annotationRate }}%</h2>
      <span>标注完成率</span>
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

      <span>训练集</span>

      <strong>{{ dataset.subset_counts?.train || 0 }} 条</strong>

      </div>

      <div class="info-item">

      <span>验证集</span>

      <strong>{{ dataset.subset_counts?.val || 0 }} 条</strong>

      </div>

      <div class="info-item">

      <span>测试集</span>

      <strong>{{ dataset.subset_counts?.test || 0 }} 条</strong>

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
      <div
        v-for="s in pagedSamples"
        :key="s.sample_id"
        class="sample-item"
        @click="openSample(s)"
      >
        <div class="thumb-row" :class="'n' + displayThumbs(s).length">
          <div
            v-for="img in displayThumbs(s)"
            :key="img.resource_id"
            class="mini-thumb"
            :class="img.modality"
          >
            <span class="mod-tag">{{ modShort(img.modality, img) }}</span>
            <img :src="img.thumbnail" loading="lazy" @error="onThumbError" />
          </div>
        </div>
        <div class="sample-meta">
          <span>#{{ s.group_no ?? s.sample_id }}</span>
          <span>{{ s.scene }}</span>
          <span>{{ s.modality_count }}模态</span>
        </div>
      </div>
    </div>
    <el-pagination
      v-if="sampleData.length > pageSize"
      background
      layout="prev, pager, next"
      :total="sampleData.length"
      :page-size="pageSize"
      :current-page="currentPage"
      @current-change="currentPage = $event"
      style="margin-top:16px;justify-content:center;"
    />
  </div>
</div>
<div v-else class="loading">加载中...</div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDatasetDetail } from '@/api/dataset'
import request from '@/api/request'

const route = useRoute()
const router = useRouter()

const THUMB_SLOTS = [
  { modality: 'visible', prefer: 'DA8679037', label: '可见光' },
  { modality: 'infrared', prefer: null, label: '红外' },
  { modality: 'mmwave', prefer: null, label: '毫米波' },
  { modality: 'lidar', prefer: null, label: '激光雷达' },
]

function modShort(m, img) {
  if (img?._slotLabel) return img._slotLabel
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}

function displayThumbs(sample) {
  // 有几个模态就展示几张；可见光只放设备1，标签仍为「可见光」；不补空白格
  const images = sample?.images || []
  const used = new Set()
  const result = []
  for (const slot of THUMB_SLOTS) {
    const candidates = images.filter(
      img => (img.modality || '') === slot.modality && !used.has(img.resource_id)
    )
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
  return result
}

function onThumbError(e) {
  e.target.style.opacity = '0.25'
}

function openSample(s) {
  // 带上数据集内该样本的 resource_id，详情页只展示所选模态
  const ids = (s.images || []).map(i => i.resource_id).filter(Boolean).join(',')
  router.push({
    name: 'SampleDetail',
    params: { id: String(s.group_no ?? s.sample_id) },
    query: {
      batch: s.batch_id || undefined,
      ids: ids || undefined,
    },
  })
}

const dataset = ref(null)
const sampleData = ref([])
const currentPage = ref(1)
const pageSize = 10

const annotationRate = computed(() => {
  const total = Number(dataset.value?.sample_count || 0)
  const annotated = Number(dataset.value?.annotated_count || 0)
  if (!total) return 0
  return Math.round((annotated * 100) / total)
})

const pagedSamples = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return sampleData.value.slice(start, start + pageSize)
})

async function loadDataset(id) {
  if (!id) {
    dataset.value = null
    sampleData.value = []
    return
  }
  dataset.value = null
  sampleData.value = []
  currentPage.value = 1
  try {
    const { data } = await getDatasetDetail(id)
    dataset.value = data
    try {
      const res = await request.get(`/datasets/${id}/items`)
      const samples = res.data?.samples || []
      sampleData.value = samples.map(s => {
        const images = (s.resources || []).map(r => ({
          resource_id: r.resource_id,
          modality: r.modality,
          name: r.name,
          sensor: r.sensor || '',
          thumbnail: `/api/images/${r.resource_id}/thumbnail`,
          annotation_status: r.annotation_status,
        }))
        return {
          sample_id: s.sample_id || `${s.batch_id || 'unknown'}::${s.sample_group}`,
          group_no: s.sample_group,
          batch_id: s.batch_id || '',
          scene: s.scene || '-',
          modality_count: new Set(images.map(i => i.modality)).size,
          images,
        }
      }).sort((a, b) => {
        const na = Number(a.group_no)
        const nb = Number(b.group_no)
        if (Number.isFinite(na) && Number.isFinite(nb) && na !== nb) return na - nb
        return String(a.group_no ?? '').localeCompare(String(b.group_no ?? ''), undefined, { numeric: true })
      })
    } catch { /* sample preview optional */ }
  } catch {
    dataset.value = null
  }
}

// keep-alive 下切换 /datasets/:id 必须监听，否则会一直显示第一次打开的详情
watch(() => route.params.id, (id) => { loadDataset(id) }, { immediate: true })
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
grid-template-columns: repeat(3, 1fr);
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
cursor:pointer;

}

.sample-item:hover{

transform:translateY(-6px);

box-shadow:
0 12px 28px rgba(15,23,42,.12);

}
.thumb-row{ display:grid; gap:2px; margin-bottom:8px; background:#e2e8f0; border-radius:8px; overflow:hidden; padding:2px; }
.thumb-row.n1{ grid-template-columns:1fr; }
.thumb-row.n2{ grid-template-columns:1fr 1fr; }
.thumb-row.n3,
.thumb-row.n4{ grid-template-columns:1fr 1fr; }
.mini-thumb{
  position:relative;
  aspect-ratio:1;
  height:auto;
  min-height:72px;
  border-radius:6px;
  overflow:hidden;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:12px;
  color:#fff;
  background:#0f172a;
}
.mini-thumb img{ width:100%; height:100%; object-fit:cover; }
.mod-tag{
  position:absolute; top:4px; left:4px; z-index:1;
  font-size:10px; padding:1px 6px; border-radius:8px;
  background:rgba(0,0,0,.55); color:#fff;
}
.sample-meta{ display:flex; gap:8px; font-size:12px; color:#6b7280; flex-wrap:wrap; }
</style>
