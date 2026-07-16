<template>
  <el-dialog v-model="visible" title="数据集预览" width="800px" @close="$emit('close')">
    <div class="preview-grid" v-if="samples.length > 0">
      <div v-for="(s, i) in samples" :key="i" class="sample-item">
        <img :src="s.thumb_url || placeholderUrl" @error="e => e.target.src = placeholderUrl" />
        <div class="sample-info">{{ s.name }}</div>
      </div>
    </div>
    <div v-else class="loading-hint">加载样本中...</div>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { getDatasetList } from '@/api/dataset'

const props = defineProps({ modelValue: Boolean, dataset: Object })
const emit = defineEmits(['update:modelValue', 'close'])
const visible = ref(props.modelValue)
const samples = ref([])
const placeholderUrl = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="140" fill="%23e5e7eb"><rect width="200" height="140"/></svg>'

watch(() => props.modelValue, v => { visible.value = v })
watch(visible, v => { if (!v) emit('update:modelValue', false) })

watch(() => props.dataset, async (ds) => {
  if (!ds) return
  try {
    const { data } = await getDatasetList({ dataset_id: ds.dataset_id, preview: true, limit: 8 })
    samples.value = data.items || data.samples || []
  } catch { samples.value = [] }
})
</script>

<style scoped>
.preview-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.sample-item { text-align: center; }
.sample-item img { width: 100%; height: 120px; object-fit: cover; border-radius: 6px; background: #f3f4f6; }
.sample-info { font-size: 11px; color: #6b7280; margin-top: 4px; }
.loading-hint { text-align: center; padding: 40px; color: #9ca3af; }
</style>
