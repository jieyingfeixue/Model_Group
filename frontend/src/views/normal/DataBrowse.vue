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
        条数据

      </div>

      <div class="tip">

        默认按最新上传排序

      </div>

    </div>

    <!-- 数据列表 -->
    <div class="grid-card">

      <DataGrid
        :items="dataList"
        :total="total"
        :page-size="pageSize"
        :current-page="currentPage"
        @select="onSelect"
        @page-change="onPageChange"
      />

    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import SearchFilter from '@/components/common/SearchFilter.vue'
import DataGrid from '@/components/common/DataGrid.vue'
import { getDataList } from '@/api/data'

const router = useRouter()
const dataList = ref([])
const total = ref(0)
const pageSize = ref(12)
const currentPage = ref(1)
const filters = ref({})

function onFilterChange(val) {
  filters.value = val
  currentPage.value = 1
  fetchData()
}

async function fetchData() {
  const f = filters.value
  const params = {
    page: currentPage.value,
    page_size: pageSize.value,
    modality: f.modality || undefined,
  }
  try {
    const { data } = await getDataList(params)
    dataList.value = data.items || []
    total.value = data.total || 0
  } catch { /* backend not ready */ }
}

function onSelect(item) {
  const ids = dataList.value.map(d => d.resource_id)
  router.push({ name: 'DataDetail', params: { id: item.resource_id }, query: { ids: ids.join(',') } })
}
function onPageChange(page) { currentPage.value = page; fetchData() }

onMounted(fetchData)
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

</style>
