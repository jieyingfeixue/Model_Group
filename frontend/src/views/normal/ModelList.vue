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
        <h2>{{ models.length }}</h2>
        <span>模型总数</span>
    </div>

    <div class="stat-card">
        <div class="icon">🚀</div>
        <h2>{{ models.filter(m=>m.status==='available').length }}</h2>
        <span>可用模型</span>
    </div>

    <div class="stat-card">
        <div class="icon">⚡</div>
        <h2>{{ models.filter(m=>m.framework==='pytorch').length }}</h2>
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

  <div class="table-card">
    <el-table :data="models" stripe>
      <el-table-column prop="name" label="模型名称" min-width="260" header-align="left" align="left"/><el-table-column prop="framework" label="框架" width="120" header-align="center" align="center"/>
      <el-table-column prop="status" label="状态" width="120" header-align="center" align="center"><template #default="{row}"><el-tag
        :type="row.status==='available'?'success':'info'"
        round
        effect="light"
        >
        {{row.status}}
        </el-tag></template></el-table-column>
      <el-table-column label="操作" width="300" header-align="center" align="center"><template #default="{row}">
        <el-button
          plain
          size="small"
          >
          详情
          </el-button>

          <el-button
          type="success"
          size="small"
          plain
          >
          训练
          </el-button>

          <el-button
          type="warning"
          size="small"
          plain
          >
          推理
          </el-button>

          <el-button
          type="danger"
          size="small"
          plain
          >
          评测
          </el-button>
      </template></el-table-column>
    </el-table>
  </div>

  <el-dialog v-model="uploadVisible" title="🧠 上传模型" width="620px">
    <el-form :model="uploadForm" label-position="top">
      <el-form-item label="模型名称"><el-input v-model="uploadForm.name" /></el-form-item>
      <el-form-item label="框架"><el-select v-model="uploadForm.framework"><el-option label="PyTorch" value="pytorch" /><el-option label="ONNX" value="onnx" /></el-select></el-form-item>
      <el-form-item label="骨干网络"><el-input v-model="uploadForm.backbone" placeholder="如 ResNet50" /></el-form-item>
      <el-form-item label="输入尺寸"><el-input v-model="uploadForm.inputSize" placeholder="640x640" /></el-form-item>
      <el-form-item label="模型文件"><input type="file" accept=".pt,.pth,.onnx" @change="onFileChange" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="uploadVisible=false">取消</el-button><el-button type="primary" @click="onSubmit">确认上传</el-button></template>
  </el-dialog>
</div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMyModels, registerModel } from '@/api/model'
const router = useRouter()
const filter = ref('')
const uploadVisible = ref(false)
const uploadForm = reactive({ name:'', framework:'pytorch', backbone:'', inputSize:'640x640' })
const models = ref([])
async function fetchModels() {
  try {
    const { data } = await getMyModels()
    models.value = Array.isArray(data) ? data : (data.items || data.models || [])
  } catch { /* backend not ready */ }
}
onMounted(fetchModels)
let selectedFile = null
function onFileChange(e) { selectedFile = e.target.files[0] }
async function onSubmit(){
  if (!selectedFile) { ElMessage.warning('请选择模型文件'); return }
  try {
    await registerModel({ ...uploadForm, file: selectedFile })
    uploadVisible.value = false
    ElMessage.success('模型已上传')
    fetchModels()
  } catch(e) { ElMessage.error(e?.response?.data?.detail || '上传失败') }
}
function onEval(row){ router.push('/eval?model='+row.model_id) }
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
  padding:40px;
  margin-bottom:30px;
  border-radius:22px;
  background:
  linear-gradient(
  135deg,
  #1d4ed8,
  #2563eb,
  #3b82f6
  );
  color:white;
  box-shadow:
  0 10px 30px rgba(37,99,235,.25);
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
