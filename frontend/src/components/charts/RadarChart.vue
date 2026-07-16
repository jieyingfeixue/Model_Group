<template><div ref="chartRef" style="width:100%;height:380px;"></div></template>
<script setup>
import { ref, onMounted, watch } from 'vue'
import * as echarts from 'echarts'
const props = defineProps({ indicators: { type: Array, default: () => [] }, series: { type: Array, default: () => [] } })
const chartRef = ref(null)
let chart = null
function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    legend: { data: props.series.map(s => s.name), bottom: 0 },
    radar: { indicator: props.indicators },
    series: [{ type: 'radar', data: props.series.map(s => ({ name: s.name, value: s.values })) }],
  })
}
watch(() => [props.indicators, props.series], render, { deep: true })
onMounted(render)
</script>
