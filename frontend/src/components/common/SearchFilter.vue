<template>
  <div class="search-filter">
    <el-select v-model="local.weather" placeholder="天气" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="晴天" value="sunny" />
      <el-option label="雨天" value="rainy" />
      <el-option label="雾天" value="foggy" />
    </el-select>
    <el-select v-model="local.time_of_day" placeholder="时段" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="白天" value="day" />
      <el-option label="夜晚" value="night" />
    </el-select>
    <el-select v-model="local.terrain" placeholder="地形" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="山地" value="mountain" />
      <el-option label="平原" value="plain" />
      <el-option label="河流" value="river" />
    </el-select>
    <el-select v-model="local.obstacle" placeholder="障碍物" @change="onChange">
      <el-option label="全部" value="" />
      <el-option label="高压线塔" value="power_tower" />
      <el-option label="风力发电车" value="wind_turbine" />
      <el-option label="建筑物" value="building" />
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
  time_of_day: props.modelValue?.time_of_day || '',
  terrain: props.modelValue?.terrain || '',
  obstacle: props.modelValue?.obstacle || '',
})

function onChange() {
  emit('update:modelValue', { ...local })
}
function onReset() {
  Object.assign(local, { weather: '', time_of_day: '', terrain: '', obstacle: '' })
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
