<template>
  <div class="page" v-loading="loading">
    <div class="back-bar">
      <el-button text @click="$router.back()">← 返回</el-button>
    </div>
    <h2>{{ detail?.name || '数据集详情' }}</h2>
    <div class="card" v-if="detail">
      <table class="kv">
        <tr><td>ID</td><td>{{ detail.dataset_id }}</td></tr>
        <tr><td>版本</td><td>{{ detail.version }}</td></tr>
        <tr><td>状态</td><td>{{ detail.status }}</td></tr>
        <tr><td>可见性</td><td>{{ detail.visibility }}</td></tr>
        <tr><td>审核</td><td>{{ detail.review_status }}</td></tr>
        <tr><td>描述</td><td>{{ detail.description || '-' }}</td></tr>
        <tr><td>样本统计</td><td>{{ subsetText }}</td></tr>
      </table>
      <div style="margin-top:16px">
        <el-button v-if="detail.status==='draft'" type="success" @click="onFreeze">冻结</el-button>
        <el-button v-if="detail.status==='frozen'" type="warning" @click="onPublish">发布公开</el-button>
        <el-button @click="onExport">导出 COCO</el-button>
        <el-button type="primary" @click="$router.push({ path:'/train', query:{ dataset_id: detail.dataset_id }})">去训练</el-button>
        <el-button type="danger" @click="$router.push({ path:'/eval', query:{ dataset_id: detail.dataset_id }})">去评测</el-button>
      </div>
    </div>
    <div class="card">
      <h3>版本历史</h3>
      <el-empty v-if="!versions.length" description="暂无版本记录" />
      <el-timeline v-else>
        <el-timeline-item v-for="v in versions" :key="v.version_id || v.version" :timestamp="formatDate(v.created_at)">
          {{ v.version }} — {{ v.change_log || '无说明' }}（样本 {{ v.sample_count ?? '-' }}）
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getDatasetDetail,
  getDatasetVersions,
  freezeDataset,
  publishDataset,
  exportDataset,
} from '@/api/dataset'

const route = useRoute()
const loading = ref(false)
const detail = ref(null)
const versions = ref([])

const subsetText = computed(() => {
  const c = detail.value?.subset_counts || detail.value?.counts
  if (!c) return detail.value?.sample_count ?? '-'
  return `train ${c.train || 0} / val ${c.val || 0} / test ${c.test || 0}`
})

function formatDate(v){ return v ? String(v).replace('T',' ').slice(0,19) : '-' }

async function load() {
  const id = route.params.id
  if (!id) return
  loading.value = true
  try {
    const [{ data: d }, ver] = await Promise.all([
      getDatasetDetail(id),
      getDatasetVersions(id).catch(() => ({ data: [] })),
    ])
    detail.value = d
    versions.value = Array.isArray(ver.data) ? ver.data : (ver.data?.items || [])
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function onFreeze() {
  try {
    await freezeDataset(detail.value.dataset_id)
    ElMessage.success('已冻结')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '冻结失败')
  }
}

async function onPublish() {
  try {
    await publishDataset(detail.value.dataset_id, { visibility: 'public' })
    ElMessage.success('已发布')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '发布失败')
  }
}

async function onExport() {
  try {
    const { data } = await exportDataset(detail.value.dataset_id, { format: 'coco' })
    const blob = data instanceof Blob ? data : new Blob([JSON.stringify(data)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `dataset_${detail.value.dataset_id}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '导出失败')
  }
}

watch(() => route.params.id, load)
onMounted(load)
</script>

<style scoped>
.page{padding:24px;max-width:900px;margin:0 auto}
.back-bar{margin-bottom:8px}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.kv td{padding:6px 12px 6px 0;font-size:14px}
.kv td:first-child{color:#6b7280;width:100px}
h3{margin-bottom:12px}
</style>
