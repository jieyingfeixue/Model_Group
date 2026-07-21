<template>
  <div class="page" v-loading="loading">
    <h2>模型详情</h2>
    <div class="card" v-if="model">
      <h3>基本信息</h3>
      <table class="kv">
        <tr><td>名称</td><td>{{ model.name }}</td></tr>
        <tr><td>框架</td><td>{{ model.framework }}</td></tr>
        <tr><td>状态</td><td>{{ model.status }}</td></tr>
        <tr><td>输入</td><td>{{ inputSize }}</td></tr>
        <tr><td>模态</td><td>{{ (meta.modalities || []).join(', ') || '-' }}</td></tr>
        <tr><td>类别</td><td>{{ (meta.categories || []).join(', ') || '-' }}</td></tr>
        <tr><td>公开</td><td>{{ model.is_public ? '是' : '否' }}</td></tr>
        <tr><td>创建时间</td><td>{{ formatDate(model.created_at) }}</td></tr>
      </table>
    </div>
    <div class="card">
      <h3>版本历史</h3>
      <el-empty v-if="!versions.length" description="暂无版本" />
      <el-timeline v-else>
        <el-timeline-item
          v-for="v in versions"
          :key="v.version_id"
          :timestamp="formatDate(v.created_at)"
        >
          {{ v.version_number }} — {{ v.change_note || '无说明' }}
        </el-timeline-item>
      </el-timeline>
    </div>
    <el-button type="success" @click="goTrain">训练</el-button>
    <el-button type="warning" style="margin-left:12px" @click="goInfer">推理</el-button>
    <el-button type="danger" style="margin-left:12px" @click="goEval">评测</el-button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getModelDetail } from '@/api/model'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const model = ref(null)

const versions = computed(() => model.value?.versions || [])
const meta = computed(() => model.value?.meta_info || {})
const inputSize = computed(() => {
  const s = meta.value.input_size
  if (Array.isArray(s) && s.length >= 2) return `${s[0]}x${s[1]}`
  return '-'
})

function formatDate(v) {
  if (!v) return '-'
  return String(v).replace('T', ' ').slice(0, 19)
}

async function load() {
  loading.value = true
  try {
    const { data } = await getModelDetail(route.params.id)
    model.value = data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载模型详情失败')
  } finally {
    loading.value = false
  }
}

function goTrain() {
  router.push({ path: '/train', query: { model_id: route.params.id } })
}
function goInfer() {
  router.push({ path: '/infer/0', query: { model_id: route.params.id } })
}
function goEval() {
  router.push({ path: '/eval', query: { model_id: route.params.id } })
}

watch(() => route.params.id, load)
onMounted(load)
</script>

<style scoped>
.page{padding:24px;max-width:800px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.kv td{padding:6px 12px 6px 0;font-size:14px}
.kv td:first-child{color:#6b7280;width:100px}
</style>
