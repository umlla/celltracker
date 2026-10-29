<template>
  <div class="vial-grid">
    <div class="corner" />
    <div v-for="col in detail.cols" :key="`c${col}`" class="axis">{{ col }}</div>
    <template v-for="row in detail.rows" :key="row">
      <div class="axis">{{ row }}</div>
      <div
        v-for="col in detail.cols"
        :key="`${row}${col}`"
        :class="['vial-cell', cellClass(`${row}${col}`)]"
        :title="cellTitle(`${row}${col}`)"
        role="button"
        tabindex="0"
        @click="$emit('hole-click', { hole: `${row}${col}`, vial: detail.holes[`${row}${col}`] || null })"
        @keydown.enter="$emit('hole-click', { hole: `${row}${col}`, vial: detail.holes[`${row}${col}`] || null })"
      >
        <template v-if="detail.holes[`${row}${col}`]">
          <span class="cell-name">{{ detail.holes[`${row}${col}`].cell_name }}</span>
          <span class="row" style="gap: 4px">
            <i class="status-dot" />
            <span style="font-size: 9px">{{ detail.holes[`${row}${col}`].status }}</span>
          </span>
        </template>
        <template v-else>
          <span style="font-size: 16px; line-height: 1">＋</span>
          <span class="hole">{{ row }}{{ col }}</span>
        </template>
      </div>
    </template>
  </div>
</template>

<script setup>
const props = defineProps({
  detail: { type: Object, required: true },
})

defineEmits(['hole-click'])

function cellClass(hole) {
  const vial = props.detail.holes[hole]
  if (!vial) return ''
  return {
    occupied: true,
    revived: vial.status === '已复苏',
    discarded: vial.status === '已丢弃',
  }
}

function cellTitle(hole) {
  const vial = props.detail.holes[hole]
  if (!vial) return `孔位 ${hole}（空闲，点击添加）`
  const parts = [
    vial.cell_name,
    vial.status,
    vial.cell_count ? `${Number(vial.cell_count).toLocaleString()} 细胞` : '',
    vial.freeze_date ? `冻存 ${vial.freeze_date}` : '',
    vial.pd !== null && vial.pd !== undefined ? `PD ${vial.pd}` : '',
  ]
  return `${hole} · ${parts.filter(Boolean).join(' · ')}`
}
</script>
