<template><div ref="chartRef" style="width:100%;height:350px;"></div></template>
<script setup>
import { ref, onMounted, watch } from 'vue'
import * as echarts from 'echarts'
const props = defineProps({ data: { type: Array, default: () => [] }, labels: { type: Array, default: () => [] } })
const chartRef = ref(null)
let chart = null
function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { position: 'top' },
    xAxis: { data: props.labels, axisLabel: { rotate: 45 } },
    yAxis: { data: props.labels },
    visualMap: { min: 0, max: Math.max(...(props.data.flat() || [1])), calculable: true, orient: 'vertical', left: 'right' },
    series: [{ type: 'heatmap', data: props.data.flatMap((row, i) => row.map((v, j) => [j, i, v])), label: { show: true } }],
  })
}
watch(() => [props.data, props.labels], render, { deep: true })
onMounted(render)
</script>
