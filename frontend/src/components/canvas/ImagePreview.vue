<template>
  <div class="image-preview" ref="container">
    <div class="toolbar">
      <span class="zoom-label">{{ Math.round(zoom * 100) }}%</span>
      <div class="toolbar">

  <div class="toolbar-left">

    <span class="zoom-label">

      🔍 {{ Math.round(zoom * 100) }}%

    </span>

  </div>

  <div class="toolbar-right">

    <el-button
      size="small"
      @click="fitToScreen"
    >
      适应窗口
    </el-button>

    <el-button
      size="small"
      @click="zoomTo(1)"
    >
      原始尺寸
    </el-button>

    <el-button
      size="small"
      type="primary"
      plain
      v-if="showAnnotations"
      @click="$emit('toggle-annotations', false)"
    >
      隐藏标注
    </el-button>

    <el-button
      size="small"
      type="primary"
      @click="$emit('toggle-annotations', true)"
      v-else
    >
      显示标注
    </el-button>

  </div>

</div>
    </div>
    <div class="canvas-area" ref="canvasArea">
      <canvas ref="canvas" @wheel="onWheel" @mousedown="onMouseDown"
        @mousemove="onMouseMove" @mouseup="onMouseUp" @mouseleave="onMouseUp" />
      <div v-if="!loaded" class="loading">加载中...</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'

const props = defineProps({
  imageUrl: String,
  bboxes: { type: Array, default: () => [] },
  showAnnotations: { type: Boolean, default: true },
  categoryLabels: { type: Array, default: () => [] },
})
defineEmits(['toggle-annotations'])

const container = ref(null)
const canvasArea = ref(null)
const canvas = ref(null)
const loaded = ref(false)
const zoom = ref(1)
const panX = ref(0), panY = ref(0)
let img = null, dragging = false, dragStart = { x: 0, y: 0 }

function loadImage() {
  if (!props.imageUrl) return
  loaded.value = false
  img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => { loaded.value = true; fitToScreen() }
  img.onerror = () => { loaded.value = false }
  img.src = props.imageUrl
}

function fitToScreen() {
  if (!img || !canvasArea.value) return
  const areaW = canvasArea.value.clientWidth
  const areaH = canvasArea.value.clientHeight
  zoom.value = Math.min(areaW / img.width, areaH / img.height, 2)
  panX.value = (areaW - img.width * zoom.value) / 2
  panY.value = (areaH - img.height * zoom.value) / 2
  draw()
}

function zoomTo(z) { zoom.value = z; panX.value = 0; panY.value = 0; draw() }

function onWheel(e) {
  e.preventDefault()
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  zoom.value = Math.max(0.1, Math.min(5, zoom.value + delta))
  draw()
}

function onMouseDown(e) {
  dragging = true
  dragStart = { x: e.clientX - panX.value, y: e.clientY - panY.value }
}
function onMouseMove(e) {
  if (!dragging) return
  panX.value = e.clientX - dragStart.x
  panY.value = e.clientY - dragStart.y
  draw()
}
function onMouseUp() { dragging = false }

function draw() {
  if (!canvas.value || !img) return
  const ctx = canvas.value.getContext('2d')
  const w = canvas.value.width = canvasArea.value?.clientWidth || 800
  const h = canvas.value.height = canvasArea.value?.clientHeight || 500
  ctx.clearRect(0, 0, w, h)
  ctx.save()
  ctx.translate(panX.value, panY.value)
  ctx.scale(zoom.value, zoom.value)
  ctx.drawImage(img, 0, 0)
  // draw annotation boxes
  if (props.showAnnotations && props.bboxes.length > 0) {
    props.bboxes.forEach(b => {
      const x = b.x * img.width
      const y = b.y * img.height
      const bw = b.w * img.width
      const bh = b.h * img.height
      ctx.strokeStyle = '#3b82f6'
      ctx.lineWidth = 2 / zoom.value
      ctx.strokeRect(x, y, bw, bh)
      const catName = props.categoryLabels.find(c => c.id === b.category_id)?.name || ''
      const label = catName ? `${catName} ${b.depth || ''}m`.trim() : `${b.depth || ''}m`
      ctx.fillStyle = '#3b82f6'
      ctx.font = `${Math.max(12, 14 / zoom.value)}px sans-serif`
      ctx.fillText(label, x, y > 20 ? y - 4 : y + bh + 14)
    })
  }
  ctx.restore()
}

watch(() => props.imageUrl, loadImage)
watch(() => [props.bboxes, props.showAnnotations], draw, { deep: true })

onMounted(() => { loadImage(); window.addEventListener('resize', draw) })
onBeforeUnmount(() => { window.removeEventListener('resize', draw) })
</script>

<style scoped>
.image-preview{

display:flex;

flex-direction:column;

height:100%;

background:#ffffff;

border-radius:18px;

overflow:hidden;

border:1px solid #e2e8f0;

box-shadow:

0 8px 22px rgba(15,23,42,.05);

}
.toolbar{

display:flex;

justify-content:space-between;

align-items:center;

padding:14px 20px;

background:#f8fafc;

border-bottom:1px solid #e2e8f0;

}
.toolbar-left{

display:flex;

align-items:center;

gap:10px;

}

.toolbar-right{

display:flex;

gap:10px;

}
.toolbar button { font-size: 12px; padding: 4px 10px; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; background: transparent; color: #ccc; cursor: pointer; }
.toolbar button:hover { background: rgba(255,255,255,0.1); }
.zoom-label{

font-size:14px;

font-weight:600;

color:#2563eb;

padding:6px 12px;

background:#dbeafe;

border-radius:20px;

}
.canvas-area{

flex:1;

position:relative;

overflow:hidden;

background:

linear-gradient(
135deg,
#f8fafc,
#eef2ff
);

}
canvas{

display:block;

width:100%;

height:100%;

cursor:grab;

}
canvas:active { cursor: grabbing; }
.loading{

position:absolute;

left:50%;

top:50%;

transform:translate(-50%,-50%);

padding:16px 24px;

background:white;

border-radius:12px;

box-shadow:

0 8px 24px rgba(0,0,0,.08);

color:#64748b;

font-size:14px;

}
</style>
