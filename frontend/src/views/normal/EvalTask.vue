<template>
    <div class="page">
        <!-- Hero -->
        <div class="hero">
            <div>
            <h1>📊 模型评测</h1>

            <p>
                基于标准测试数据集评估模型性能，
                支持精度分析、指标统计、模型对比和评测报告生成。
            </p>
            </div>
        </div>
    
    <div class="stats">
        <div class="stat-card">
            <div class="icon">🤖</div>
            <h2>{{ models.length }}</h2>
            <span>可评测模型</span>
        </div>

        <div class="stat-card">
            <div class="icon">📂</div>
            <h2>1</h2>
            <span>测试数据集</span>
        </div>

        <div class="stat-card">
            <div class="icon">📈</div>
            <h2>{{ completed ? '100%' : '0%' }}</h2>
            <span>评测进度</span>
        </div>
    </div>

    <div class="content-card">
        <div class="card"><h3>🚀 发起评测任务</h3>
        <el-form label-position="top" class="eval-form">
        <el-form-item label="模型"><el-select v-model="evalForm.model" style="width:100%"><el-option v-for="m in models" :key="m.model_id" :label="m.name" :value="m.model_id"/></el-select></el-form-item>
        <el-form-item label="测试数据集"><el-select v-model="evalForm.dataset" style="width:100%"><el-option v-for="d in datasets" :key="d.dataset_id" :label="d.name" :value="d.dataset_id"/></el-select></el-form-item>
        <el-form-item label="置信度阈值"> <el-slider v-model="evalForm.conf"
            :min="0"
            :max="1"
            :step="0.05"
            show-input
            />
        </el-form-item>
        <el-form-item label="评测指标">
            <el-checkbox-group v-model="evalForm.metrics">
            <el-checkbox label="mAP"/>
            <el-checkbox label="Precision"/>
            <el-checkbox label="Recall"/>
            <el-checkbox label="F1"/>
            </el-checkbox-group>
        </el-form-item>
        <el-button type="primary" size="large" @click="onSubmit">开始评测</el-button>
        </el-form></div>
        <div class="card"
            v-if="running"
            >
            <h3>⚙️ 评测进度</h3>
            <el-progress
            :percentage="progress"
            status="success"
            />
            <p>
            当前状态：
            <el-tag>
            {{ status }}
            </el-tag>
            </p>
        </div>
        <div class="success-card"
            v-if="completed"
            >
            <h3>
            🎉 模型评测完成
            </h3>
            <p>
            本次评测已完成，
            可查看详细报告，
            并与其它模型进行性能对比。
            </p>
            <div class="action-bar">
            <el-button
            type="primary"
            size="large"
            >
            查看评测报告
            </el-button>
            <el-button
            size="large"
            >
            模型对比
            </el-button>
            </div>
            </div>
        </div>
    </div>
</template>

<script setup>
import {ref,reactive,onMounted} from 'vue'
import {useRouter} from 'vue-router'
import {ElMessage} from 'element-plus'
import { getMyModels } from '@/api/model'
import { getDatasetList } from '@/api/dataset'
import { submitEval, getEvalStatus } from '@/api/eval'

const router = useRouter()
const models = ref([])
const datasets = ref([])
const evalForm = reactive({
    model: null,
    dataset: null,
    iou: 0.5,
    conf: 0.25,
    metrics: ['mAP','Precision','Recall']
})
const running=ref(false);const completed=ref(false);const status=ref('')
const progress = ref(0)
const evalTaskId = ref(null)
let pollTimer = null

onMounted(async () => {
  try {
    const [mRes, dRes] = await Promise.all([
      getMyModels(),
      getDatasetList({ visibility: 'public' })
    ])
    models.value = mRes.data?.items || []
    datasets.value = dRes.data?.items || []
    evalForm.model = models.value[0]?.model_id || null
    evalForm.dataset = datasets.value[0]?.dataset_id || null
  } catch { /* ignore */ }
})

async function onSubmit(){
  if (!evalForm.model || !evalForm.dataset) { ElMessage.warning('请选择模型和数据集'); return }
  running.value = true
  progress.value = 10
  status.value = '排队中'
  try {
    const { data } = await submitEval({
      model_id: evalForm.model,
      dataset_id: evalForm.dataset,
      metric_config: {
        iou_thresholds: [evalForm.iou],
        conf_threshold: evalForm.conf,
        metrics: evalForm.metrics
      }
    })
    evalTaskId.value = data.task_id
    status.value = '评测中'
    progress.value = 30
    // 轮询评测状态
    pollTimer = setInterval(async () => {
      try {
        const { data: t } = await getEvalStatus(evalTaskId.value)
        status.value = t.status
        if (t.status === 'running') progress.value = Math.min(progress.value + 10, 90)
        else if (t.status === 'completed') {
          progress.value = 100
          running.value = false
          completed.value = true
          clearInterval(pollTimer)
          ElMessage.success('评测完成')
          router.push('/eval/' + evalTaskId.value)
        } else if (t.status === 'failed') {
          running.value = false
          clearInterval(pollTimer)
          ElMessage.error('评测失败')
        }
      } catch { /* ignore */ }
    }, 2000)
  } catch (e) {
    running.value = false
    ElMessage.error(e?.response?.data?.detail || '提交评测失败')
  }
}

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
    font-weight:700;
    margin-bottom:12px;
}

.hero p{
    max-width:700px;
    line-height:1.8;
    opacity:.9;
}

.stats{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:22px;
    margin-bottom:30px;
}

.stat-card{
    background:white;
    border-radius:18px;
    padding:28px;
    text-align:center;
    box-shadow:0 8px 24px rgba(15,23,42,.05);
}

.icon{
    font-size:30px;
    margin-bottom:12px;
}

.stat-card h2{
    font-size:34px;
    color:#2563eb;
}

.stat-card span{
    color:#64748b;
}

.content-card{
    background:white;
    border-radius:22px;
    padding:28px;
    box-shadow:0 8px 24px rgba(15,23,42,.05);
}

.card{
    padding:24px;
    border:1px solid #e5e7eb;
    border-radius:18px;
    margin-bottom:24px;
}

.card h3{
    margin-bottom:20px;
    font-size:18px;
    font-weight:700;
}

.eval-form{
    max-width:650px;
}

.success-card{
    padding:28px;
    background:#f0fdf4;
    border:1px solid #86efac;
    border-radius:18px;
}

.action-bar{
    display:flex;
    justify-content:flex-end;
    gap:16px;
    margin-top:20px;
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper){
    border-radius:10px;
}

:deep(.el-button){
    border-radius:10px;
}
</style>