<template>
<div class="page">
  <div class="hero">
    <div>
      <h1>🖊️ 数据标注</h1>
      <p>
        标注在独立工具 Auto-labeling-LH 中完成（画框 / SAM3 / 深度）。
        平台负责入口跳转，以及把 LabelMe 结果回显到数据浏览与样本详情。
      </p>
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
      <h3>使用步骤</h3>
      <ol>
        <li>在本机启动 Auto-labeling-LH（默认 <code>http://127.0.0.1:8080</code>）</li>
        <li>点击上方「打开标注工具」，在新标签页标注</li>
        <li>工具内以红外帧导航，自动匹配双目可见光，可手动画框或 SAM3 检测</li>
        <li>在工具内保存；产物为扩展 LabelMe JSON</li>
        <li>回到平台打开对应可见光详情，点「显示标注」查看叠加结果</li>
      </ol>
    </div>
    <div class="card">
      <h3>启动标注服务</h3>
      <p class="hint">在仓库根目录执行（需已安装该工具依赖）：</p>
      <pre>cd Auto-labeling-LH
python -m web_server.app</pre>
      <p class="hint">或：</p>
      <pre>cd Auto-labeling-LH
uvicorn web_server.app:app --host 0.0.0.0 --port 8080</pre>
      <p class="hint">
        跳转地址可用前端环境变量 <code>VITE_LH_ANNOTATE_URL</code> 配置
        （见 <code>frontend/.env.example</code>）。
      </p>
    </div>
    <div class="card">
      <h3>结果如何回到平台</h3>
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
  padding: 28px;
  max-width: 1100px;
  margin: auto;
  background: #f8fafc;
  min-height: 100vh;
}
.hero {
  padding: 40px 44px;
  margin-bottom: 22px;
  border-radius: 18px;
  color: white;
  background: linear-gradient(135deg, #0f172a, #1e3a8a);
  box-shadow: 0 10px 30px rgba(30, 64, 175, 0.18);
}
.hero h1 {
  font-size: 30px;
  margin: 0 0 10px;
}
.hero p {
  margin: 0;
  opacity: 0.92;
  line-height: 1.7;
  font-size: 15px;
}
.status-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  background: white;
  border-radius: 16px;
  padding: 18px 20px;
  margin-bottom: 20px;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
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
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}
.card {
  background: white;
  border-radius: 16px;
  padding: 20px 22px;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
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
pre {
  margin: 0 0 12px;
  padding: 12px 14px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 10px;
  font-size: 12px;
  overflow-x: auto;
  line-height: 1.55;
}
code {
  font-size: 12px;
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
