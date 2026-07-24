<template>
<div class="page">
  <!-- Hero -->
  <div class="hero">
    <div>
      <h1>📚 我的数据集</h1>
      <p>
        管理个人创建的数据集，
        支持冻结、发布、归档及版本管理。
      </p>
    </div>

  </div>
  <!-- 统计 -->
  <div class="stats">
    <div class="stat-card">
      <div class="icon">📦</div>
      <h2>{{ datasets.length }}</h2>
      <span>数据集总数</span>
    </div>
    <div class="stat-card">
      <div class="icon">🚀</div>
      <h2>{{ datasets.filter(d=>d.status==='published').length }}</h2>
      <span>已发布</span>
    </div>

    <div class="stat-card">
      <div class="icon">📝</div>
      <h2>{{ datasets.filter(d=>d.status==='draft').length }}</h2>
      <span>草稿</span>
    </div>
  </div>

  <div class="toolbar">
      <div class="left">
          <el-button
              type="primary"
              size="large"
              @click="$router.push({path:'/datasets/build', query:{fresh:'1'}})"
          >
              + 构建数据集
          </el-button>
      </div>

      <div class="right">
          <el-select
              v-model="filter.status"
              placeholder="状态筛选"
              clearable
              style="width:160px"
          >
              <el-option label="全部" value=""/>
          </el-select>
      </div>
  </div>

  <div class="table-card">
    <el-table :data="datasets" style="margin-top:12px;">
      <el-table-column prop="name" label="数据集名称" />
      <el-table-column prop="sample_count" label="样本数" width="100" header-align="center" align="center" />
      <el-table-column prop="annotation_progress" label="标注状态" width="110" header-align="center" align="center">
        <template #default="{row}">
          <el-tag v-if="row.annotated_count === row.sample_count" type="success" round effect="light" size="small">已完成标注</el-tag>
          <el-tag v-else type="warning" round effect="light" size="small">未完成标注</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="visibility" label="可见范围" width="100" header-align="center" align="center" />
      <el-table-column prop="created_at" label="创建时间" width="120" header-align="center" align="center" />
      <el-table-column label="操作" width="320" header-align="center" align="center">
        <template #default="{ row }">

          <el-button size="small" plain @click="$router.push('/datasets/' + row.dataset_id)">详情</el-button>

          <!-- 标注（未完成标注时显示） -->
          <el-button
            v-if="row.annotated_count < row.sample_count"
            size="small" type="primary" round @click="$router.push('/annotate/' + row.dataset_id)"
          >标注</el-button>

          <!-- 提交公开申请（未提交或被驳回时显示） -->
          <el-tooltip content="提交后将同时进入数据集审核和标注审核，两者均通过后自动发布到数据集市场" placement="top">
          <el-button
            v-if="row.review_status === 'not_submitted' || row.review_status === 'rejected'"
            size="small" type="warning" round @click="onSubmitReview(row)"
          >提交公开申请</el-button>
          </el-tooltip>

          <!-- 删除 -->
          <el-button size="small" type="danger" plain round @click="onDelete(row)">删除</el-button>

        </template>
      </el-table-column>
    </el-table>
  </div>
  <el-empty v-if="datasets.length===0" description="暂无数据集，点击上方构建第一个数据集" />
</div>
</template>

<script setup>
import { ref, reactive, onMounted, onActivated, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getDatasetList, deleteDataset, submitForReview } from '@/api/dataset'

const filter = reactive({ status: '' })
const datasets = ref([])
const loading = ref(false)

async function fetchDatasets() {
  loading.value = true
  try {
    const params = {}
    if (filter.status) params.status = filter.status
    const { data } = await getDatasetList(params)
    datasets.value = (data.items || []).filter(d => d.archive_status !== 'archived')
  } catch {
    ElMessage.error('加载数据集列表失败')
  } finally {
    loading.value = false
  }
}

async function onSubmitReview(row){
  try {
    await submitForReview(row.dataset_id)
    row.review_status = 'submitted'
    ElMessage.success('已提交公开申请，等待审核员审批')
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '提交失败') }
}

async function onDelete(row){
  try {
    await ElMessageBox.confirm(
      `确定删除数据集「${row.name}」？删除后不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await deleteDataset(row.dataset_id)
    datasets.value = datasets.value.filter(d => d.dataset_id !== row.dataset_id)
    ElMessage.success('已删除')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

onMounted(fetchDatasets)
onActivated(fetchDatasets)
watch(() => filter.status, fetchDatasets)
</script>

<style scoped>
.page{
  padding:28px;
  max-width:1450px;
  margin:auto;
  background:#f8fafc;
  min-height:100vh;
}
.toolbar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:24px;
}
h2{ margin-bottom:16px; }
.hero{
  padding:45px 50px;
  margin-bottom:28px;
  border-radius:18px;
  color:white;
  background: linear-gradient(135deg, #0f172a, #1e3a8a);
  box-shadow: 0 10px 30px rgba(30,64,175,.18);
}

.hero h1{
  font-size:34px;
  margin-bottom:10px;
}

.hero p{
  font-size:16px;
  opacity:.92;
  line-height:1.8;
}
.stats{
  display:grid;
  grid-template-columns:
  repeat(3,1fr);
  gap:22px;
  margin-bottom:30px;
}

.stat-card{
  background:white;
  border-radius:18px;
  padding:28px;
  text-align:center;
  box-shadow:
  0 8px 22px rgba(15,23,42,.05);
  transition:.3s;
}

.stat-card:hover{transform:translateY(-6px);}

.icon{
  font-size:30px;
  margin-bottom:12px;
}

.stat-card h2{
  font-size:34px;
  color:#2563eb;
  margin-bottom:8px;
}

.stat-card span{color:#64748b;}

.table-card{
  background:white;
  padding:20px;
  border-radius:20px;
  box-shadow:
  0 8px 24px rgba(15,23,42,.06);
}
</style>
