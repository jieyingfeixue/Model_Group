<template><div class="page" v-if="model">
  <div class="hero"><h1>{{ model.name }}</h1><p>{{ model.framework }} · {{ model.status }}</p></div>
  <div class="card"><h3>基本信息</h3>
    <table class="kv">
      <tr><td>名称</td><td>{{ model.name }}</td></tr>
      <tr><td>框架</td><td>{{ model.framework }}</td></tr>
      <tr><td>骨干</td><td>{{ model.meta_info?.backbone || '-' }}</td></tr>
      <tr><td>输入尺寸</td><td>{{ model.meta_info?.input_size?.w || 640 }}×{{ model.meta_info?.input_size?.h || 640 }}</td></tr>
      <tr><td>状态</td><td><el-tag :type="model.status==='available'?'success':'info'" round size="small">{{ model.status }}</el-tag></td></tr>
      <tr><td>创建时间</td><td>{{ model.created_at }}</td></tr>
    </table>
  </div>
  <div class="card" v-if="versions.length > 0"><h3>版本历史</h3>
    <el-timeline><el-timeline-item v-for="v in versions" :key="v.version_id" :timestamp="v.created_at">
      {{ v.version_number }} — {{ v.change_note || '无说明' }}
    </el-timeline-item></el-timeline>
  </div>
  <div class="actions">
    <el-button type="success" @click="$router.push('/train')">训练</el-button>
    <el-button type="warning" @click="$router.push('/eval')">评测</el-button>
  </div>
</div>
<div v-else class="loading">加载中...</div></template>
<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getModelDetail } from '@/api/model'

const route = useRoute()
const model = ref(null)
const versions = ref([])

onMounted(async () => {
  try {
    const { data } = await getModelDetail(route.params.id)
    model.value = data
    versions.value = data.versions || []
  } catch { model.value = null }
})
</script>
<style scoped>
.page{padding:24px;max-width:900px;margin:0 auto}
.hero{padding:32px 40px;margin-bottom:24px;border-radius:18px;
  background:linear-gradient(135deg,#0f172a,#1e3a8a);color:white;
  box-shadow:0 10px 30px rgba(30,64,175,.18)}
.hero h1{font-size:26px;margin-bottom:6px}
.hero p{opacity:.85}
.card{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;
  box-shadow:0 1px 4px rgba(0,0,0,.04);border:1px solid #e5e7eb}
.kv td{padding:6px 12px 6px 0;font-size:14px}
.kv td:first-child{color:#6b7280;width:100px}
.actions{display:flex;gap:12px;margin-top:16px}
.loading{text-align:center;padding:60px;color:#9ca3af}
</style>