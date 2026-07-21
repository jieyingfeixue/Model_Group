<template>
  <div class="page">
    <h2>算力 / 训练审批</h2>
    <p class="hint">对接管理员训练审批接口。GPU 节点管理后端尚未实现。</p>
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
} from '@/api/admin'

const tasks = ref([])
const loading = ref(false)

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

onMounted(fetchList)
</script>

<style scoped>
.page{padding:24px;max-width:1100px;margin:0 auto}
.hint{color:#64748b;margin-bottom:16px}
.card{background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
h3{margin:0}
</style>
