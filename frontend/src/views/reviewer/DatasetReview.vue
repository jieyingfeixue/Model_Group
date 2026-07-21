<template>
  <div class="page">
    <h2>数据集审核</h2>
    <div class="card" v-loading="loading">
      <el-table :data="items">
        <el-table-column prop="name" label="数据集" />
        <el-table-column prop="owner_id" label="提交者 ID" width="100" />
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="review_status" label="审核状态" width="120" />
        <el-table-column prop="status" label="数据集状态" width="120" />
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button size="small" @click="onClaim(row)" v-if="row.review_status==='submitted'">认领</el-button>
            <el-button size="small" @click="onOpenChecklist(row)">检查清单</el-button>
            <el-button size="small" type="success" @click="onReview(row,'approved')">通过</el-button>
            <el-button size="small" type="danger" @click="onReview(row,'rejected')">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="detailVisible" title="系统检查清单" width="720px">
      <el-table :data="checklistItems" v-loading="checklistLoading">
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column prop="name" label="检查项" />
        <el-table-column prop="result" label="结果" width="120" />
        <el-table-column prop="detail" label="说明" />
      </el-table>
      <template #footer>
        <el-button @click="detailVisible=false">关闭</el-button>
        <el-button type="success" @click="onReview(current,'approved')">通过</el-button>
        <el-button type="danger" @click="onReview(current,'rejected')">驳回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getPendingDatasets,
  claimDatasetReview,
  getChecklist,
  reviewDataset,
} from '@/api/review'

const items = ref([])
const loading = ref(false)
const detailVisible = ref(false)
const checklistLoading = ref(false)
const checklistItems = ref([])
const current = ref(null)

async function fetchList() {
  loading.value = true
  try {
    const { data } = await getPendingDatasets({ page: 1, size: 50 })
    items.value = data.items || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载待审列表失败（需 reviewer/admin）')
  } finally {
    loading.value = false
  }
}

async function onClaim(row) {
  try {
    await claimDatasetReview(row.dataset_id)
    ElMessage.success('已认领')
    await fetchList()
    await onOpenChecklist(row)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '认领失败')
  }
}

async function onOpenChecklist(row) {
  current.value = row
  detailVisible.value = true
  checklistLoading.value = true
  try {
    const { data } = await getChecklist(row.dataset_id)
    const list = data.items || data.checklist || data.results || []
    checklistItems.value = Array.isArray(list)
      ? list.map((x, i) => ({
          id: x.id || x.code || `C${i + 1}`,
          name: x.name || x.title || x.check_item || JSON.stringify(x),
          result: x.result || x.status || '-',
          detail: x.detail || x.message || x.note || '',
        }))
      : Object.entries(data).map(([k, v]) => ({
          id: k,
          name: k,
          result: typeof v === 'object' ? (v.result || '-') : String(v),
          detail: typeof v === 'object' ? JSON.stringify(v) : '',
        }))
  } catch (e) {
    checklistItems.value = []
    ElMessage.error(e?.response?.data?.detail || '获取检查清单失败')
  } finally {
    checklistLoading.value = false
  }
}

async function onReview(row, result) {
  if (!row) return
  try {
    if (result === 'rejected') {
      const { value } = await ElMessageBox.prompt('请输入驳回备注', '驳回', {
        inputPlaceholder: 'notes',
      })
      await reviewDataset(row.dataset_id, { result, notes: value })
    } else {
      await reviewDataset(row.dataset_id, { result })
    }
    ElMessage.success(result === 'approved' ? '已通过' : '已驳回')
    detailVisible.value = false
    await fetchList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '裁决失败')
  }
}

onMounted(fetchList)
</script>

<style scoped>
.page{padding:24px;max-width:1200px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
</style>
