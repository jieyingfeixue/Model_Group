<template>
  <div class="market-page">
    <div class="market-hero">
      <div>
        <h1>📦 数据集市场</h1>
        <p>
          浏览平台公开数据集与社区共享资源，
          快速用于模型训练、算法评测和实验验证。
        </p>
      </div>
    </div>

    <div class="market-stats">
      <div class="stat">
          <h2>{{datasets.length}}</h2>
          <span>公开数据集</span>
      </div>
      <div class="stat">
          <h2>{{ modalityCount }}</h2>
          <span>数据模态</span>
      </div>
      <div class="stat">
          <h2>{{ datasets.length > 0 ? '✓' : '-' }}</h2>
          <span>开放共享</span>
      </div>
    </div>

    <div class="filter-panel">
      <div class="filter-title">
        <div class="title-main">
          🧩 数据集筛选
        </div>
        <div class="title-sub">
          按数据来源、模态类型或关键字快速查找平台公开数据集
        </div>
      </div>
      <el-radio-group
        v-model="marketFilter.type"
        @change="fetchDatasets"
      >
        <el-radio-button value="all">
          📦 全部
        </el-radio-button>
        <el-radio-button value="official">
          ⭐ 官方
        </el-radio-button>
        <el-radio-button value="community">
          👥 社区
        </el-radio-button>
      </el-radio-group>
      <div class="search-row">
        <el-input
          v-model="marketFilter.keyword"
          placeholder="🔍 搜索数据集名称、描述..."
          clearable
          class="search-input"
          @input="onSearch"
        />
        <el-select
          v-model="marketFilter.modality"
          placeholder="全部模态"
          clearable
          @change="fetchDatasets"
        >
          <el-option label="可见光" value="visible"/>
          <el-option label="红外" value="infrared"/>
          <el-option label="毫米波" value="mmwave"/>
          <el-option label="激光雷达" value="lidar"/>
        </el-select>
      </div>
    </div>

    <!-- 数据集列表 -->
    <div class="section-header">
      <div>
        <h2>数据集列表</h2>
        <p>共找到 {{ datasets.length }} 个公开数据集</p>
      </div>
    </div>

    <div
      class="card-grid"
      v-if="datasets.length > 0"
    >
      <DatasetCard
        v-for="ds in datasets"
        :key="ds.dataset_id"
        :dataset="ds"
        @click="goDetail(ds)"
        @preview="openPreview(ds)"
        @download="onDownload(ds)"
      />
    </div>

    <div
      v-else
      class="empty"
    >
      暂无公开数据集
    </div>

    <PreviewDialog v-model="previewVisible" :dataset="previewDataset" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import DatasetCard from '@/components/common/DatasetCard.vue'
import PreviewDialog from '@/components/common/PreviewDialog.vue'
import { getDatasetList } from '@/api/dataset'
import { ElMessage } from 'element-plus'

const router = useRouter()
const datasets = ref([])
const previewVisible = ref(false)
const previewDataset = ref(null)
const modalityCount = ref(0)

const marketFilter = reactive({ type: 'all', keyword: '', modality: '' })

let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(fetchDatasets, 400)
}

async function fetchDatasets() {
  const params = { visibility: 'public' }
  if (marketFilter.keyword) params.keyword = marketFilter.keyword
  if (marketFilter.modality) params.modality = marketFilter.modality
  try {
    const { data } = await getDatasetList(params)
    let items = data.items || data.datasets || []
    // 过滤掉已归档/删除的数据集
    items = items.filter(d => d.archive_status !== 'archived' && d.status !== 'archived')
    if (marketFilter.type === 'official') items = items.filter(d => d.is_official)
    if (marketFilter.type === 'community') items = items.filter(d => !d.is_official)
    datasets.value = items
    // 统计模态种类
    const mods = new Set(items.map(d => d.modality).filter(Boolean))
    modalityCount.value = mods.size || 4
  } catch { datasets.value = [] }
}

function goDetail(ds) { router.push({ name: 'DatasetDetail', params: { id: ds.dataset_id } }) }
function openPreview(ds) { previewDataset.value = ds; previewVisible.value = true }
function onDownload() { ElMessage.info('下载功能将在后端就绪后开放') }

onMounted(fetchDatasets)
</script>

<style scoped>
.market-page{
  padding:28px;
  max-width:1450px;
  margin:0 auto;
  background:#f8fafc;
  min-height:100vh;
}

.filter-panel{
  background:#fff;
  padding:26px;
  border-radius:18px;
  border:1px solid #e2e8f0;
  box-shadow:0 8px 22px rgba(15,23,42,.05);
  margin-bottom:32px;
}
.filter-title{
  padding-bottom:16px;
  border-bottom:1px solid #eef2f7;
  margin-bottom:22px;
}

.title-main{
  display:flex;
  align-items:center;
  gap:8px;
  font-size:18px;
  font-weight:700;
  color:#1e293b;
}

.title-sub{
  margin-top:8px;
  font-size:13px;
  color:#94a3b8;
  line-height:1.6;
}
.search-row{
  display:flex;
  gap:18px;
  margin-top:22px;
  align-items:center;
}
.search-input{flex:1;}
.search-row .el-select{width:220px;}

.market-hero{
  padding:45px 50px;
  margin-bottom:28px;
  border-radius:18px;
  color:white;
  background: linear-gradient(135deg, #0f172a, #1e3a8a);
  box-shadow: 0 10px 30px rgba(30,64,175,.18);
}

.market-hero h1{
  font-size:34px;
  margin-bottom:10px;
  font-weight:700;
}

.market-hero p{
  font-size:16px;
  opacity:.92;
  line-height:1.8;
  max-width:700px;
}
.card-grid{
  display:grid;
  grid-template-columns:
  repeat(auto-fill,minmax(320px,1fr));
  gap:24px;
}
.empty{
  padding:90px;
  text-align:center;
  background:white;
  border-radius:18px;
  border:1px dashed #cbd5e1;
  color:#94a3b8;
  font-size:16px;
}

.market-stats{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:20px;
  margin-bottom:36px;
}

.stat{
  background:#fff;
  padding:26px;
  border-radius:18px;
  text-align:center;
  border:1px solid #e2e8f0;
  box-shadow:
    0 8px 22px rgba(15,23,42,.05);
  transition:all .3s ease;
  cursor:pointer;
}

.stat:hover{
  transform:translateY(-6px);
  box-shadow:
    0 14px 32px rgba(37,99,235,.15);
  border-color:#93c5fd;
}
.stat h2{
  font-size:36px;
  font-weight:700;
  color:#2563eb;
  margin-bottom:10px;
}
.stat span{
  font-size:14px;
  color:#64748b;
  letter-spacing:.5px;
}

.section-header{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:22px;
}

.section-header h2{
  margin:0;
  font-size:24px;
  font-weight:700;
  color:#1e293b;
}

.section-header p{
  margin-top:6px;
  color:#64748b;
  font-size:14px;
}

:deep(.el-radio-button__inner){
  padding:10px 22px;
  font-size:14px;
  font-weight:600;
  border-radius:10px;
}
:deep(.el-radio-button:first-child .el-radio-button__inner){border-radius:10px 0 0 10px;}
:deep(.el-radio-button:last-child .el-radio-button__inner){border-radius:0 10px 10px 0;}
/* 选中后的颜色 */
:deep(.el-radio-button__original-radio:checked + .el-radio-button__inner){
  background:#2563eb;
  border-color:#2563eb;
  color:#fff;
  box-shadow:none;
}

/* 未选中 */
:deep(.el-radio-button__inner){
  background:#f8fafc;
  border-color:#dbe3ef;
  color:#475569;
  transition:all .25s;
}

/* 鼠标悬停 */
:deep(.el-radio-button__inner:hover){
  color:#2563eb;
  background:#eff6ff;
}
:deep(.el-input__wrapper){height:44px;}
:deep(.el-select__wrapper){height:44px;}
</style>
