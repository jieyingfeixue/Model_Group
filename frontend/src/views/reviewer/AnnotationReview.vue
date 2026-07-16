<template><div class="page"><h2>标注审核</h2>
<div class="card"><h3>待审核任务</h3><el-table :data="tasks"><el-table-column prop="name" label="任务"/><el-table-column prop="dataset" label="数据集"/><el-table-column prop="annotated" label="标注进度"/><el-table-column prop="status" label="状态"/><el-table-column label="操作"><template #default="{row}"><el-button size="small" @click="onClaim(row)" v-if="row.status==='submitted'">认领</el-button><el-button size="small" type="primary" @click="onStartReview(row)" v-if="row.status==='reviewing'">开始审核</el-button></template></el-table-column></el-table></div>
<div class="card" v-if="reviewing"><h3>抽检配置</h3><p>抽检比例: <el-slider v-model="sampleRatio" :min="10" :max="100" show-input style="width:300px"/></p><el-button type="primary" @click="onStartSampling">开始抽检</el-button></div>
<div class="card" v-if="sampling"><h3>逐张审核</h3><div style="background:#f0f2f5;height:200px;display:flex;align-items:center;justify-content:center;margin-bottom:12px">图片预览区（Canvas标注叠加Mock）</div>
<el-radio-group v-model="reviewVerdict" style="margin-bottom:8px"><el-radio value="approve">通过</el-radio><el-radio value="reject">驳回</el-radio></el-radio-group>
<div v-if="reviewVerdict==='reject'"><p>驳回原因（可多选）:</p><el-checkbox-group v-model="rejectReasons"><el-checkbox v-for="t in rejectOptions" :key="t.code" :label="t.code" :value="t.code">{{t.code}} {{t.label}}</el-checkbox></el-checkbox-group></div>
<el-button @click="onNextSample">下一张</el-button><el-button type="primary" @click="onFinishReview">完成审核</el-button></div>
</div></template>
<script setup>import {ref} from 'vue';import {ElMessage} from 'element-plus'
const tasks=ref([{id:1,name:'第一批可见光标注',dataset:'可见光城市道路 v1',annotated:'120/200',status:'submitted'},{id:2,name:'红外夜间标注',dataset:'红外夜间场景 v2',annotated:'80/150',status:'reviewing'}])
const rejecting=ref(false);const sampling=ref(false);const reviewVerdict=ref('approve');const rejectReasons=ref([]);const sampleRatio=ref(20)
const rejectOptions=[{code:'T01',label:'检测框位置偏移'},{code:'T02',label:'检测框尺寸不准确'},{code:'T03',label:'目标类别标注错误'},{code:'T04',label:'漏标'},{code:'T05',label:'多标'},{code:'T06',label:'深度值明显偏差'},{code:'T07',label:'遮挡程度标注错误'},{code:'T08',label:'截断程度标注错误'},{code:'T09',label:'标注框坐标越界'},{code:'T10',label:'图片质量不可标注'}]
function onClaim(row){row.status='reviewing';ElMessage.success('已认领')}
function onStartReview(row){rejecting.value=true}
function onStartSampling(){sampling.value=true;ElMessage.success('抽检样本已生成')}
function onNextSample(){reviewVerdict.value='approve';rejectReasons.value=[]}
function onFinishReview(){rejecting.value=false;sampling.value=false;ElMessage.success('审核完成')}
</script>
<style scoped>.page{padding:24px;max-width:1200px;margin:0 auto}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}</style>