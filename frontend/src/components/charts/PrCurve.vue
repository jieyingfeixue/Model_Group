<template><div ref="chartRef" style="width:100%;height:300px;"></div></template>
<script setup>
import { ref, onMounted, watch } from 'vue'
import * as echarts from 'echarts'
const props = defineProps({ data: { type: Array, default: () => [] } })
const chartRef = ref(null)
let chart = null
function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'item' },
    legend: { data: props.data.map(d => d.name), bottom: 0 },
    xAxis: { name: 'Recall', max: 1 },
    yAxis: { name: 'Precision', max: 1 },
    series: props.data.map(d => ({
      name: d.name, type: 'line', data: d.points, smooth: true,
    })),
  })
}
watch(() => props.data, render, { deep: true })
onMounted(render)
</script>
