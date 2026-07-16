<template><div class="page"><h2>模型评测</h2>
<div class="card"><h3>发起评测</h3>
<el-form label-position="top" style="max-width:500px">
<el-form-item label="模型"><el-select v-model="evalForm.model" style="width:100%"><el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id"/></el-select></el-form-item>
<el-form-item label="测试数据集"><el-select v-model="evalForm.dataset" style="width:100%"><el-option label="低空障碍物检测 v1.0" :value="1"/></el-select></el-form-item>
<el-form-item label="IoU阈值"><el-input v-model="evalForm.iou" placeholder="0.5"/></el-form-item>
<el-button type="primary" @click="onSubmit">开始评测</el-button>
</el-form></div>
<div class="card" v-if="running"><h3>评测进度</h3><el-tag>{{status}}</el-tag><p style="margin-top:8px">正在计算指标...</p></div>
<div class="card" v-if="completed"><h3>评测完成</h3>
<el-button type="primary" @click="$router.push('/eval/1')">查看报告</el-button>
<el-button @click="$router.push('/compare')">模型对比</el-button></div>
</div></template>
<script setup>import {ref,reactive} from 'vue';import {ElMessage} from 'element-plus'
const models=[{id:1,name:'YOLOv8-低光增强'},{id:2,name:'Faster R-CNN ResNet-50'}]
const evalForm=reactive({model:1,dataset:1,iou:'0.5'});const running=ref(false);const completed=ref(false);const status=ref('')
function onSubmit(){running.value=true;status.value='queued';ElMessage.success('评测任务已提交')
setTimeout(()=>{status.value='running'},1000);setTimeout(()=>{status.value='completed';running.value=false;completed.value=true;ElMessage.success('评测完成')},3000)}
</script>
<style scoped>.page{padding:24px;max-width:800px;margin:0 auto}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}</style>