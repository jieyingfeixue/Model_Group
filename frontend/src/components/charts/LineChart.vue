<template><div ref="chartRef" style="width:100%;height:300px;"></div></template>
<script setup>
import { ref, onMounted, watch } from 'vue'
import * as echarts from 'echarts'
const props = defineProps({ title: String, xData: Array, series: { type: Array, default: () => [] } })
const chartRef = ref(null)
let chart = null
function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    title: { text: props.title, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: props.series.map(s => s.name), bottom: 0 },
    xAxis: { data: props.xData },
    yAxis: {},
    series: props.series.map(s => ({ name: s.name, type: 'line', data: s.data, smooth: true })),
    grid: { top: 40, bottom: 60 },
  })
}
watch(() => [props.xData, props.series], render, { deep: true })
onMounted(render)
</script>
