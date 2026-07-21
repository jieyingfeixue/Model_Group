<template>
  <div class="page">
    <h2>模型推理</h2>

    <div class="card">
      <h3>提交推理</h3>
      <el-form label-position="top" style="max-width:520px" v-loading="loadingModels">
        <el-form-item label="模型">
          <el-select v-model="form.model_id" style="width:100%" filterable>
            <el-option
              v-for="m in models"
              :key="m.model_id"
              :label="`${m.name} (#${m.model_id})`"
              :value="m.model_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模式">
          <el-radio-group v-model="mode">
            <el-radio-button value="image">单图 image_id</el-radio-button>
            <el-radio-button value="dataset">数据集 dataset_id</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="mode === 'image'" label="图片资源 ID">
          <el-input-number v-model="form.image_id" :min="1" style="width:100%" />
        </el-form-item>
        <el-form-item v-else label="数据集 ID">
          <el-input-number v-model="form.dataset_id" :min="1" style="width:100%" />
        </el-form-item>
        <el-button type="primary" :loading="submitting" @click="onSubmit">提交推理</el-button>
      </el-form>
    </div>

    <div class="card" v-if="task">
      <h3>任务 #{{ task.task_id }}</h3>
      <el-tag>{{ task.status }}</el-tag>
      <el-button size="small" style="margin-left:12px" @click="refresh">刷新结果</el-button>
      <div v-if="task.results" class="result-box">
        <pre>{{ JSON.stringify(task.results, null, 2) }}</pre>
      </div>
      <div v-if="vizUrl" style="margin-top:16px">
        <h4>可视化</h4>
        <img :src="vizUrl" alt="visualize" class="viz" @error="vizBroken = true" />
        <p v-if="vizBroken" class="hint">可视化图加载失败（任务未完成或无对应 image_id）</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getMyModels,
  submitInfer,
  getInferResults,
  getInferVisualizeUrl,
} from '@/api/model'

const route = useRoute()
const models = ref([])
const loadingModels = ref(false)
const submitting = ref(false)
const mode = ref('image')
const task = ref(null)
const vizBroken = ref(false)
let pollTimer = null

const form = reactive({
  model_id: null,
  image_id: 1,
  dataset_id: 1,
})

const vizUrl = computed(() => {
  if (!task.value?.task_id || mode.value !== 'image' || !form.image_id) return ''
  if (task.value.status !== 'completed') return ''
  return getInferVisualizeUrl(task.value.task_id, form.image_id)
})

async function loadModels() {
  loadingModels.value = true
  try {
    const { data } = await getMyModels({ page: 1, size: 100 })
    models.value = data.items || []
    const qid = Number(route.query.model_id)
    if (qid) form.model_id = qid
    else if (models.value.length) form.model_id = models.value[0].model_id
    const tid = Number(route.params.taskId)
    if (tid > 0) {
      task.value = { task_id: tid, status: 'unknown' }
      await refresh()
      pollTimer = setInterval(refresh, 2500)
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loadingModels.value = false
  }
}

async function refresh() {
  if (!task.value?.task_id) return
  try {
    const { data } = await getInferResults(task.value.task_id, { coord: 'both' })
    task.value = data
    vizBroken.value = false
    if (['completed', 'failed'].includes(data.status)) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '刷新失败')
  }
}

async function onSubmit() {
  if (!form.model_id) {
    ElMessage.warning('请选择模型')
    return
  }
  const body = { model_id: form.model_id }
  if (mode.value === 'image') {
    if (!form.image_id) {
      ElMessage.warning('请填写 image_id')
      return
    }
    body.image_id = form.image_id
  } else {
    if (!form.dataset_id) {
      ElMessage.warning('请填写 dataset_id')
      return
    }
    body.dataset_id = form.dataset_id
  }
  submitting.value = true
  try {
    const { data } = await submitInfer(body)
    task.value = data
    ElMessage.success(`推理任务已提交 #${data.task_id}`)
    clearInterval(pollTimer)
    pollTimer = setInterval(refresh, 2500)
    await refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

onMounted(loadModels)
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.page{padding:24px;max-width:900px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
h3{margin-bottom:12px}
.result-box{
  margin-top:12px;max-height:360px;overflow:auto;background:#0f172a;color:#e2e8f0;
  border-radius:8px;padding:12px
}
.result-box pre{margin:0;font-size:12px;white-space:pre-wrap}
.viz{max-width:100%;border-radius:8px;border:1px solid #e2e8f0}
.hint{font-size:12px;color:#94a3b8}
</style>
