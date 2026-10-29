<template>
  <div ref="host" class="chart-host chart-box" :style="{ height }" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '320px' },
})

const host = ref(null)
let chart = null
let observer = null

function render() {
  if (chart) chart.setOption(props.option, true)
}

onMounted(() => {
  chart = echarts.init(host.value)
  render()
  observer = new ResizeObserver(() => chart && chart.resize())
  observer.observe(host.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>
