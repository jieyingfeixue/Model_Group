<template><div class="page">
  <div class="hero">
    <div>
      <h1>📁 数据源配置</h1>
      <p>配置外部多模态数据源的连接信息、时间戳对齐策略及传感器的空间位置参数。</p>
    </div>
  </div>
  <div class="card">
    <el-empty description="数据源配置功能开发中，当前为占位页面">
      <template #image><span style="font-size:64px">🔧</span></template>
    </el-empty>
  </div>
</div></template>
<style scoped>
.page{padding:28px;max-width:1450px;margin:auto;background:#f8fafc;min-height:100vh}
.hero{padding:45px 50px;margin-bottom:28px;border-radius:18px;color:white;
  background:linear-gradient(135deg,#0f172a,#1e3a8a);
  box-shadow:0 10px 30px rgba(30,64,175,.18)}
.hero h1{font-size:34px;font-weight:700;margin-bottom:12px}
.hero p{font-size:16px;opacity:.92;line-height:1.8;max-width:650px}
.card{background:white;padding:60px 40px;border-radius:20px;
  box-shadow:0 8px 24px rgba(15,23,42,.06)}
</style>
