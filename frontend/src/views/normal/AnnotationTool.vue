<template>
  <div class="page">
    <h2>标注工具</h2>
    <div class="card">
      <el-form inline>
        <el-form-item label="标注任务">
          <el-select v-model="taskId" style="width:280px" filterable placeholder="选择任务" @change="onTaskChange">
            <el-option
              v-for="t in tasks"
              :key="t.task_id"
              :label="`${t.name || '任务'} (#${t.task_id})`"
              :value="t.task_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!taskId" :loading="loading" @click="loadNext">下一张</el-button>
          <el-button :disabled="!current" @click="onSave">保存</el-button>
          <el-button type="success" :disabled="!current" @click="onSubmit">提交</el-button>
        </el-form-item>
      </el-form>
      <p v-if="progressText" class="hint">{{ progressText }}</p>
    </div>

    <div class="card" v-if="current" v-loading="loading">
      <div class="preview">
        <img :src="current.image_url || current.thumbnail_url" alt="annotate" />
      </div>
      <p>资源 #{{ current.resource_id }} — {{ current.name }}</p>
      <el-input
        v-model="bboxesJson"
        type="textarea"
        :rows="10"
        placeholder='bboxes JSON，例如 [{"category_id":"cat_001","bbox":[0.1,0.2,0.3,0.4]}]'
      />
      <div style="margin-top:8px">
        <el-button size="small" @click="loadHistory">查看历史</el-button>
        <el-button size="small" @click="onRollback" :disabled="!historyVersion">回滚到版本</el-button>
        <el-input-number v-model="historyVersion" :min="1" size="small" style="margin-left:8px" />
      </div>
      <pre v-if="history" class="raw">{{ JSON.stringify(history, null, 2) }}</pre>
    </div>
    <el-empty v-else description="选择任务后加载图片开始标注（完整 Canvas 可后续增强）" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getMyTasks,
  getTaskProgress,
  getNextImage,
  saveAnnotation,
  submitAnnotation,
  getAnnotationHistory,
  rollbackAnnotation,
} from '@/api/annotation'

const route = useRoute()
const tasks = ref([])
const taskId = ref(null)
const current = ref(null)
const bboxesJson = ref('[]')
const loading = ref(false)
const progressText = ref('')
const history = ref(null)
const historyVersion = ref(1)

async function loadTasks() {
  try {
    const { data } = await getMyTasks()
    tasks.value = data.items || []
    const q = Number(route.params.taskId)
    if (q) taskId.value = q
    else if (tasks.value.length) taskId.value = tasks.value[0].task_id
    if (taskId.value) await onTaskChange()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载任务失败')
  }
}

async function onTaskChange() {
  if (!taskId.value) return
  try {
    const { data } = await getTaskProgress(taskId.value)
    progressText.value = `进度 annotated ${data.annotated}/${data.total}，approved ${data.approved}`
  } catch {
    progressText.value = ''
  }
  await loadNext()
}

async function loadNext() {
  if (!taskId.value) return
  loading.value = true
  history.value = null
  try {
    const { data } = await getNextImage(taskId.value)
    current.value = data
    bboxesJson.value = JSON.stringify(data.annotation?.bboxes || [], null, 2)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载下一张失败')
  } finally {
    loading.value = false
  }
}

async function onSave() {
  try {
    const bboxes = JSON.parse(bboxesJson.value || '[]')
    await saveAnnotation(current.value.resource_id, { bboxes }, taskId.value)
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存失败')
  }
}

async function onSubmit() {
  try {
    await onSave()
    await submitAnnotation(current.value.resource_id, taskId.value)
    ElMessage.success('已提交')
    await loadNext()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  }
}

async function loadHistory() {
  try {
    const { data } = await getAnnotationHistory(current.value.resource_id, taskId.value)
    history.value = data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '历史加载失败')
  }
}

async function onRollback() {
  try {
    await rollbackAnnotation(current.value.resource_id, historyVersion.value, taskId.value)
    ElMessage.success('已回滚并另存新版本')
    await loadNext()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '回滚失败')
  }
}

onMounted(loadTasks)
</script>

<style scoped>
.page{padding:24px;max-width:1000px;margin:0 auto}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.hint{color:#64748b;font-size:13px}
.preview{background:#f1f5f9;min-height:240px;display:flex;align-items:center;justify-content:center;margin-bottom:12px;border-radius:8px;overflow:hidden}
.preview img{max-width:100%;max-height:420px}
.raw{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;font-size:12px;overflow:auto;max-height:240px;margin-top:12px}
</style>
