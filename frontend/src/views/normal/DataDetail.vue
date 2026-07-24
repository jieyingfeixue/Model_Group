<template>
  <div class="detail-page">
    <div class="back-bar">
      <el-button @click="$router.back()" text>← 返回列表</el-button>
      <span class="nav-hint">← → 键切换图片</span>
    </div>
    <div class="detail-body">
      <div class="preview-area">
        <ImagePreview :image-url="imageUrl" :bboxes="item.bboxes || []"
          :showAnnotations="showAnnotations" :categoryLabels="categoryLabels"
          @toggle-annotations="showAnnotations = $event" />
      </div>
      <div class="info-area">
        <InfoPanel :item="item" :versions="versions" :categoryLabels="categoryLabels" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ImagePreview from '@/components/canvas/ImagePreview.vue'
import InfoPanel from '@/components/common/InfoPanel.vue'
import { getDataDetail, getThumbnailUrl } from '@/api/data'

const route = useRoute()
const router = useRouter()
const item = ref({ meta_info: {} })
const versions = ref([])
const showAnnotations = ref(true)

const imageUrl = computed(() => item.value.resource_id ? `/api/images/${item.value.resource_id}` : '')
const categoryLabels = ref([
  { id: 1, name: '电线杆' }, { id: 2, name: '桥梁' },
  { id: 3, name: '建筑物' }, { id: 4, name: '树木' }, { id: 5, name: '路灯' },
])

const ids = computed(() => {
  const q = route.query.ids
  return q ? q.split(',').map(Number) : []
})

async function loadItem(id) {
  try {
    const { data } = await getDataDetail(id)
    item.value = data
  } catch { /* backend not ready */ }
}

function navigate(dir) {
  const idx = ids.value.indexOf(Number(route.params.id))
  const next = idx + dir
  if (next >= 0 && next < ids.value.length) {
    router.replace({ params: { id: ids.value[next] }, query: route.query })
  }
}

function onKey(e) {
  if (e.key === 'ArrowLeft') navigate(-1)
  if (e.key === 'ArrowRight') navigate(1)
}

onMounted(() => {
  loadItem(route.params.id)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.detail-page { display: flex; flex-direction: column; height: calc(100vh - 60px); padding: 16px 20px; }
.back-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.nav-hint { font-size: 12px; color: #9ca3af; }
.detail-body { display: flex; gap: 16px; flex: 1; min-height: 0; }
.preview-area { flex: 1; min-width: 0; }
.info-area { width: 340px; flex-shrink: 0; background: #fff; border-radius: 8px; padding: 16px; overflow-y: auto; }
</style>
