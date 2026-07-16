<template><div class="page"><h2>模型对比</h2>
<div class="card"><h3>雷达图</h3><RadarChart :indicators="indicators" :series="radarSeries"/></div>
<div class="card"><h3>指标对比</h3><BarChart title="mAP@0.5 对比" :labels="models.map(m=>m.name)" :values="models.map(m=>m.map50)"/></div>
<div class="card"><h3>排行榜</h3><el-table :data="leaderboard"><el-table-column prop="rank" label="排名" width="60"/><el-table-column prop="name" label="模型"/><el-table-column prop="map50" label="mAP@0.5"/><el-table-column prop="map50_95" label="mAP@0.5:0.95"/><el-table-column prop="fps" label="FPS"/></el-table></div>
</div></template>
<script setup>import RadarChart from '@/components/charts/RadarChart.vue';import BarChart from '@/components/charts/BarChart.vue'
const models=[{name:'YOLOv8-低光增强',map50:0.723,map50_95:0.518,prec:0.81,rec:0.68,fps:45,size:28},{name:'Faster R-CNN R50',map50:0.691,map50_95:0.487,prec:0.78,rec:0.64,fps:22,size:160},{name:'DETR-多模态',map50:0.705,map50_95:0.501,prec:0.79,rec:0.66,fps:18,size:210}]
const indicators=[{name:'mAP@0.5',max:1},{name:'mAP@0.5:0.95',max:1},{name:'Precision',max:1},{name:'Recall',max:1},{name:'FPS',max:60},{name:'轻量化(1/Size)',max:0.05}]
const radarSeries=models.map(m=>({name:m.name,values:[m.map50,m.map50_95,m.prec,m.rec,m.fps,1/m.size]}))
const leaderboard=models.map((m,i)=>({rank:i+1,...m}))</script>
<style scoped>.page{padding:24px;max-width:1200px;margin:0 auto}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}h3{margin-bottom:12px}</style>