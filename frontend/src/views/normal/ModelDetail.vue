<template><div class="page"><h2>模型详情</h2>
<div class="card"><h3>基本信息</h3>
<table class="kv"><tr><td>名称</td><td>YOLOv8-低光增强</td></tr><tr><td>框架</td><td>PyTorch</td></tr><tr><td>骨干</td><td>CSPDarknet</td></tr><tr><td>输入</td><td>640x640</td></tr><tr><td>状态</td><td>available</td></tr></table></div>
<div class="card"><h3>版本历史</h3><el-timeline><el-timeline-item v-for="v in versions" :key="v.v" :timestamp="v.d">{{v.v}} — {{v.n}}</el-timeline-item></el-timeline></div>
<el-button type="success" @click="$router.push('/train')">训练</el-button><el-button type="warning" style="margin-left:12px" @click="$router.push('/eval')">评测</el-button>
</div></template>
<script setup>const versions=[{v:'v1.0.0',d:'2024-05-10',n:'初始版本'},{v:'v1.1.0',d:'2024-06-02',n:'新增数据增强'},{v:'v1.2.0',d:'2024-06-20',n:'优化学习率'}]</script>
<style scoped>.page{padding:24px;max-width:800px;margin:0 auto}.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}.kv td{padding:6px 12px 6px 0;font-size:14px}.kv td:first-child{color:#6b7280;width:100px}</style>