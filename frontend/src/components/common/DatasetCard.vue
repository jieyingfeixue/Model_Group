<template>
  <div class="card" @click="$emit('click', dataset)">
    <!-- 顶部封面 -->
    <div class="card-cover">
      <div class="cover-icon">
        {{ modalityIcon(dataset.modality) }}
      </div>

      <div class="cover-badge">
        <span
          v-if="dataset.is_official"
          class="badge official"
        >
          官方
        </span>
        <span
          v-else
          class="badge community"
        >
          社区
        </span>
      </div>
    </div>

    <!-- 内容 -->
    <div class="card-content">
      <h3 class="card-title">
        {{ dataset.name }}
      </h3>
      <p class="card-desc">
        {{ dataset.description || '暂无数据集描述' }}
      </p>
      <div class="card-meta">
        <div class="meta-item">
          📦 {{ dataset.sample_count }}
          <span>样本</span>
        </div>
        <div class="meta-item">
          🛰 {{ modalityLabel(dataset.modality) }}
        </div>
      </div>
    </div>

    <!-- 按钮 -->
    <div
      class="card-actions"
      @click.stop
    >
      <el-button
        plain
        @click="$emit('preview', dataset)"
      >
        预览
      </el-button>
      <el-button
        type="primary"
        @click="$emit('download', dataset)"
      >
        下载
      </el-button>
    </div>
  </div>
</template>

<script setup>
defineProps({ dataset: Object })
defineEmits(['click', 'preview', 'download'])

function modalityIcon(m) {
  const map = { visible: '📷', infrared: '🔥', mmwave: '📡', lidar: '📐' }
  return map[m] || '📷'
}
function modalityLabel(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
</script>

<style scoped>
.card{
  background:#fff;
  border-radius:20px;
  overflow:hidden;
  cursor:pointer;
  border:1px solid #e2e8f0;
  box-shadow:
  0 8px 24px rgba(15,23,42,.05);
  transition:
  all .25s ease;
  display:flex;
  flex-direction:column;
}

.card:hover{
  transform:translateY(-6px);
  box-shadow:
  0 18px 40px rgba(37,99,235,.12);
  border-color:#bfdbfe;
}

.card-cover{
  height:120px;
  background:
  linear-gradient(
  135deg,
  #1d4ed8,
  #2563eb,
  #60a5fa
  );
  display:flex;
  align-items:center;
  justify-content:center;
  position:relative;
}

.cover-icon{
  font-size:48px;
  filter:drop-shadow(0 6px 12px rgba(0,0,0,.15));
}

.cover-badge{
  position:absolute;
  right:16px;
  top:16px;
}

.badge{
  padding:5px 12px;
  border-radius:20px;
  font-size:12px;
  font-weight:600;
  color:white;
}

.badge.official{background:#10b981;}

.badge.community{background:#f59e0b;}

.card-content{
  padding:20px;
  flex:1;
  display:flex;
  flex-direction:column;
}

.card-title{
  font-size:18px;
  font-weight:700;
  color:#0f172a;
  margin-bottom:10px;
  line-height:1.4;
}

.card-desc{
  font-size:14px;
  color:#64748b;
  line-height:1.7;
  height:48px;
  overflow:hidden;
  display:-webkit-box;
  -webkit-line-clamp:2;
  -webkit-box-orient:vertical;
  margin-bottom:18px;
}

.card-meta{
  display:flex;
  justify-content:space-between;
  padding-top:12px;
  border-top:1px solid #e5e7eb;
}

.meta-item{
  display:flex;
  align-items:center;
  gap:6px;
  font-size:13px;
  color:#475569;
  font-weight:600;
}

.card-actions{
  display:flex;
  gap:10px;
  padding:0 20px 20px;
}

.card-actions .el-button{
  flex:1;
  height:38px;
  border-radius:10px;
}
</style>
