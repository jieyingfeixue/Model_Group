<template>
<div class="page">
  <div class="hero">
    <div class="hero-text">
      <h1>
        🖊️ 数据标注中心
      </h1>
      <p>
        使用 Auto-labeling-LH 完成目标检测数据标注，
        支持人工框选、SAM3自动检测、深度信息生成，
        标注结果自动同步回平台。
      </p>
    </div>
    <div class="hero-info">
      <div>
        <span>工具状态</span>
        <strong>
          {{health===true?'在线':'未连接'}}
        </strong>
      </div>
      <div>
        <span>支持算法</span>
        <strong>
          SAM3 / LabelMe
        </strong>
      </div>
    </div>
  </div>

  <div class="status-card">
    <div class="status-left">
      <el-tag :type="health === true ? 'success' : health === false ? 'danger' : 'info'" round>
        {{ healthLabel }}
      </el-tag>
      <span class="url">{{ annotatePage }}</span>
    </div>
    <div class="status-right">
      <el-button @click="refreshHealth" :loading="checking">检测服务</el-button>
      <el-button type="primary" size="large" @click="onOpen">打开标注工具</el-button>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>📌 使用步骤</h3>
      <ol>
        <li>在本机启动 Auto-labeling-LH（默认 <code>http://127.0.0.1:8080</code>）</li>
        <li>点击上方「打开标注工具」，在新标签页标注</li>
        <li>工具内以红外帧导航，自动匹配双目可见光，可手动画框或 SAM3 检测</li>
        <li>在工具内保存；产物为扩展 LabelMe JSON</li>
        <li>回到平台打开对应可见光详情，点「显示标注」查看叠加结果</li>
      </ol>
    </div>
    <div class="card">
      <h3>🚀 启动标注服务</h3>
      <p class="hint">本地联调（推荐，自动指向仓库里的 with_cameras_capture_*）：</p>
      <pre>powershell -ExecutionPolicy Bypass -File scripts/start_lh_local.ps1</pre>
      <p class="hint">或手动指定数据根后启动：</p>
      <pre>$env:LH_DATASET_ROOT="E:\学校有关\暑期岗位实习\Model_Group-main"
cd Auto-labeling-LH
python -m web_server.app</pre>
      <p class="hint">
        注意：不要指到 <code>E:\robot</code>（里面没有 LH 采集结构）。
        标注结果写到仓库根的 <code>label_with_annotation_and_depth/</code>；
        已有 LabelMe 在 <code>label_with_cameras_capture_*</code> 也可被平台回显。
      </p>
      <p class="hint">
        跳转地址可用前端环境变量 <code>VITE_LH_ANNOTATE_URL</code> 配置
        （见 <code>frontend/.env.example</code>）。
      </p>
    </div>
    <div class="card">
      <h3>🔄 结果如何回到平台</h3>
      <ul>
        <li>LH 工具默认写出目录：<code>label_with_annotation_and_depth/</code>（仓库根旁）</li>
        <li>也可使用：<code>label_with_cameras_capture_*</code></li>
        <li>Docker 已挂载上述目录到 API 的 <code>/labels</code></li>
        <li>详情接口按可见光文件名 / 时间戳+相机号匹配；有非空 <code>shapes</code> 才显示框与「已标注」</li>
      </ul>
    </div>
  </div>
</div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  LH_ANNOTATE_PAGE,
  openLhAnnotateTool,
  checkLhAnnotateHealth,
} from '@/config/lhAnnotate'

const annotatePage = LH_ANNOTATE_PAGE
const health = ref(null)
const checking = ref(false)

const healthLabel = computed(() => {
  if (health.value === true) return '标注服务在线'
  if (health.value === false) return '标注服务未检测到'
  return '尚未检测'
})

async function refreshHealth() {
  checking.value = true
  health.value = await checkLhAnnotateHealth()
  checking.value = false
}

function onOpen() {
  openLhAnnotateTool()
  if (health.value === false) {
    ElMessage.warning('未检测到标注服务，请先在本机启动 Auto-labeling-LH')
  } else {
    ElMessage.success('已在新标签页打开标注工具')
  }
  refreshHealth()
}

onMounted(refreshHealth)
</script>

<style scoped>
.page {
  padding:28px;
  width:100%;
  max-width:none;
  background:#f8fafc;
  min-height:100vh;
}
.hero{
display:flex;
justify-content:space-between;
align-items:center;
padding:45px 50px;
margin-bottom:26px;
border-radius:22px;
background:
linear-gradient(
135deg,
#0f172a,
#2563eb
);
color:white;
box-shadow:
0 15px 40px rgba(37,99,235,.25);
}

.hero-text{
max-width:750px;
}

.hero h1{
font-size:32px;
margin-bottom:12px;
}

.hero p{
font-size:16px;
line-height:1.8;
opacity:.9;
}

.hero-info{
display:flex;
gap:20px;
}

.hero-info div{
background:
rgba(255,255,255,.15);
padding:20px 28px;
border-radius:16px;
backdrop-filter:blur(8px);
}

.hero-info span{
display:block;
font-size:13px;
opacity:.8;
}

.hero-info strong{
display:block;
margin-top:8px;
font-size:20px;
}

.status-card{
background:white;
border-radius:18px;
padding:22px 28px;
margin-bottom:26px;
border:
1px solid #e2e8f0;
box-shadow:
0 10px 30px rgba(15,23,42,.08);
}

.status-card:hover{
transform:translateY(-3px);
box-shadow:
0 15px 35px rgba(15,23,42,.12);
transition:.3s;
}

.status-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.url {
  color: #64748b;
  font-size: 13px;
  word-break: break-all;
}
.status-right {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.grid{
display:grid;
grid-template-columns:
repeat(3,1fr);
gap:24px;
}
.card{
background:white;
border-radius:18px;
padding:24px;
border:
1px solid #e2e8f0;
box-shadow:
0 8px 24px rgba(15,23,42,.05);
transition:.3s;
}

.card:hover{
transform:translateY(-5px);
box-shadow:
0 15px 35px rgba(15,23,42,.1);
}

.card h3 {
  margin: 0 0 12px;
  font-size: 16px;
  color: #0f172a;
}
.card ol,
.card ul {
  margin: 0;
  padding-left: 18px;
  color: #334155;
  line-height: 1.75;
  font-size: 14px;
}
.hint {
  margin: 0 0 8px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}
pre{
margin-top:12px;
padding:18px;
background:#f8fafc;
color:#1e293b;
border:1px solid #e2e8f0;
border-radius:14px;
font-size:13px;
line-height:1.7;
}
code {
  font-size: 12px;
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
