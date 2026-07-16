<template>
  <div class="info-panel">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="基本信息" name="basic">
        <div class="info-list">

          <div class="info-item">
            <span class="label">文件名</span>
            <span class="value">{{ item.name }}</span>
          </div>

          <div class="info-item">
            <span class="label">模态类型</span>
            <span class="value">
              {{ modalityMap[item.modality] || item.modality }}
            </span>
          </div>

          <div class="info-item">
            <span class="label">分辨率</span>
            <span class="value">
              {{ item.metadata?.width }} × {{ item.metadata?.height }}
            </span>
          </div>

          <div class="info-item">
            <span class="label">文件大小</span>
            <span class="value">
              {{ item.metadata?.file_size || '-' }}
            </span>
          </div>

          <div class="info-item">
            <span class="label">上传时间</span>
            <span class="value">
              {{ formatDate(item.created_at) }}
            </span>
          </div>

          <div class="info-item">
            <span class="label">来源</span>
            <span class="value">
              {{ item.metadata?.source || item.metadata?.device || '-' }}
            </span>
          </div>

          <div class="info-item">
            <span class="label">场景</span>
            <span class="value">
              {{ item.metadata?.scene || '-' }}
            </span>
          </div>

          <div class="info-item">
            <span class="label">天气</span>
            <span class="value">
              {{ item.metadata?.weather || '-' }}
            </span>
          </div>

          <div class="info-item">
            <span class="label">采集批次</span>
            <span class="value">
              {{ item.metadata?.batch_id || '-' }}
            </span>
          </div>

          <div class="info-item">
            <span class="label">地理位置</span>
            <span class="value">
              {{ item.metadata?.geo_location || '-' }}
            </span>
          </div>

        </div>
      </el-tab-pane>

      <el-tab-pane label="标注信息" name="annotation">
        <div v-if="!item.bboxes || item.bboxes.length === 0" class="empty-hint">该图片尚未标注</div>
        <div v-else>
          <p class="summary">共 {{ item.bboxes.length }} 个标注框</p>
          <div
            v-for="(b,i) in item.bboxes"
            :key="i"
            class="bbox-card">

            <div class="bbox-header">

                <span class="bbox-cat">

                    {{ categoryName(b.category_id) }}

                </span>

                <span class="bbox-depth">

                    {{ b.depth }} m

                </span>

            </div>

            <div class="bbox-tags">

                <el-tag
                    size="small"
                    type="warning"
                    v-if="b.occlusion!='none'">

                    遮挡：{{ b.occlusion }}

                </el-tag>

                <el-tag
                    size="small"
                    type="info"
                    v-if="b.truncation!='none'">

                    截断：{{ b.truncation }}

                </el-tag>

            </div>

        </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="版本历史" name="versions">
        <div v-if="!versions || versions.length === 0" class="empty-hint">暂无版本记录</div>
        <el-timeline v-else>
          <el-timeline-item v-for="v in versions" :key="v.version_id"
            :timestamp="formatDate(v.created_at)" placement="top">
            <p><strong>v{{ v.version_number }}</strong> — {{ v.change_note }}</p>
          </el-timeline-item>
        </el-timeline>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  item: { type: Object, default: () => ({ metadata: {} }) },
  versions: { type: Array, default: () => [] },
  categoryLabels: { type: Array, default: () => [] },
})

const activeTab = ref('basic')

const modalityMap = { visible: '可见光', infrared: '红外', mmwave: '毫米波', lidar: '激光雷达' }

function formatDate(d) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN')
}
function categoryName(id) {
  const found = props.categoryLabels.find(c => c.id === id)
  return found ? found.name : `类别${id}`
}
</script>

<style scoped>
.info-panel { padding: 4px 0; }
.info-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  transition: .2s;
}

.info-item:hover {
  background: #eef4ff;
  border-color: #bfdbfe;
}

.label {
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
}

.value {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  max-width: 180px;
  text-align: right;
  word-break: break-all;
}
.summary{

margin-bottom:18px;

font-size:14px;

font-weight:600;

color:#475569;

}

.bbox-card{

background:#f8fafc;

border-radius:14px;

padding:14px;

margin-bottom:14px;

border:1px solid #e2e8f0;

transition:.2s;

}

.bbox-card:hover{

border-color:#bfdbfe;

box-shadow:

0 6px 18px rgba(37,99,235,.08);

}

.bbox-header{

display:flex;

justify-content:space-between;

margin-bottom:10px;

}

.bbox-cat{

font-weight:700;

color:#2563eb;

}

.bbox-depth{

color:#475569;

}

.bbox-tags{

display:flex;

gap:8px;

flex-wrap:wrap;

}
:deep(.el-tabs__item){

font-weight:600;

font-size:15px;

}

:deep(.el-tabs__active-bar){

height:3px;

border-radius:3px;

}

:deep(.el-tabs__nav-wrap::after){

background:#e5e7eb;

}
.empty-hint{

padding:50px;

text-align:center;

background:#f8fafc;

border-radius:14px;

border:1px dashed #cbd5e1;

font-size:14px;

color:#94a3b8;

}
:deep(.el-timeline-item__timestamp){

color:#64748b;

font-size:13px;

}

:deep(.el-timeline-item__node){

background:#2563eb;

}
.summary { font-size: 13px; margin-bottom: 10px; color: #374151; }
.bbox-item { display: flex; align-items: center; gap: 10px; padding: 8px 0;
  border-bottom: 1px solid #f3f4f6; font-size: 13px; }
.bbox-cat { font-weight: 600; color: #1e40af; min-width: 60px; }
.bbox-depth { color: #6b7280; }
.bbox-attrs { display: flex; gap: 4px; }
</style>
