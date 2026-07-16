<template><div class="page"><h2>天梯榜管理</h2>
<div class="card"><h3>试卷锁定</h3><el-select v-model="lockedDataset" placeholder="选择标准测试集" style="width:300px"><el-option label="低空障碍物检测 v1.0" :value="1"/></el-select><el-button type="warning" @click="onLock" style="margin-left:12px">锁定试卷（GT隐藏）</el-button></div>
<div class="card"><h3>作弊注销</h3><el-table :data="cheatLogs"><el-table-column prop="model" label="模型"/><el-table-column prop="score" label="异常分数"/><el-table-column prop="reason" label="原因"/><el-table-column label="操作"><template #default="{row}"><el-button size="small" type="danger" @click="onInvalidate(row)">注销跑分</el-button></template></el-table-column></el-table></div>
<div class="card"><h3>指标权重调整</h3><p>夜间场景mAP权重: <el-slider v-model="nightWeight" :min="0" :max="1" :step="0.1" show-input style="width:300px"/></p><p>FPS权重: <el-slider v-model="fpsWeight" :min="0" :max="1" :step="0.1" show-input style="width:300px"/></p><el-button type="primary" @click="onUpdateWeights">保存权重</el-button></div></div></template>
<script setup>import {ref} from 'vue';import {ElMessage} from 'element-plus';const lockedDataset=ref(null);const nightWeight=ref(0.3);const fpsWeight=ref(0.1)
const cheatLogs=ref([{model:'SuspiciousModel-v3',score:0.998,reason:'分数异常偏高，疑似绕过评测接口'}])
function onLock(){ElMessage.success('试卷已锁定，GT已对普通用户隐藏')}
function onInvalidate(row){ElMessage.success('跑分已注销，已通知用户')}
function onUpdateWeights(){ElMessage.success('权重已更新')}
</script>
<style scoped>.page{padding:24px;max-width:1000px;margin:0 auto}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}</style>