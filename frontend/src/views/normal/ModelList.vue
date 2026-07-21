<template>
<div class="page">
  <!-- Hero -->
  <div class="hero">
      <div>
          <h1>🧠 我的模型</h1>
          <p>
              管理个人上传的模型，
              支持训练、推理、算法评测及版本维护。
          </p>
      </div>
  </div>

  <div class="stats">
    <div class="stat-card">
        <div class="icon">🧠</div>
        <h2>{{ filteredModels.length }}</h2>
        <span>模型总数</span>
    </div>

    <div class="stat-card">
        <div class="icon">🚀</div>
        <h2>{{ filteredModels.filter(m=>m.status==='available').length }}</h2>
        <span>可用模型</span>
    </div>

    <div class="stat-card">
        <div class="icon">⚡</div>
        <h2>{{ filteredModels.filter(m=>m.framework==='pytorch').length }}</h2>
        <span>PyTorch模型</span>
    </div>
  </div>

  <div class="toolbar">
    <div class="toolbar-left">
        <el-button
            type="primary"
            size="large"
            @click="uploadVisible=true"
        >
            + 上传模型
        </el-button>
    </div>

    <div class="toolbar-right">
        <el-select
            v-model="filter"
            placeholder="框架筛选"
            clearable
            style="width:180px"
        >
            <el-option label="全部" value=""/>
            <el-option label="PyTorch" value="pytorch"/>
            <el-option label="ONNX" value="onnx"/>
        </el-select>
    </div>
  </div>

  <div class="table-card" v-loading="loading">
    <el-table :data="filteredModels" stripe>
      <el-table-column prop="name" label="模型名称" min-width="260" header-align="left" align="left"/><el-table-column prop="framework" label="框架" width="120" header-align="center" align="center"/>
      <el-table-column prop="status" label="状态" width="120" header-align="center" align="center"><template #default="{row}"><el-tag
        :type="row.status==='available'?'success':'info'"
        round
        effect="light"
        >
        {{row.status}}
        </el-tag></template></el-table-column>
      <el-table-column label="操作" width="320" header-align="center" align="center"><template #default="{row}">
        <el-button plain size="small" @click="goDetail(row)">详情</el-button>
        <el-button type="success" size="small" plain @click="goTrain(row)">训练</el-button>
        <el-button type="warning" size="small" plain @click="goInfer(row)">推理</el-button>
        <el-button type="danger" size="small" plain @click="goEval(row)">评测</el-button>
      </template></el-table-column>
    </el-table>
  </div>

  <el-dialog v-model="uploadVisible" title="上传模型" width="620px">
    <el-form :model="uploadForm" label-position="top">
      <el-form-item label="模型名称"><el-input v-model="uploadForm.name" /></el-form-item>
      <el-form-item label="框架"><el-select v-model="uploadForm.framework"><el-option label="PyTorch" value="pytorch" /><el-option label="ONNX" value="onnx" /></el-select></el-form-item>
      <el-form-item label="模态 modalities"><el-input v-model="uploadForm.modalities" placeholder="visible 或 visible,infrared" /></el-form-item>
      <el-form-item label="类别 categories"><el-input v-model="uploadForm.categories" placeholder="pole,bridge" /></el-form-item>
      <el-form-item label="输入尺寸"><el-input v-model="uploadForm.inputSize" placeholder="640x640" /></el-form-item>
      <el-form-item label="模型文件">
        <input type="file" accept=".pt,.pth,.onnx" @change="onPickFile" />
        <div v-if="fileRef" style="margin-top:8px;color:#64748b;font-size:13px">{{ fileRef.name }}</div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="uploadVisible=false">取消</el-button>
      <el-button type="primary" :loading="uploading" @click="onSubmit">确认上传</el-button>
    </template>
  </el-dialog>
</div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMyModels, registerModel } from '@/api/model'

const router = useRouter()
const filter = ref('')
const loading = ref(false)
const uploadVisible = ref(false)
const uploading = ref(false)
const uploadForm = reactive({
  name: '',
  framework: 'onnx',
  modalities: 'visible',
  categories: 'pole,bridge',
  inputSize: '640x640',
})
const fileRef = ref(null)
const models = ref([])
const total = ref(0)

const filteredModels = computed(() => {
  if (!filter.value) return models.value
  return models.value.filter((m) => m.framework === filter.value)
})

async function fetchModels() {
  loading.value = true
  try {
    const params = { page: 1, size: 100 }
    if (filter.value) params.framework = filter.value
    const { data } = await getMyModels(params)
    models.value = data.items || []
    total.value = data.total ?? models.value.length
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载模型列表失败')
  } finally {
    loading.value = false
  }
}

function onPickFile(e) {
  fileRef.value = e.target.files?.[0] || null
}

async function onSubmit() {
  if (!uploadForm.name.trim()) {
    ElMessage.warning('请填写模型名称')
    return
  }
  if (!fileRef.value) {
    ElMessage.warning('请选择权重文件')
    return
  }
  const sizeParts = String(uploadForm.inputSize).toLowerCase().split(/[x×]/)
  const h = parseInt(sizeParts[0], 10) || 640
  const w = parseInt(sizeParts[1], 10) || h
  const metadata = {
    input_size: [h, w],
    modalities: String(uploadForm.modalities || 'visible')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
    categories: String(uploadForm.categories || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  }
  const fd = new FormData()
  fd.append('file', fileRef.value)
  fd.append('name', uploadForm.name.trim())
  fd.append('framework', uploadForm.framework)
  fd.append('metadata', JSON.stringify(metadata))
  uploading.value = true
  try {
    await registerModel(fd)
    ElMessage.success('模型注册成功')
    uploadVisible.value = false
    fileRef.value = null
    await fetchModels()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

function goDetail(row) {
  router.push(`/models/${row.model_id}`)
}
function goTrain(row) {
  router.push({ path: '/train', query: { model_id: row.model_id } })
}
function goInfer(row) {
  router.push({ path: '/infer/0', query: { model_id: row.model_id } })
}
function goEval(row) {
  router.push({ path: '/eval', query: { model_id: row.model_id } })
}

watch(filter, fetchModels)
onMounted(fetchModels)
</script>

<style scoped>
.page{
    padding:28px;
    max-width:1450px;
    margin:auto;
    background:#f8fafc;
    min-height:100vh;
}
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
  font-weight:700;
}

.hero p{
  font-size:16px;
  line-height:1.8;
  opacity:.9;
  max-width:650px;
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

.icon{
  font-size:30px;
  margin-bottom:12px;
}
.toolbar{ display:flex; align-items:center; }

.toolbar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:24px;
}

.toolbar-left{
  display:flex;
  align-items:center;
  gap:16px;
}

.toolbar-right{
  display:flex;
  gap:16px;
}

.table-card{
  background:white;
  padding:20px;
  border-radius:20px;
  box-shadow:
  0 8px 24px rgba(15,23,42,.06);
}

:deep(.el-dialog){
  border-radius:18px;
  overflow:hidden;
}

:deep(.el-dialog__header){
  background:#f8fafc;
  padding:20px 24px;
  font-weight:700;
}

:deep(.el-dialog__body){padding:24px;}

:deep(.table-header){
    text-align:center !important;
    font-weight:700;
    color:#334155;
}

</style>
