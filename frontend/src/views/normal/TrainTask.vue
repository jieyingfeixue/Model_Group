<template>
  <div class="page">
    <h2>模型训练</h2>
    <div class="card">
      <h3>训练配置</h3>
      <el-form label-position="top" style="max-width:500px" v-loading="loadingModels">
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
        <el-form-item label="数据集">
          <el-select v-model="form.dataset_id" style="width:100%" filterable allow-create>
            <el-option
              v-for="d in datasets"
              :key="d.dataset_id"
              :label="`${d.name} (#${d.dataset_id})`"
              :value="d.dataset_id"
            />
          </el-select>
          <div class="hint">优先显示「我的数据集」；也可手动输入 dataset_id</div>
        </el-form-item>
        <el-form-item label="Epochs">
          <el-input-number v-model="form.epochs" :min="1" :max="500" />
        </el-form-item>
        <el-form-item label="Batch Size">
          <el-input-number v-model="form.batch_size" :min="1" :max="128" />
        </el-form-item>
        <el-form-item label="Learning Rate">
          <el-input v-model="form.lr" placeholder="0.001" />
        </el-form-item>
        <el-form-item label="GPU 规格">
          <el-select v-model="form.gpu" style="width:100%">
            <el-option label="A100-40G" value="a100" />
            <el-option label="V100-32G" value="v100" />
            <el-option label="CPU / Demo" value="cpu" />
          </el-select>
        </el-form-item>
        <el-button type="primary" :loading="submitting" @click="onSubmit">提交训练申请</el-button>
      </el-form>
    </div>

    <div class="card" v-if="task">
      <h3>任务状态</h3>
      <el-tag>{{ task.status }}</el-tag>
      <div style="margin-top:12px">
        <p>Task ID: {{ task.task_id }}</p>
        <p v-if="task.progress">进度: {{ formatProgress(task.progress) }}</p>
        <p v-if="task.error_log" style="color:#dc2626">错误: {{ task.error_log }}</p>
      </div>
      <el-button size="small" style="margin-top:8px" @click="refreshTask">刷新状态</el-button>
      <el-button
        size="small"
        type="danger"
        style="margin-top:8px;margin-left:8px"
        :disabled="!canStop"
        @click="onStop"
      >终止</el-button>
      <div v-if="logs.length" class="logs">
        <div v-for="(line, i) in logs" :key="i">{{ line }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMyModels, submitTrain, getTrainDetail, getTrainLogs, stopTrain } from '@/api/model'
import { getMyDatasets } from '@/api/dataset'

const route = useRoute()
const models = ref([])
const datasets = ref([])
const loadingModels = ref(false)
const submitting = ref(false)
const task = ref(null)
const logs = ref([])
let pollTimer = null

const form = reactive({
  model_id: null,
  dataset_id: 1,
  epochs: 10,
  batch_size: 8,
  lr: '0.001',
  gpu: 'cpu',
})

const canStop = computed(() => {
  const s = task.value?.status
  return s && !['completed', 'failed', 'stopped', 'rejected'].includes(s)
})

function formatProgress(p) {
  if (!p || typeof p !== 'object') return '-'
  const epoch = p.epoch ?? p.current_epoch
  const loss = p.loss
  const map = p.mAP ?? p.map
  const parts = []
  if (epoch != null) parts.push(`epoch ${epoch}`)
  if (loss != null) parts.push(`loss ${loss}`)
  if (map != null) parts.push(`mAP ${map}`)
  return parts.join(' | ') || JSON.stringify(p)
}

async function loadModels() {
  loadingModels.value = true
  try {
    const [{ data: modelData }, dsRes] = await Promise.all([
      getMyModels({ page: 1, size: 100 }),
      getMyDatasets({ page: 1, size: 100 }).catch(() => ({ data: { items: [] } })),
    ])
    models.value = modelData.items || []
    datasets.value = dsRes.data?.items || []
    const qid = Number(route.query.model_id)
    if (qid) form.model_id = qid
    else if (models.value.length && !form.model_id) form.model_id = models.value[0].model_id
    const qds = Number(route.query.dataset_id)
    if (qds) form.dataset_id = qds
    else if (datasets.value.length && !form.dataset_id) form.dataset_id = datasets.value[0].dataset_id
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载模型失败')
  } finally {
    loadingModels.value = false
  }
}

async function refreshTask() {
  if (!task.value?.task_id) return
  try {
    const [{ data: t }, { data: logData }] = await Promise.all([
      getTrainDetail(task.value.task_id),
      getTrainLogs(task.value.task_id).catch(() => ({ data: { lines: [] } })),
    ])
    task.value = t
    logs.value = logData.lines || []
    if (['completed', 'failed', 'stopped', 'rejected'].includes(t.status)) {
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
  if (!form.dataset_id) {
    ElMessage.warning('请填写数据集 ID')
    return
  }
  submitting.value = true
  try {
    const { data } = await submitTrain({
      model_id: form.model_id,
      dataset_id: form.dataset_id,
      config: {
        epochs: form.epochs,
        batch_size: form.batch_size,
        lr: parseFloat(form.lr) || 0.001,
      },
      gpu_config: { type: form.gpu },
    })
    task.value = data
    ElMessage.success(`训练申请已提交（#${data.task_id}），待管理员审批后才会真正跑`)
    clearInterval(pollTimer)
    pollTimer = setInterval(refreshTask, 3000)
    await refreshTask()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

async function onStop() {
  try {
    const { data } = await stopTrain(task.value.task_id)
    task.value = data
    ElMessage.success('已请求终止')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '终止失败')
  }
}

onMounted(loadModels)
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.page{padding:24px;max-width:800px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
h3{margin-bottom:12px}
.hint{font-size:12px;color:#94a3b8;margin-top:6px}
.logs{
  margin-top:12px;max-height:240px;overflow:auto;background:#0f172a;color:#e2e8f0;
  font-family:ui-monospace,monospace;font-size:12px;padding:12px;border-radius:8px;white-space:pre-wrap
}
</style>
