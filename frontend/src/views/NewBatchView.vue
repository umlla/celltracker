<template>
  <div class="panel">
    <div class="panel-head">
      <div>
        <h2>新建培养批次（复苏）</h2>
        <p class="sub">每次复苏创建一个独立批次，可绑定一管在库冻存管，创建后该管自动标记为「已复苏」</p>
      </div>
    </div>

    <div class="new-batch-layout">
      <div class="panel-body">
        <el-form :model="form" label-width="130px" label-position="left">
          <el-form-item label="细胞株" required>
            <el-select v-model="form.cell_line_id" filterable placeholder="选择细胞株" style="width: 100%" @change="onLineChange">
              <el-option v-for="line in lines" :key="line.id" :label="`${line.name}（${line.type || '未分类'}）`" :value="line.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="复苏日期" required>
            <el-date-picker v-model="form.revival_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="来源冻存管">
            <el-select v-model="form.vial_id" clearable placeholder="不绑定，手动填写冻存日期" style="width: 100%" :disabled="!inStockVials.length" @change="onVialChange">
              <el-option
                v-for="vial in inStockVials"
                :key="vial.id"
                :label="`${vial.freeze_date || '—'} | ${vial.location || '无位置'} | ${fmtNum(vial.cell_count)} cells`"
                :value="vial.id"
              />
            </el-select>
            <div class="form-tip" v-if="form.cell_line_id && !inStockVials.length">该细胞株没有状态为「在库」的冻存管</div>
          </el-form-item>
          <el-form-item label="冻存来源日期">
            <el-date-picker v-model="form.source_freeze_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="初始 PD">
            <el-input-number v-model="form.initial_pd" :min="0" :precision="2" :step="0.1" style="width: 100%" />
            <div class="form-tip">原代细胞首次传代前已有的累计群体倍增数，没有可填 0</div>
          </el-form-item>
          <el-form-item label="复苏接种细胞数">
            <el-input-number v-model="form.initial_cell_count" :min="0" :precision="2" :step="0.1" style="width: 100%" />
            <div class="form-tip">用于计算首次传代的 PD（收获 / 复苏接种数）</div>
          </el-form-item>
          <el-form-item label="批次备注">
            <el-input v-model="form.notes" type="textarea" :rows="2" placeholder="可选" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" :disabled="!form.cell_line_id" @click="submit">创建批次</el-button>
            <span class="small faint" style="margin-left: 12px">批次名：{{ previewName }}</span>
          </el-form-item>
        </el-form>
      </div>

      <aside class="side">
        <div class="side-block">
          <div class="dialog-section-title">当前在养批次</div>
          <div v-if="activeBatches.length">
            <div v-for="batch in activeBatches" :key="batch.id" class="side-row">
              <div>
                <div class="side-title">{{ batch.batch_name }}</div>
                <div class="small faint">
                  复苏 {{ batch.revival_date || '—' }} · P{{ batch.current_record?.passage ?? 0 }}
                </div>
              </div>
              <el-tag size="small" effect="plain" :type="statusTagType(batch.current_record?.status)">
                {{ batch.current_record?.status || '—' }}
              </el-tag>
            </div>
          </div>
          <div v-else class="small faint">暂无在养批次</div>
        </div>

        <div class="side-block">
          <div class="dialog-section-title">在库冻存管（{{ inStockVials.length }}）</div>
          <div v-if="inStockVials.length" class="vial-mini-list">
            <div v-for="vial in inStockVials.slice(0, 8)" :key="vial.id" class="side-row">
              <div>
                <div class="side-title">{{ vial.location || '未填写位置' }}</div>
                <div class="small faint">{{ vial.freeze_date || '—' }} · {{ fmtNum(vial.cell_count) }} cells</div>
              </div>
              <span class="mono faint">PD {{ vial.pd ?? '—' }}</span>
            </div>
          </div>
          <div v-else class="small faint">该细胞株暂无在库冻存管</div>
        </div>

        <div class="side-tip">
          <strong>小提示</strong>
          <p>绑定冻存管后，系统会把该管状态改为「已复苏」并关联到新批次；同一管不能重复复苏。</p>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { batchApi, lineApi } from '../api'
import { fmtNum, statusTagType, todayISO } from '../utils'

const router = useRouter()
const lines = ref([])
const vials = ref([])
const activeBatches = ref([])
const saving = ref(false)

const form = ref({
  cell_line_id: null,
  revival_date: todayISO(),
  source_freeze_date: todayISO(),
  vial_id: null,
  initial_pd: 0,
  initial_cell_count: 0,
  notes: '',
})

const selectedLine = computed(() => lines.value.find((line) => line.id === form.value.cell_line_id))
const inStockVials = computed(() => vials.value.filter((vial) => vial.status === '在库'))
const previewName = computed(() => {
  if (!selectedLine.value) return '—'
  const cutoff = (form.value.revival_date || todayISO()).replaceAll('-', '').slice(2, 8)
  return `${selectedLine.value.name}-${cutoff}`
})

async function onLineChange() {
  form.value.vial_id = null
  vials.value = []
  activeBatches.value = []
  if (!form.value.cell_line_id) return
  const [vialList, batchList] = await Promise.all([
    lineApi.vials(form.value.cell_line_id),
    batchApi.list({ cell_line_id: form.value.cell_line_id, is_active: true }),
  ])
  vials.value = vialList
  activeBatches.value = batchList
}

function onVialChange(vialId) {
  const vial = vials.value.find((item) => item.id === vialId)
  if (vial?.freeze_date) form.value.source_freeze_date = vial.freeze_date
}

async function submit() {
  if (!form.value.cell_line_id) return
  saving.value = true
  try {
    const batch = await batchApi.create({ ...form.value })
    ElMessage.success(`已创建批次「${batch.batch_name}」`)
    router.push({ path: '/', query: { mode: 'line', line: form.value.cell_line_id } })
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  lines.value = await lineApi.list()
  const withBatches = lines.value.find((line) => line.active_batch_count > 0)
  form.value.cell_line_id = withBatches?.id || lines.value[0]?.id || null
  if (form.value.cell_line_id) await onLineChange()
})
</script>

<style scoped>
.new-batch-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
}

.side {
  border-left: 1px solid var(--ct-border);
  padding: 18px;
  background: #fbfdfc;
  border-radius: 0 0 var(--ct-radius) 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.side-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.side-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid var(--ct-border);
  border-radius: 9px;
}

.side-title {
  font-size: 12.5px;
  font-weight: 550;
}

.vial-mini-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.side-tip {
  font-size: 12px;
  line-height: 1.6;
  color: var(--ct-muted);
  background: var(--ct-primary-soft);
  border-radius: 10px;
  padding: 12px 14px;
}

.side-tip p {
  margin: 6px 0 0;
}

@media (max-width: 1000px) {
  .new-batch-layout {
    grid-template-columns: 1fr;
  }
  .side {
    border-left: 0;
    border-top: 1px solid var(--ct-border);
    border-radius: 0 0 var(--ct-radius) var(--ct-radius);
  }
}
</style>
