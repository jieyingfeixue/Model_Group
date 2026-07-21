<template>
  <div class="page">
    <h2>算力 / 训练审批</h2>
    <div class="card" v-loading="loadingGpu">
      <div class="toolbar">
        <h3>GPU / 计算节点</h3>
        <el-button size="small" @click="loadGpu">刷新节点</el-button>
      </div>
      <el-table :data="gpuNodes" size="small">
        <el-table-column prop="node_id" label="节点" width="120" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="type" label="类型" width="80" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column prop="max_parallel" label="并行" width="80" />
        <el-table-column prop="executor" label="执行器" width="100" />
      </el-table>
    </div>

    <div class="card" v-loading="loading">
      <div class="toolbar">
        <h3>待审批训练任务</h3>
        <el-button @click="fetchList">刷新</el-button>
      </div>
      <el-table :data="tasks">
        <el-table-column prop="task_id" label="Task ID" width="90" />
        <el-table-column prop="model_id" label="模型" width="90" />
        <el-table-column prop="dataset_id" label="数据集" width="90" />
        <el-table-column prop="status" label="状态" width="140" />
        <el-table-column prop="created_by" label="申请人" width="90" />
        <el-table-column prop="created_at" label="创建时间" min-width="160">
          <template #default="{row}">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="onApprove(row)">通过</el-button>
            <el-button size="small" type="danger" @click="onReject(row)">拒绝</el-button>
            <el-button size="small" @click="onTerminate(row)">终止</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !tasks.length" description="暂无待审批任务" />
    </div>

    <div class="card" v-loading="loadingInfer">
      <div class="toolbar">
        <h3>推理任务（排队/失败可重试）</h3>
        <el-button size="small" @click="loadInfer">刷新</el-button>
      </div>
      <el-table :data="inferTasks" size="small">
        <el-table-column prop="task_id" label="ID" width="80" />
        <el-table-column prop="model_id" label="模型" width="80" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="image_id" label="image" width="90" />
        <el-table-column prop="dataset_id" label="dataset" width="90" />
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" type="primary" @click="onApproveInfer(row)">审批/重试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getPendingTrainTasks,
  approveTrain,
  rejectTrain,
  terminateTrain,
  getPendingInferTasks,
  approveInfer,
  getGpuNodes,
} from '@/api/admin'

const tasks = ref([])
const inferTasks = ref([])
const gpuNodes = ref([])
const loading = ref(false)
const loadingInfer = ref(false)
const loadingGpu = ref(false)

function formatDate(v){ return v ? String(v).replace('T',' ').slice(0,19) : '-' }

async function fetchList() {
  loading.value = true
  try {
    const { data } = await getPendingTrainTasks()
    tasks.value = Array.isArray(data) ? data : (data.items || [])
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败（需 admin）')
  } finally {
    loading.value = false
  }
}

async function loadInfer() {
  loadingInfer.value = true
  try {
    const { data } = await getPendingInferTasks()
    inferTasks.value = Array.isArray(data) ? data : (data.items || [])
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '推理列表加载失败')
  } finally {
    loadingInfer.value = false
  }
}

async function loadGpu() {
  loadingGpu.value = true
  try {
    const { data } = await getGpuNodes()
    gpuNodes.value = data.items || (Array.isArray(data) ? data : [])
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '节点加载失败')
  } finally {
    loadingGpu.value = false
  }
}

async function onApprove(row) {
  try {
    await approveTrain(row.task_id)
    ElMessage.success(`已通过并入队 #${row.task_id}`)
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '审批失败')
  }
}

async function onReject(row) {
  try {
    const { value } = await ElMessageBox.prompt('拒绝原因', '拒绝训练', {
      inputValidator: (v) => !!v || '必填',
    })
    await rejectTrain(row.task_id, { reason: value })
    ElMessage.success('已拒绝')
    await fetchList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '拒绝失败')
  }
}

async function onTerminate(row) {
  try {
    await terminateTrain(row.task_id)
    ElMessage.success('已终止')
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '终止失败')
  }
}

async function onApproveInfer(row) {
  try {
    await approveInfer(row.task_id)
    ElMessage.success('已入队/重试')
    await loadInfer()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

onMounted(() => {
  fetchList()
  loadInfer()
  loadGpu()
})
</script>

<style scoped>
.page{padding:24px;max-width:1100px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
h3{margin:0}
</style>
