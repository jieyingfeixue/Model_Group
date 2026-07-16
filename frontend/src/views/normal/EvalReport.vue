<template><div class="page"><h2>评测报告</h2>
<div class="metrics-row"><div class="metric-card"><span class="val">0.723</span><span class="lbl">mAP@0.5</span></div><div class="metric-card"><span class="val">0.518</span><span class="lbl">mAP@0.5:0.95</span></div><div class="metric-card"><span class="val">0.81</span><span class="lbl">Precision</span></div><div class="metric-card"><span class="val">0.68</span><span class="lbl">Recall</span></div></div>
<div class="card"><h3>PR 曲线</h3><PrCurve :data="prData"/></div>
<div class="card"><h3>混淆矩阵</h3><ConfusionMatrix :data="matrix" :labels="labels"/></div>
<div class="card"><h3>分类别 AP</h3><BarChart title="各类别 AP" :labels="labels" :values="perClass"/></div>
<div class="card"><h3>分场景评测</h3><BarChart title="分场景 mAP" :labels="['白天','夜间','雨天']" :values="[0.75,0.62,0.58]"/></div>
<div class="card"><h3>错误样本</h3><el-tabs><el-tab-pane label="漏检(FN)"><p v-for="i in 3" :key="i">样本 #{{i}}: 图像可见光_000{{i}}.jpg — 未检测到障碍物</p></el-tab-pane><el-tab-pane label="误检(FP)"><p v-for="i in 3" :key="i">样本 #{{i+3}}: 图像可见光_000{{i+3}}.jpg — 误检为障碍物</p></el-tab-pane></el-tabs></div>
</div></template>
<script setup>import PrCurve from '@/components/charts/PrCurve.vue';import ConfusionMatrix from '@/components/charts/ConfusionMatrix.vue';import BarChart from '@/components/charts/BarChart.vue'
const labels=['电线杆','桥梁','建筑物','树木','路灯'];const perClass=[0.82,0.71,0.65,0.78,0.66]
const prData=labels.map((n,i)=>({name:n,points:Array.from({length:20},(_,j)=>{const r=(j+1)/20;return[r,(0.9-i*0.05)*(1-r*r*0.6)]})}))
const matrix=[[45,2,1,0,1],[1,38,3,1,0],[0,2,32,3,1],[1,0,2,40,2],[0,1,0,1,35]]</script>
<style scoped>.page{padding:24px;max-width:1200px;margin:0 auto}.metrics-row{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}.metric-card{background:#fff;border-radius:8px;padding:20px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.04)}.val{display:block;font-size:28px;font-weight:700;color:#1a1a2e}.lbl{font-size:13px;color:#6b7280}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}</style>