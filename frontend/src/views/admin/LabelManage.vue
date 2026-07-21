<template>
  <div class="page">
    <h2>标签体系管理</h2>
    <div class="toolbar">
      <el-select v-model="schemaId" placeholder="选择标签体系" style="width:260px" filterable @change="loadCategories">
        <el-option v-for="s in schemas" :key="s.schema_id" :label="`${s.name} (#${s.schema_id})`" :value="s.schema_id" />
      </el-select>
      <el-button type="primary" @click="onCreateSchema">新建体系</el-button>
      <el-button @click="onAdd" :disabled="!schemaId">新增类别</el-button>
      <el-button @click="onExport" :disabled="!schemaId">导出 JSON</el-button>
      <el-button @click="onImport">导入 JSON</el-button>
    </div>

    <el-table :data="categories" style="margin-top:12px" v-loading="loading">
      <el-table-column prop="category_id" label="ID" width="100" />
      <el-table-column prop="name" label="类别名称" />
      <el-table-column prop="shortcut" label="快捷键" width="80" />
      <el-table-column prop="depth_required" label="强制深度" width="100">
        <template #default="{row}"><el-tag :type="row.depth_required?'warning':'info'" size="small">{{row.depth_required?'是':'否'}}</el-tag></template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{row}"><el-tag :type="row.status==='active'?'success':'danger'" size="small">{{row.status}}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{row}">
          <el-button size="small" @click="onDeprecate(row)" v-if="row.status==='active'">废弃</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="addVisible" title="新增类别" width="400px">
      <el-form :model="newCat" label-position="top">
        <el-form-item label="名称"><el-input v-model="newCat.name"/></el-form-item>
        <el-form-item label="快捷键"><el-input v-model="newCat.shortcut"/></el-form-item>
        <el-form-item label="强制标注深度"><el-switch v-model="newCat.depth_required"/></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible=false">取消</el-button>
        <el-button type="primary" @click="onConfirmAdd">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listSchemas,
  createSchema,
  addCategory,
  deprecateCategory,
  exportSchema,
  importSchema,
} from '@/api/admin'
import { getActiveCategories } from '@/api/annotation'

const schemas = ref([])
const schemaId = ref(null)
const categories = ref([])
const loading = ref(false)
const addVisible = ref(false)
const newCat = reactive({ name: '', shortcut: '', depth_required: true })

async function loadSchemas() {
  try {
    const { data } = await listSchemas()
    schemas.value = data.items || []
    if (!schemaId.value && schemas.value.length) {
      schemaId.value = schemas.value[0].schema_id
      await loadCategories()
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载标签体系失败（需 admin）')
  }
}

async function loadCategories() {
  if (!schemaId.value) return
  loading.value = true
  try {
    const { data } = await getActiveCategories(schemaId.value)
    const cats = data.categories || []
    // 合并 schema 内全部（含 deprecated）
    const full = schemas.value.find((s) => s.schema_id === schemaId.value)?.categories
    categories.value = Array.isArray(full) && full.length ? full : cats
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载类别失败')
  } finally {
    loading.value = false
  }
}

async function onCreateSchema() {
  try {
    const { value } = await ElMessageBox.prompt('体系名称', '新建标签体系')
    const { data } = await createSchema({ name: value })
    ElMessage.success('已创建')
    await loadSchemas()
    schemaId.value = data.schema_id
    await loadCategories()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

function onAdd() { addVisible.value = true }

async function onConfirmAdd() {
  try {
    await addCategory(schemaId.value, { ...newCat })
    addVisible.value = false
    newCat.name = ''
    newCat.shortcut = ''
    ElMessage.success('类别已添加')
    await loadSchemas()
    await loadCategories()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  }
}

async function onDeprecate(row) {
  try {
    const { value } = await ElMessageBox.prompt('废弃原因', '废弃类别')
    await deprecateCategory(schemaId.value, row.category_id, { reason: value })
    ElMessage.success('已废弃')
    await loadSchemas()
    await loadCategories()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '废弃失败')
  }
}

async function onExport() {
  try {
    const { data } = await exportSchema(schemaId.value)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `schema_${schemaId.value}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '导出失败')
  }
}

async function onImport() {
  try {
    const { value } = await ElMessageBox.prompt('粘贴 JSON（需含 name 与 categories）', '导入', {
      inputType: 'textarea',
    })
    const parsed = JSON.parse(value)
    await importSchema(parsed)
    ElMessage.success('导入成功')
    await loadSchemas()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || e?.message || '导入失败')
  }
}

onMounted(loadSchemas)
</script>

<style scoped>
.page{padding:24px;max-width:1000px;margin:0 auto}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
</style>
