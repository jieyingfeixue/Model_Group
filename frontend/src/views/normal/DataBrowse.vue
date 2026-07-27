<template>
  <div class="my-data-page">

    <!-- 页面头部 -->
    <div class="page-header">

      <div>

        <div class="page-tag">
          📦 Dataset Explorer
        </div>

        <h1>数据浏览</h1>

        <p>
          浏览平台公开数据资源，支持多模态数据检索、筛选与在线预览。
        </p>

      </div>

    </div>

    <!-- 搜索区域 -->
    <div class="filter-card">

      <div class="section-title">

        🔍 数据筛选

      </div>

      <SearchFilter
        :modelValue="filters"
        @update:modelValue="onFilterChange"
      />

    </div>

    <!-- 数据统计 -->
    <div class="toolbar">

      <div class="count">

        共
        <span>{{ total }}</span>
        个样本

      </div>

      <div class="tip">

        默认按最新上传排序

      </div>

    </div>

    <!-- 样本列表 -->
    <div class="grid-card">
      <div v-if="samples.length === 0" class="empty">暂无数据</div>
      <div v-else class="sample-grid">
        <SampleCard v-for="s in samples" :key="s.sample_id" :sample="s"
          @select="onSelect" />
      </div>
      <div class="pagination" v-if="total > pageSize">
        <el-pagination background layout="prev, pager, next" :total="total"
          :page-size="pageSize" :current-page="currentPage" @current-change="onPageChange" />
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import SearchFilter from '@/components/common/SearchFilter.vue'
import SampleCard from '@/components/common/SampleCard.vue'
import { getDataList } from '@/api/data'

const router = useRouter()
const samples = ref([])
const total = ref(0)
const pageSize = ref(12)
const currentPage = ref(1)
const filters = ref({})

function onFilterChange(val) {
  filters.value = val
  currentPage.value = 1
  fetchSamples()
}

async function fetchAllResources(filterParams) {
  const pageSizeApi = 6000
  let page = 1
  let items = []
  let apiTotal = Infinity
  while (items.length < apiTotal) {
    const { data } = await getDataList({
      ...filterParams,
      page,
      size: pageSizeApi,
    })
    apiTotal = Number(data?.total ?? 0)
    const chunk = data?.items || []
    if (!chunk.length) break
    items = items.concat(chunk)
    if (chunk.length < pageSizeApi) break
    page += 1
  }
  return items
}

function sampleKey(meta) {
  return `${meta?.batch_id || 'unknown'}::${meta?.sample_group}`
}

function buildSampleGroups(rawItems) {
  const groupMap = {}
  rawItems
    .filter(item => item.meta_info?.sample_group != null)
    .forEach(item => {
      const meta = item.meta_info || {}
      const gid = sampleKey(meta)
      if (!groupMap[gid]) {
        groupMap[gid] = {
          sample_id: gid,
          group_no: meta.sample_group,
          images: [],
          scene: meta.scene || '-',
          weather: meta.weather,
          time_of_day: meta.time_of_day,
          terrain: meta.terrain,
          obstacle: meta.obstacle,
          batch_id: meta.batch_id || '',
          modality_count: 0,
          _seenResource: new Set(),
          _seenSensor: new Set(),
        }
      }
      const g = groupMap[gid]
      if (g._seenResource.has(item.resource_id)) return
      const sensorKey = meta.sensor || `${item.modality}:${item.name}`
      if (g._seenSensor.has(sensorKey)) return
      g._seenResource.add(item.resource_id)
      g._seenSensor.add(sensorKey)
      g.images.push({
        resource_id: item.resource_id,
        modality: item.modality,
        name: item.name,
        sensor: meta.sensor || '',
        thumbnail: `/api/images/${item.resource_id}/thumbnail`,
        annotation_status: item.annotation_status,
      })
      g.modality_count = new Set(g.images.map(i => i.modality)).size
    })
  return Object.values(groupMap).map(({ _seenResource, _seenSensor, ...rest }) => rest)
}

async function fetchSamples() {
  try {
    const f = filters.value || {}
    const rawItems = await fetchAllResources({
      weather: f.weather || undefined,
      time_of_day: f.time_of_day || undefined,
      terrain: f.terrain || undefined,
      obstacle: f.obstacle || undefined,
    })
    const all = buildSampleGroups(rawItems)
    total.value = all.length
    const start = (currentPage.value - 1) * pageSize.value
    samples.value = all.slice(start, start + pageSize.value)
  } catch { /* backend not ready */ }
}
function onSelect(sample) {
  // 避免把 batch_id 放进 path（含特殊字符时路由会解析错，导致总进同一个样本）
  router.push({
    name: 'SampleDetail',
    params: { id: String(sample.group_no ?? sample.sample_id) },
    query: { batch: sample.batch_id || undefined },
  })
}
function onPageChange(page) { currentPage.value = page; fetchSamples(); window.scrollTo(0, 0) }
onMounted(fetchSamples)
</script>

<style scoped>

.my-data-page{

padding:32px;

max-width:1400px;

margin:auto;

background:#f8fafc;

min-height:100vh;

}

/* ---------- 页面头 ---------- */

.page-header{

background:
linear-gradient(
135deg,
#0f172a,
#1e3a8a
);

border-radius:18px;

padding:45px 50px;

margin-bottom:28px;

color:white;

box-shadow:
0 10px 30px rgba(30,64,175,.18);

}

.page-tag{

display:inline-block;

padding:8px 18px;

background:rgba(255,255,255,.12);

border-radius:20px;

font-size:13px;

margin-bottom:20px;

}

.page-header h1{

font-size:38px;

font-weight:700;

margin:0 0 16px;

}

.page-header p{

font-size:16px;

opacity:.88;

line-height:1.8;

margin:0;

}

/* ---------- 卡片 ---------- */

.filter-card,
.grid-card{

background:white;

border-radius:18px;

padding:26px;

margin-bottom:26px;

box-shadow:
0 6px 18px rgba(15,23,42,.05);

border:1px solid #edf2f7;

}

/* ---------- 标题 ---------- */

.section-title{

font-size:18px;

font-weight:700;

margin-bottom:20px;

color:#1e293b;

}

/* ---------- 工具栏 ---------- */

.toolbar{

display:flex;

justify-content:space-between;

align-items:center;

margin-bottom:18px;

padding:0 8px;

}

.count{

font-size:16px;

color:#475569;

}

.count span{

font-size:26px;

font-weight:700;

color:#2563eb;

margin:0 6px;

}

.tip{

font-size:14px;

color:#94a3b8;

}

/* ---------- 响应式 ---------- */

@media (max-width:768px){

.my-data-page{

padding:18px;

}

.page-header{

padding:30px;

}

.page-header h1{

font-size:28px;

}

.toolbar{

flex-direction:column;

align-items:flex-start;

gap:10px;

}

}

.sample-grid{ display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; }
</style>
