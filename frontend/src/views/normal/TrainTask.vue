<template><div class="page"><h2>模型训练</h2>
<div class="card"><h3>训练配置</h3>
<el-form label-position="top" style="max-width:500px">
<el-form-item label="模型"><el-select v-model="form.model" style="width:100%"><el-option v-for="m in models" :key="m.model_id" :label="m.name" :value="m.model_id"/></el-select></el-form-item>
<el-form-item label="数据集"><el-select v-model="form.dataset" style="width:100%"><el-option v-for="d in datasets" :key="d.dataset_id" :label="d.name" :value="d.dataset_id"/></el-select></el-form-item>
<el-form-item label="Epochs"><el-input-number v-model="form.epochs" :min="1" :max="500"/></el-form-item>
<el-form-item label="Batch Size"><el-input-number v-model="form.batchSize" :min="1" :max="128"/></el-form-item>
<el-form-item label="Learning Rate"><el-input v-model="form.lr" placeholder="0.001"/></el-form-item>
<el-form-item label="GPU规格"><el-select v-model="form.gpu"><el-option label="A100-40G" value="a100"/><el-option label="V100-32G" value="v100"/></el-select></el-form-item>
<el-button type="primary" @click="onSubmit">提交训练申请</el-button>
</el-form></div>
<div class="card" v-if="submitted"><h3>任务状态</h3><el-tag>{{status}}</el-tag><div style="margin-top:12px"><p>进度: {{progress.epoch}}/{{form.epochs}} epoch</p><p>Loss: {{progress.loss}} | mAP: {{progress.mAP}}</p></div></div>
</div></template>
<script setup>import {ref,reactive,onMounted} from 'vue';import {ElMessage} from 'element-plus'
import { getMyModels } from '@/api/model'
import { getDatasetList } from '@/api/dataset'
import { submitTrain, getTrainDetail } from '@/api/model'

const models = ref([])
const datasets = ref([])
const form=reactive({model:null,dataset:null,epochs:100,batchSize:16,lr:'0.001',gpu:'a100'})
const submitted=ref(false);const status=ref('');const progress=reactive({epoch:0,loss:0,mAP:0})
const taskId = ref(null)
let pollTimer = null

onMounted(async () => {
  try {
    const [mRes, dRes] = await Promise.all([
      getMyModels(),
      getDatasetList({ visibility: 'public' })
    ])
    models.value = mRes.data?.items || []
    datasets.value = dRes.data?.items || []
    form.model = models.value[0]?.model_id || null
    form.dataset = datasets.value[0]?.dataset_id || null
  } catch { /* ignore */ }
})

async function onSubmit(){
  if (!form.model || !form.dataset) { ElMessage.warning('请选择模型和数据集'); return }
  submitted.value = true
  try {
    const { data } = await submitTrain({
      model_id: form.model,
      dataset_id: form.dataset,
      config: { epochs: form.epochs, batch_size: form.batchSize, lr: parseFloat(form.lr) || 0.001 },
      gpu_config: { gpu_type: form.gpu, gpu_count: 1 }
    })
    taskId.value = data.task_id
    status.value = data.status
    ElMessage.success('训练任务已提交')
    // 轮询训练进度
    pollTimer = setInterval(async () => {
      try {
        const { data: t } = await getTrainDetail(taskId.value)
        status.value = t.status
        if (t.progress) {
          progress.epoch = t.progress.epoch || 0
          progress.loss = t.progress.loss || 0
          progress.mAP = t.progress.mAP || 0
        }
        if (['completed','failed','stopped'].includes(t.status)) {
          clearInterval(pollTimer)
          ElMessage.success(t.status === 'completed' ? '训练完成' : '训练已结束')
        }
      } catch { /* ignore */ }
    }, 3000)
  } catch (e) {
    submitted.value = false
    ElMessage.error(e?.response?.data?.detail || '提交训练失败')
  }
}
</script>
<style scoped>.page{padding:24px;max-width:800px;margin:0 auto}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}</style>