<template>
  <div class="data-grid-wrapper">
    <div v-if="items.length === 0" class="empty">暂无数据</div>
    <div v-else class="grid">
      <div v-for="item in items" :key="item.resource_id" class="grid-item"
        @click="$emit('select', item)">
        <div class="thumb">
          <img :src="`/api/images/${item.resource_id}/thumbnail`"
            loading="lazy" @error="onImgError" />
          <span class="modality-tag" :class="item.modality">
            {{ modalityLabel(item.modality) }}
          </span>
          <span class="status-tag" :class="item.annotation_status">
            {{ item.annotation_status === 'annotated' ? '已标注' : '未标注' }}
          </span>
        </div>
        <div class="info">

    <div class="name"
         :title="item.name">

        {{ item.name }}

    </div>

    <div class="meta">

        <span>
            📍 {{ item.metadata?.scene || '-' }}
        </span>

        <span>
            🌞 {{ item.metadata?.time_of_day || '-' }}
        </span>

    </div>

    <div class="meta">

        <span>
            📅 {{ formatDate(item.created_at) }}
        </span>

        <span>
            📷 {{ item.metadata?.source || '-' }}
        </span>

    </div>

    <div class="detail-btn">

        查看详情 →

    </div>

</div>
      </div>
    </div>
    <div class="pagination" v-if="total > pageSize">
      <el-pagination background layout="prev, pager, next" :total="total"
        :page-size="pageSize" :current-page="currentPage" @current-change="$emit('page-change', $event)" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  pageSize: { type: Number, default: 12 },
  currentPage: { type: Number, default: 1 },
})
defineEmits(['select', 'page-change'])

function modalityLabel(m) {
  const map = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }
  return map[m] || m
}
function formatDate(d) {
  if (!d) return '-'
  return new Date(d).toLocaleDateString('zh-CN')
}
function onImgError(e) { e.target.style.display = 'none' }
</script>

<style scoped>
.data-grid-wrapper { min-height: 200px; }
.empty { text-align: center; padding: 60px; color: #9ca3af; font-size: 14px; }
.grid{

display:grid;

grid-template-columns:
repeat(auto-fill,minmax(280px,1fr));

gap:24px;

}
.grid-item{

background:#fff;

border-radius:18px;

overflow:hidden;

cursor:pointer;

border:1px solid #edf2f7;

box-shadow:

0 6px 20px rgba(15,23,42,.06);

transition:

all .25s ease;

}
.grid-item:hover{

transform:translateY(-6px);

box-shadow:

0 18px 35px rgba(37,99,235,.18);

border-color:#bfdbfe;

}
.thumb{

position:relative;

height:180px;

background:

linear-gradient(
135deg,
#f8fafc,
#e2e8f0
);

overflow:hidden;

}
.thumb img{

width:100%;

height:100%;

object-fit:cover;

transition:

transform .4s;

}
.grid-item:hover img{

transform:scale(1.06);

}
.thumb-placeholder { display: flex; align-items: center; justify-content: center;
  height: 100%; color: #9ca3af; font-size: 13px; }
.modality-tag{

position:absolute;

left:12px;

top:12px;

padding:5px 12px;

border-radius:30px;

font-size:12px;

font-weight:600;

color:white;

backdrop-filter:blur(8px);

}
.modality-tag.visible{

background:#2563eb;

}

.modality-tag.infrared{

background:#ef4444;

}

.modality-tag.mmwave{

background:#7c3aed;

}

.modality-tag.lidar{

background:#0891b2;

}
.status-tag{

position:absolute;

right:12px;

top:12px;

padding:5px 10px;

border-radius:20px;

font-size:12px;

font-weight:600;

color:white;

}
.status-tag.annotated { background: #22c55e; }
.status-tag.unannotated { background: #f59e0b; }
.info{

padding:18px;

}
.name{

font-size:17px;

font-weight:700;

color:#1e293b;

margin-bottom:14px;

white-space:nowrap;

overflow:hidden;

text-overflow:ellipsis;

}
.meta{

display:flex;

justify-content:space-between;

margin-bottom:10px;

font-size:13px;

color:#64748b;

}
.pagination { display: flex; justify-content: center; margin-top: 20px; }
.detail-btn{

margin-top:14px;

padding-top:14px;

border-top:1px solid #f1f5f9;

font-size:14px;

font-weight:600;

color:#2563eb;

transition:.2s;

}

.grid-item:hover .detail-btn{

padding-left:8px;

}
</style>
