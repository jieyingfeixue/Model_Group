<template><div ref="chartRef" style="width:100%;height:300px;"></div></template>
<script setup>
import { ref, onMounted, watch } from 'vue'
import * as echarts from 'echarts'
const props = defineProps({ title: String, labels: Array, values: Array })
const chartRef = ref(null)
let chart = null
function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    title: { text: props.title, left: 'center', textStyle: { fontSize: 14 } },
    xAxis: { data: props.labels, axisLabel: { rotate: 30 } },
    yAxis: {},
    series: [{ type: 'bar', data: props.values, itemStyle: { color: '#3b82f6' } }],
    grid: { top: 40, bottom: 60 },
  })
}
watch(() => [props.labels, props.values], render)
onMounted(render)
</script>
