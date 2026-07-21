<template>
  <div class="my-data-page">
    <div class="page-header">
      <div>
        <div class="page-tag">Dataset Explorer</div>
        <h1>数据浏览</h1>
        <p>浏览当前用户上传的数据资源，支持模态 / 场景筛选与分页。</p>
      </div>
    </div>

    <div class="filter-card">
      <div class="section-title">数据筛选</div>
      <SearchFilter
        :modelValue="filters"
        @update:modelValue="onFilterChange"
      />
    </div>

    <div class="toolbar">
      <div class="count">
        共 <span>{{ total }}</span> 条数据
      </div>
      <div class="tip">对接 GET /api/data</div>
    </div>

    <div class="grid-card" v-loading="loading">
      <div v-if="!loading && samples.length === 0" class="empty">暂无数据（请先上传或检查登录）</div>
      <div v-else class="sample-grid">
        <SampleCard
          v-for="s in samples"
          :key="s.sample_id"
          :sample="s"
          @select="onSelect"
        />
      </div>
      <div class="pagination" v-if="total > pageSize">
        <el-pagination
          background
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="currentPage"
          @current-change="onPageChange"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SearchFilter from '@/components/common/SearchFilter.vue'
import SampleCard from '@/components/common/SampleCard.vue'
import { getDataList, getThumbnailUrl } from '@/api/data'

const router = useRouter()
const samples = ref([])
const total = ref(0)
const pageSize = ref(12)
const currentPage = ref(1)
const filters = ref({})
const loading = ref(false)
const idList = ref([])

function resourceToSample(r) {
  const meta = r.meta_info || {}
  return {
    sample_id: r.resource_id,
    scene: meta.scene || filters.value.scene || 'daytime',
    time_of_day: meta.time_of_day || 'day',
    modality_count: 1,
    batch_id: meta.batch_id || r.name || `res-${r.resource_id}`,
    alignment_group_id: String(r.resource_id),
    images: [
      {
        resource_id: r.resource_id,
        modality: r.modality || 'visible',
        thumbnail: getThumbnailUrl(r.resource_id),
        annotation_status: r.annotation_status,
      },
    ],
  }
}

function onFilterChange(val) {
  filters.value = val
  currentPage.value = 1
  fetchSamples()
}

async function fetchSamples() {
  loading.value = true
  try {
    const f = filters.value || {}
    const { data } = await getDataList({
      page: currentPage.value,
      page_size: pageSize.value,
      modality: f.modality,
      scene: f.scene || undefined,
      annotation_status: f.annotation_status || undefined,
    })
    let items = data.items || []
    if (f.keyword) {
      const kw = String(f.keyword).toLowerCase()
      items = items.filter(
        (r) =>
          String(r.name || '').toLowerCase().includes(kw) ||
          String(r.resource_id).includes(kw) ||
          String((r.meta_info || {}).batch_id || '').toLowerCase().includes(kw),
      )
    }
    samples.value = items.map(resourceToSample)
    idList.value = items.map((r) => r.resource_id)
    total.value = data.total ?? items.length
  } catch (e) {
    samples.value = []
    total.value = 0
    ElMessage.error(e?.response?.data?.detail || '加载数据失败')
  } finally {
    loading.value = false
  }
}

function onSelect(sample) {
  router.push({
    path: `/data/${sample.sample_id}`,
    query: { ids: idList.value.join(',') },
  })
}

function onPageChange(page) {
  currentPage.value = page
  fetchSamples()
}

onMounted(fetchSamples)
</script>

<style scoped>
.my-data-page{padding:32px;max-width:1400px;margin:auto;background:#f8fafc;min-height:100vh}
.page-header{
  background:linear-gradient(135deg,#0f172a,#1e3a8a);border-radius:18px;padding:45px 50px;
  margin-bottom:28px;color:white;box-shadow:0 10px 30px rgba(30,64,175,.18)
}
.page-tag{
  display:inline-block;padding:8px 18px;background:rgba(255,255,255,.12);
  border-radius:20px;font-size:13px;margin-bottom:20px
}
.page-header h1{font-size:38px;font-weight:700;margin:0 0 16px}
.page-header p{font-size:16px;opacity:.88;line-height:1.8;margin:0}
.filter-card,.grid-card{
  background:white;border-radius:18px;padding:26px;margin-bottom:26px;
  box-shadow:0 6px 18px rgba(15,23,42,.05);border:1px solid #edf2f7
}
.section-title{font-size:18px;font-weight:700;margin-bottom:20px;color:#1e293b}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;padding:0 8px}
.count{font-size:16px;color:#475569}
.count span{font-size:26px;font-weight:700;color:#2563eb;margin:0 6px}
.tip{font-size:14px;color:#94a3b8}
.sample-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px}
.empty{text-align:center;color:#94a3b8;padding:40px 0}
.pagination{display:flex;justify-content:center;margin-top:24px}
@media (max-width:768px){
  .my-data-page{padding:18px}
  .page-header{padding:30px}
  .page-header h1{font-size:28px}
  .toolbar{flex-direction:column;align-items:flex-start;gap:10px}
}
</style>
