<template>
  <div class="search-filter">
    <el-select v-model="local.weather" placeholder="天气" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="晴天" value="sunny" />
      <el-option label="多云" value="cloudy" />
      <el-option label="雨天" value="rainy" />
      <el-option label="雾天" value="foggy" />
    </el-select>
    <el-select v-model="local.timeOfDay" placeholder="时间" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="白天" value="day" />
      <el-option label="夜晚" value="night" />
    </el-select>
    <el-select v-model="local.terrain" placeholder="地形" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="城市" value="urban" />
      <el-option label="高速" value="highway" />
      <el-option label="乡村" value="rural" />
      <el-option label="山区" value="mountain" />
    </el-select>
    <el-select v-model="local.obstacle" placeholder="障碍物" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="电线杆" value="pole" />
      <el-option label="桥梁" value="bridge" />
      <el-option label="建筑物" value="building" />
      <el-option label="树木" value="tree" />
      <el-option label="路灯" value="lamp" />
    </el-select>
    <el-button @click="onReset">重置</el-button>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const props = defineProps({ modelValue: Object })
const emit = defineEmits(['update:modelValue'])

const local = reactive({
  weather: props.modelValue?.weather || '',
  timeOfDay: props.modelValue?.timeOfDay || '',
  terrain: props.modelValue?.terrain || '',
  obstacle: props.modelValue?.obstacle || '',
})

function onChange() {
  emit('update:modelValue', { ...local })
}
function onReset() {
  Object.assign(local, { weather: '', timeOfDay: '', terrain: '', obstacle: '' })
  emit('update:modelValue', { ...local })
}
</script>

<style scoped>
.search-filter {
  display: flex; gap: 10px; flex-wrap: nowrap; align-items: center;
  padding: 12px 16px; background: #fff; border-radius: 8px; margin-bottom: 16px;
}
.search-filter .el-select { width: 140px; }
</style>
