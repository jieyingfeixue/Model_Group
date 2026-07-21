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
import { generateSamples } from '@/mock/data'

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
function fetchSamples() {
  let all = generateSamples(12)
  const f = filters.value
  // 模态筛选：AND 逻辑，样本必须同时包含所有选中模态
  if (f.modality && f.modality.length > 0) {
    all = all.filter(s => f.modality.every(m => s.images.some(img => img.modality === m)))
  }
  if (f.scene) {
    all = all.filter(s => s.scene === f.scene)
  }
  if (f.keyword) {
    all = all.filter(s => s.alignment_group_id.includes(f.keyword) || s.batch_id.includes(f.keyword))
  }
  const start = (currentPage.value - 1) * pageSize.value
  samples.value = all.slice(start, start + pageSize.value)
  total.value = all.length
}
function onSelect(sample) {
  // 点击样本，后续可跳转到样本详情页
  console.log('Selected sample:', sample)
}
function onPageChange(page) { currentPage.value = page; fetchSamples() }
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

</style>
