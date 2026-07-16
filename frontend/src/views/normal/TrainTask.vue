<template><div class="page"><h2>模型训练</h2>
<div class="card"><h3>训练配置</h3>
<el-form label-position="top" style="max-width:500px">
<el-form-item label="模型"><el-select v-model="form.model" style="width:100%"><el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id"/></el-select></el-form-item>
<el-form-item label="数据集"><el-select v-model="form.dataset" style="width:100%"><el-option label="低空障碍物检测 v1.0" :value="1"/></el-select></el-form-item>
<el-form-item label="Epochs"><el-input-number v-model="form.epochs" :min="1" :max="500"/></el-form-item>
<el-form-item label="Batch Size"><el-input-number v-model="form.batchSize" :min="1" :max="128"/></el-form-item>
<el-form-item label="Learning Rate"><el-input v-model="form.lr" placeholder="0.001"/></el-form-item>
<el-form-item label="GPU规格"><el-select v-model="form.gpu"><el-option label="A100-40G" value="a100"/><el-option label="V100-32G" value="v100"/></el-select></el-form-item>
<el-button type="primary" @click="onSubmit">提交训练申请</el-button>
</el-form></div>
<div class="card" v-if="submitted"><h3>任务状态</h3><el-tag>{{status}}</el-tag><div style="margin-top:12px"><p>进度: {{progress.epoch}}/{{form.epochs}} epoch</p><p>Loss: {{progress.loss}} | mAP: {{progress.mAP}}</p></div></div>
</div></template>
<script setup>import {ref,reactive} from 'vue';import {ElMessage} from 'element-plus'
const models=[{id:1,name:'YOLOv8-低光增强'},{id:2,name:'Faster R-CNN ResNet-50'}]
const form=reactive({model:1,dataset:1,epochs:100,batchSize:16,lr:'0.001',gpu:'a100'})
const submitted=ref(false);const status=ref('pending_approval');const progress=reactive({epoch:0,loss:0,mAP:0})
function onSubmit(){submitted.value=true;ElMessage.success('训练申请已提交（Mock）');status.value='approved'
let e=0;const t=setInterval(()=>{e+=5;progress.epoch=e;progress.loss=(0.8-e/500).toFixed(3);progress.mAP=(e/250).toFixed(3);if(e>=100){clearInterval(t);status.value='completed';ElMessage.success('训练完成')}},800)}
</script>
<style scoped>.page{padding:24px;max-width:800px;margin:0 auto}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}</style>