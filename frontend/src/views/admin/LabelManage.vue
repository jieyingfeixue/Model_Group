<template><div class="page">
  <div class="hero">
    <div>
      <h1>🏷️ 标签体系管理</h1>
      <p>管理全平台通用的障碍物类别标签库，支持新增、废弃及JSON导入导出。</p>
    </div>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="icon">🏷️</div><h2>{{ categories.length }}</h2><span>标签类别</span></div>
    <div class="stat-card"><div class="icon">✅</div><h2>{{ categories.filter(c=>c.status==='active').length }}</h2><span>启用</span></div>
    <div class="stat-card"><div class="icon">📦</div><h2>{{ categories.filter(c=>c.status==='deprecated').length }}</h2><span>已废弃</span></div>
  </div>

  <div class="toolbar">
    <div><el-button type="primary" size="large" @click="onAdd">+ 新增类别</el-button></div>
    <div class="toolbar-right">
      <el-button @click="onExport">导出JSON</el-button>
      <el-button @click="onImport">导入JSON</el-button>
    </div>
  </div>

  <div class="table-card">
    <el-table :data="categories" stripe v-loading="loading">
      <el-table-column prop="name" label="类别名称" min-width="200" />
      <el-table-column prop="shortcut" label="快捷键" width="80" align="center" />
      <el-table-column prop="depth_required" label="强制深度" width="100" align="center">
        <template #default="{row}"><el-tag :type="row.depth_required?'warning':'info'" size="small">{{row.depth_required?'是':'否'}}</el-tag></template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" align="center">
        <template #default="{row}"><el-tag :type="row.status==='active'?'success':'danger'" round size="small">{{row.status==='active'?'启用':'废弃'}}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <template #default="{row}"><el-button v-if="row.status==='active'" size="small" type="danger" plain @click="onDeprecate(row)">废弃</el-button></template>
      </el-table-column>
    </el-table>
  </div>

  <el-dialog v-model="addVisible" title="新增类别" width="450px">
    <el-form :model="newCat" label-position="top">
      <el-form-item label="类别名称"><el-input v-model="newCat.name" placeholder="如：电线杆"/></el-form-item>
      <el-form-item label="快捷键"><el-input v-model="newCat.shortcut" placeholder="如：w"/></el-form-item>
      <el-form-item label="强制标注深度"><el-switch v-model="newCat.depth_required"/></el-form-item>
    </el-form>
    <template #footer><el-button @click="addVisible=false">取消</el-button><el-button type="primary" @click="onConfirmAdd">确认</el-button></template>
  </el-dialog>
</div></template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/api/request'

const categories = ref([])
const loading = ref(false)
const addVisible = ref(false)
const newCat = reactive({ name: '', shortcut: '', depth_required: true })

async function fetchCategories() {
  loading.value = true
  try {
    const { data } = await request.get('/admin/labels')
    const schemas = data.items || []
    categories.value = schemas.flatMap(s => (s.categories || []).map(c => ({ ...c, schema_id: s.schema_id })))
  } catch {
    // Fallback mock
    categories.value = [
      { id:1, name:'电线杆', shortcut:'w', depth_required:true, status:'active' },
      { id:2, name:'桥梁', shortcut:'q', depth_required:true, status:'active' },
      { id:3, name:'建筑物', shortcut:'e', depth_required:false, status:'active' },
      { id:4, name:'树木', shortcut:'r', depth_required:false, status:'active' },
      { id:5, name:'路灯', shortcut:'t', depth_required:false, status:'deprecated' },
    ]
  } finally { loading.value = false }
}

function onAdd() { addVisible.value = true }
function onConfirmAdd() {
  categories.value.push({ id: Date.now(), ...newCat, status: 'active' })
  addVisible.value = false; ElMessage.success('类别已添加（待后端标签API完善后同步入库）')
}
function onDeprecate(row) { row.status = 'deprecated'; ElMessage.success('已废弃') }
function onExport() { ElMessage.info('导出功能待后端标签API对接') }
function onImport() { ElMessage.info('导入功能待后端标签API对接') }

onMounted(fetchCategories)
</script>

<style scoped>
.page{padding:28px;max-width:1450px;margin:auto;background:#f8fafc;min-height:100vh}
.hero{padding:45px 50px;margin-bottom:28px;border-radius:18px;color:white;
  background:linear-gradient(135deg,#0f172a,#1e3a8a);
  box-shadow:0 10px 30px rgba(30,64,175,.18)}
.hero h1{font-size:34px;font-weight:700;margin-bottom:12px}
.hero p{font-size:16px;opacity:.92;line-height:1.8;max-width:650px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-bottom:30px}
.stat-card{background:white;border-radius:18px;padding:28px;text-align:center;
  box-shadow:0 8px 22px rgba(15,23,42,.05);transition:.3s}
.stat-card:hover{transform:translateY(-6px)}
.stat-card .icon{font-size:30px;margin-bottom:12px}
.stat-card h2{font-size:34px;color:#2563eb;margin:8px 0}
.stat-card span{color:#64748b}
.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
.toolbar-right{display:flex;gap:12px}
.table-card{background:white;padding:22px;border-radius:20px;
  box-shadow:0 8px 24px rgba(15,23,42,.06)}
</style>
