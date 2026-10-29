<template>
  <div class="panel">
    <div class="panel-head" style="align-items: flex-start">
      <div>
        <h2>传代记录</h2>
        <p class="sub">批量录入按组快速填写，单批次录入适合个别操作，按组编辑可修正历史记录</p>
      </div>
    </div>

    <el-tabs v-model="tab" class="records-tabs" @tab-change="onTabChange">
      <!-- ==================== 按组批量录入 ==================== -->
      <el-tab-pane label="按组批量录入" name="group-create">
        <div class="pane-toolbar">
          <el-select v-model="entryGroupId" placeholder="选择细胞组" style="width: 220px" @change="loadEntryRows">
            <el-option v-for="group in groups" :key="group.id" :label="`${group.group_name}（${group.member_count}）`" :value="group.id" />
          </el-select>
          <el-button size="small" @click="loadEntryRows">刷新</el-button>
          <span class="small faint">勾选要提交的行，未勾选的行会被忽略</span>
          <div style="margin-left: auto">
            <el-button type="primary" :loading="submittingEntries" :disabled="!entryRows.length" @click="submitEntries">
              批量提交（{{ selectedEntries.length }}）
            </el-button>
          </div>
        </div>

        <div v-if="entryRows.length" class="pane-body">
          <el-table :data="entryRows" size="small" max-height="560">
            <el-table-column width="44" align="center">
              <template #header>
                <el-checkbox :model-value="allSelected" :indeterminate="someSelected" @change="toggleAll" />
              </template>
              <template #default="{ row }">
                <el-checkbox v-model="row.selected" />
              </template>
            </el-table-column>
            <el-table-column prop="cell_line" label="细胞株" min-width="120" fixed />
            <el-table-column prop="batch_name" label="批次" min-width="140" show-overflow-tooltip />
            <el-table-column label="代次" width="82">
              <template #default="{ row }"><el-input-number v-model="row.passage" :min="1" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="日期" width="132">
              <template #default="{ row }">
                <el-date-picker v-model="row.date" type="date" value-format="YYYY-MM-DD" size="small" style="width: 100%" />
              </template>
            </el-table-column>
            <el-table-column label="收获总数" width="116">
              <template #default="{ row }"><el-input-number v-model="row.harvested_cells" :min="0" :precision="2" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="盘数" width="82">
              <template #default="{ row }"><el-input-number v-model="row.inoculum_dishes" :min="1" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="每盘细胞数" width="112">
              <template #default="{ row }"><el-input-number v-model="row.per_dish_cells" :min="0" :precision="2" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="状态" width="94">
              <template #default="{ row }">
                <el-select v-model="row.status" size="small">
                  <el-option v-for="item in statusChoices" :key="item" :label="item" :value="item" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="间隔天数" width="100">
              <template #default="{ row }"><el-input-number v-model="row.next_passage_days" :min="0" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="备注" min-width="120">
              <template #default="{ row }"><el-input v-model="row.notes" size="small" placeholder="可选" /></template>
            </el-table-column>
          </el-table>
          <div class="pane-hint">收获总数为 0 时 PD 记为 0；每盘细胞数 × 盘数 = 本次接种数。</div>
        </div>
        <div v-else class="empty-hint">
          <span class="icon">🧬</span>{{ entryGroupId ? '该组没有活跃批次，先去新建批次' : '选择一个细胞组开始批量录入' }}
        </div>

        <el-alert v-if="entryResult" :type="entryResult.failed ? 'warning' : 'success'" :closable="true" style="margin: 0 18px 18px" @close="entryResult = null">
          <template #title>成功 {{ entryResult.success }} 条，失败 {{ entryResult.failed }} 条</template>
          <div v-for="item in entryResult.results.filter((r) => !r.ok)" :key="item.index" class="small">
            第 {{ item.index + 1 }} 行：{{ item.error }}
          </div>
        </el-alert>
      </el-tab-pane>

      <!-- ==================== 单批次录入 ==================== -->
      <el-tab-pane label="单批次录入" name="single">
        <div class="pane-body single-layout">
          <div>
            <el-form label-position="top">
              <el-form-item label="细胞株">
                <el-select v-model="singleLineId" filterable placeholder="选择细胞株" style="width: 100%" @change="loadBatches">
                  <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="培养批次">
                <el-select v-model="singleBatchId" placeholder="选择活跃批次" style="width: 100%" :disabled="!batches.length" @change="loadSingleBatch">
                  <el-option v-for="batch in batches" :key="batch.id" :label="batch.batch_name" :value="batch.id" />
                </el-select>
              </el-form-item>
            </el-form>

            <div v-if="singleBatch" class="current-batch">
              <div class="row between">
                <strong>{{ singleBatch.batch_name }}</strong>
                <el-tag size="small" type="info" effect="plain">P{{ singleBatch.current_record?.passage ?? 0 }}</el-tag>
              </div>
              <div class="small muted" style="margin-top: 6px">
                当前累计 PD {{ fmtNum(singleBatch.current_record?.cumulative_pd) }} ·
                上次传代 {{ singleBatch.current_record?.date || '—' }} ·
                建议下次 {{ singleBatch.current_record?.next_passage_date || '未设置' }}
              </div>
            </div>
            <div v-else class="small faint" style="margin-top: 8px">选择批次后可看到当前状态</div>
          </div>

          <div>
            <el-form :model="singleForm" label-width="120px" label-position="left">
              <el-form-item label="传代次数">
                <el-input-number v-model="singleForm.passage" :min="1" :step="1" />
              </el-form-item>
              <el-form-item label="传代日期">
                <el-date-picker v-model="singleForm.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
              </el-form-item>
              <el-form-item label="收获细胞总数">
                <el-input-number v-model="singleForm.harvested_cells" :min="0" :precision="2" :step="0.1" style="width: 100%" />
              </el-form-item>
              <el-form-item label="种下盘数">
                <el-input-number v-model="singleForm.inoculum_dishes" :min="1" :step="1" style="width: 100%" />
              </el-form-item>
              <el-form-item label="每盘细胞数">
                <el-input-number v-model="singleForm.per_dish_cells" :min="0" :precision="2" :step="0.1" style="width: 100%" />
              </el-form-item>
              <el-form-item label="细胞状态">
                <el-select v-model="singleForm.status" style="width: 100%">
                  <el-option v-for="item in statusChoices" :key="item" :label="item" :value="item" />
                </el-select>
              </el-form-item>
              <el-form-item label="建议间隔天数">
                <el-input-number v-model="singleForm.next_passage_days" :min="0" :step="1" style="width: 100%" />
              </el-form-item>
              <el-form-item label="备注">
                <el-input v-model="singleForm.notes" type="textarea" :rows="2" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="submittingSingle" :disabled="!singleBatchId" @click="submitSingle">
                  提交传代记录
                </el-button>
                <span class="small faint" style="margin-left: 10px">接种数 = {{ singleForm.inoculum_dishes }} × {{ singleForm.per_dish_cells }}</span>
              </el-form-item>
            </el-form>
          </div>
        </div>
      </el-tab-pane>

      <!-- ==================== 按组编辑 ==================== -->
      <el-tab-pane label="按组编辑" name="group-edit">
        <div class="pane-toolbar">
          <el-select v-model="editGroupId" placeholder="选择细胞组" style="width: 220px" @change="loadEditRows">
            <el-option v-for="group in groups" :key="group.id" :label="`${group.group_name}（${group.member_count}）`" :value="group.id" />
          </el-select>
          <el-button size="small" @click="loadEditRows">刷新</el-button>
          <span class="small faint">修改后点击保存，系统会按批次重算累计 PD</span>
          <div style="margin-left: auto">
            <el-button type="primary" :loading="savingEdits" :disabled="!editRows.length" @click="saveEdits">保存全部修改</el-button>
          </div>
        </div>

        <div v-if="editRows.length" class="pane-body">
          <el-table :data="editRows" size="small" max-height="560">
            <el-table-column prop="cell_line" label="细胞株" min-width="110" fixed />
            <el-table-column prop="batch_name" label="批次" min-width="130" show-overflow-tooltip />
            <el-table-column label="代次" width="78">
              <template #default="{ row }"><el-input-number v-model="row.passage" :min="1" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="日期" width="130">
              <template #default="{ row }"><el-date-picker v-model="row.date" type="date" value-format="YYYY-MM-DD" size="small" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="收获" width="112">
              <template #default="{ row }"><el-input-number v-model="row.harvested_cells" :min="0" :precision="2" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="盘数" width="80">
              <template #default="{ row }"><el-input-number v-model="row.inoculum_dishes" :min="1" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="每盘" width="108">
              <template #default="{ row }"><el-input-number v-model="row.per_dish_cells" :min="0" :precision="2" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="状态" width="92">
              <template #default="{ row }">
                <el-select v-model="row.status" size="small">
                  <el-option v-for="item in statusChoices" :key="item" :label="item" :value="item" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="间隔天数" width="98">
              <template #default="{ row }"><el-input-number v-model="row.next_passage_days" :min="0" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="备注" min-width="110">
              <template #default="{ row }"><el-input v-model="row.notes" size="small" /></template>
            </el-table-column>
            <el-table-column label="操作" width="70" fixed="right">
              <template #default="{ row }">
                <el-button link type="danger" size="small" @click="removeEditRow(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pane-hint">间隔天数填 0 表示保留该记录原有的建议下次传代日期。</div>
        </div>
        <div v-else class="empty-hint">
          <span class="icon">✏️</span>{{ editGroupId ? '该组没有可编辑的活跃传代记录' : '选择一个细胞组开始编辑' }}
        </div>

        <el-alert v-if="editResult" :type="editResult.failed ? 'warning' : 'success'" style="margin: 0 18px 18px" @close="editResult = null">
          <template #title>成功保存 {{ editResult.success }} 条，失败 {{ editResult.failed }} 条</template>
          <div v-for="item in editResult.results.filter((r) => !r.ok)" :key="item.index" class="small">
            第 {{ item.index + 1 }} 行：{{ item.error }}
          </div>
        </el-alert>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchApi, groupApi, lineApi, recordApi } from '../api'
import { fmtNum, todayISO } from '../utils'

const statusChoices = ['良好', '一般', '较差', '污染']

const groups = ref([])
const lines = ref([])
const tab = ref('group-create')

const entryGroupId = ref(null)
const entryRows = ref([])
const submittingEntries = ref(false)
const entryResult = ref(null)

const singleLineId = ref(null)
const singleBatchId = ref(null)
const batches = ref([])
const singleBatch = ref(null)
const submittingSingle = ref(false)
const singleForm = ref(defaultSingleForm())

const editGroupId = ref(null)
const editRows = ref([])
const savingEdits = ref(false)
const editResult = ref(null)

const selectedEntries = computed(() => entryRows.value.filter((row) => row.selected))
const allSelected = computed(() => entryRows.value.length > 0 && selectedEntries.value.length === entryRows.value.length)
const someSelected = computed(() => selectedEntries.value.length > 0 && !allSelected.value)

function defaultSingleForm() {
  return {
    passage: 1,
    date: todayISO(),
    harvested_cells: 0,
    inoculum_dishes: 1,
    per_dish_cells: 0,
    status: '良好',
    next_passage_days: 0,
    notes: '',
  }
}

function toggleAll(value) {
  entryRows.value.forEach((row) => {
    row.selected = value
  })
}

async function loadEntryRows() {
  entryResult.value = null
  if (!entryGroupId.value) {
    entryRows.value = []
    return
  }
  const statusRows = await groupApi.status(entryGroupId.value)
  entryRows.value = statusRows.map((row) => ({
    batch_id: row.batch_id,
    cell_line: row.cell_name,
    batch_name: row.batch_name,
    selected: true,
    passage: (row.passage || 0) + 1,
    date: todayISO(),
    harvested_cells: 0,
    inoculum_dishes: 1,
    per_dish_cells: 0,
    status: '良好',
    next_passage_days: row.default_passage_interval || 0,
    notes: '',
  }))
}

async function submitEntries() {
  const rows = selectedEntries.value
  if (!rows.length) {
    ElMessage.warning('请至少勾选一行')
    return
  }
  submittingEntries.value = true
  try {
    const entries = rows.map((row) => ({
      batch_id: row.batch_id,
      passage: row.passage,
      date: row.date,
      harvested_cells: row.harvested_cells,
      inoculum_dishes: row.inoculum_dishes,
      per_dish_cells: row.per_dish_cells,
      status: row.status,
      next_passage_days: row.next_passage_days,
      notes: row.notes,
    }))
    entryResult.value = await recordApi.bulkCreate(entries)
    if (!entryResult.value.failed) ElMessage.success('传代记录已提交')
    await loadEntryRows()
  } finally {
    submittingEntries.value = false
  }
}

async function loadBatches() {
  singleBatchId.value = null
  singleBatch.value = null
  batches.value = []
  if (!singleLineId.value) return
  const data = await batchApi.list({ cell_line_id: singleLineId.value, is_active: true })
  batches.value = data
  if (data.length) {
    singleBatchId.value = data[0].id
    await loadSingleBatch()
  }
}

async function loadSingleBatch() {
  if (!singleBatchId.value) {
    singleBatch.value = null
    return
  }
  const detail = await batchApi.detail(singleBatchId.value)
  singleBatch.value = detail.batch
  const current = detail.batch?.current_record
  singleForm.value = {
    ...defaultSingleForm(),
    passage: (current?.passage || 0) + 1,
    next_passage_days: detail.cell_line?.default_passage_interval || 0,
  }
}

async function submitSingle() {
  if (!singleBatchId.value) return
  submittingSingle.value = true
  try {
    await recordApi.create({ batch_id: singleBatchId.value, ...singleForm.value })
    ElMessage.success('传代记录已添加')
    await loadSingleBatch()
    singleForm.value = {
      ...singleForm.value,
      harvested_cells: 0,
      per_dish_cells: 0,
      notes: '',
      passage: (singleBatch.value?.current_record?.passage || 0) + 1,
      date: todayISO(),
    }
  } finally {
    submittingSingle.value = false
  }
}

async function loadEditRows() {
  editResult.value = null
  if (!editGroupId.value) {
    editRows.value = []
    return
  }
  const records = await groupApi.records(editGroupId.value)
  editRows.value = records.map((row) => ({
    id: row.id,
    batch_id: row.batch_id,
    cell_line: row.cell_line,
    batch_name: row.batch_name,
    passage: row.passage,
    date: row.date,
    harvested_cells: row.harvested_cells,
    inoculum_dishes: row.inoculum_dishes,
    per_dish_cells: row.per_dish_cells,
    status: row.status,
    next_passage_days: 0,
    notes: row.notes || '',
  }))
}

async function saveEdits() {
  savingEdits.value = true
  try {
    const entries = editRows.value.map((row) => ({
      id: row.id,
      passage: row.passage,
      date: row.date,
      harvested_cells: row.harvested_cells,
      inoculum_dishes: row.inoculum_dishes,
      per_dish_cells: row.per_dish_cells,
      status: row.status,
      next_passage_days: row.next_passage_days,
      notes: row.notes,
    }))
    editResult.value = await recordApi.bulkUpdate(entries)
    if (!editResult.value.failed) ElMessage.success('修改已保存，累计 PD 已重算')
    await loadEditRows()
  } finally {
    savingEdits.value = false
  }
}

async function removeEditRow(row) {
  try {
    await ElMessageBox.confirm(
      `删除 ${row.cell_line} · ${row.batch_name} 的 P${row.passage}（${row.date}）记录？`,
      '删除记录',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await recordApi.remove(row.id)
  ElMessage.success('记录已删除')
  await loadEditRows()
}

async function onTabChange(name) {
  if (name === 'single' && singleLineId.value && !batches.value.length) {
    await loadBatches()
  }
  if (name === 'group-edit' && editGroupId.value && !editRows.value.length) {
    await loadEditRows()
  }
}

onMounted(async () => {
  const [groupList, lineList] = await Promise.all([groupApi.list(), lineApi.list()])
  groups.value = groupList
  lines.value = lineList
  const withActivity = groupList.find((group) =>
    (group.members || []).some((member) => member.active_batch_count > 0),
  )
  const defaultGroup = withActivity?.id || groupList[0]?.id || null
  entryGroupId.value = defaultGroup
  editGroupId.value = defaultGroup
  if (entryGroupId.value) await loadEntryRows()
  if (editGroupId.value) await loadEditRows()

  const withBatches = lineList.find((line) => line.active_batch_count > 0)
  singleLineId.value = withBatches?.id || lineList[0]?.id || null
  if (singleLineId.value) await loadBatches()
})
</script>

<style scoped>
.records-tabs {
  padding: 0 18px 4px;
}

.pane-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 0 14px;
}

.pane-body {
  padding-bottom: 16px;
}

.pane-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--ct-faint);
}

.single-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 28px;
  align-items: start;
}

.current-batch {
  border: 1px solid var(--ct-border);
  background: #fbfdfc;
  border-radius: 12px;
  padding: 12px 14px;
}

@media (max-width: 900px) {
  .single-layout {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}
</style>
