<template>
  <div class="stat-tile" :style="{ '--tile-tint': tint }">
    <div class="label">
      <el-icon v-if="icon"><component :is="icon" /></el-icon>
      {{ label }}
    </div>
    <div class="value">{{ value }}</div>
    <div v-if="hint" class="hint">{{ hint }}</div>
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  hint: { type: String, default: '' },
  icon: { type: String, default: '' },
  tint: { type: String, default: 'rgba(15, 118, 110, 0.08)' },
})
</script>
