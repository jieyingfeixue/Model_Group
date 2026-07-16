<template>
  <div class="search-filter">
    <el-input v-model="local.keyword" placeholder="搜索文件名..." clearable class="keyword-input"
      @input="onChange" @clear="onChange" />
    <el-select v-model="local.modality" placeholder="模态类型" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="可见光" value="visible" />
      <el-option label="红外" value="infrared" />
      <el-option label="毫米波" value="mmwave" />
      <el-option label="激光雷达" value="lidar" />
    </el-select>
    <el-select v-model="local.annotation_status" placeholder="标注状态" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="已标注" value="annotated" />
      <el-option label="未标注" value="unannotated" />
    </el-select>
    <el-select v-model="local.scene" placeholder="场景环境" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="白天" value="daytime" />
      <el-option label="夜间" value="night" />
      <el-option label="雨天" value="rainy" />
      <el-option label="雾天" value="foggy" />
    </el-select>
    <el-date-picker v-model="local.timeRange" type="daterange" range-separator="至"
      start-placeholder="开始日期" end-placeholder="结束日期" @change="onChange" />
    <el-button @click="onReset">重置</el-button>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const props = defineProps({ modelValue: Object })
const emit = defineEmits(['update:modelValue'])

const local = reactive({
  keyword: props.modelValue?.keyword || '',
  modality: props.modelValue?.modality || '',
  annotation_status: props.modelValue?.annotation_status || '',
  scene: props.modelValue?.scene || '',
  timeRange: props.modelValue?.timeRange || null,
})

function onChange() {
  emit('update:modelValue', { ...local })
}
function onReset() {
  Object.assign(local, { keyword: '', modality: '', annotation_status: '', scene: '', timeRange: null })
  emit('update:modelValue', { ...local })
}
</script>

<style scoped>
.search-filter {
  display: flex; gap: 10px; flex-wrap: nowrap; align-items: center;
  padding: 12px 16px; background: #fff; border-radius: 8px; margin-bottom: 16px;
}
.keyword-input { width: 160px; }
.search-filter .el-select { width: 120px; }
.search-filter .el-date-picker { width: 220px; }
</style>
