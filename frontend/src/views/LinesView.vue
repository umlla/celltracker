<template>
  <div class="panel">
    <div class="panel-head">
      <div>
        <h2>细胞株管理</h2>
        <p class="sub">共 {{ lines.length }} 株，其中 {{ activeCount }} 株正在培养</p>
      </div>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>添加细胞株
      </el-button>
    </div>

    <div class="panel-body">
      <div class="filter-bar" style="margin-bottom: 14px">
        <el-input v-model="search" placeholder="搜索名称或备注" clearable class="search-input">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <span class="small faint">删除细胞株会同时删除其批次、传代记录、冻存管和分组关系</span>
      </div>

      <el-table :data="filteredLines" size="default" max-height="620">
        <el-table-column label="细胞株" min-width="180">
          <template #default="{ row }">
            <div class="line-cell">
              <span class="dot" :class="{ on: row.active_batch_count > 0 }" />
              <span class="name">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.type === '原代' ? 'warning' : 'info'">{{ row.type || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认间隔" width="92" align="center">
          <template #default="{ row }">{{ row.default_passage_interval ? `${row.default_passage_interval} 天` : '—' }}</template>
        </el-table-column>
        <el-table-column prop="revival_date" label="首次复苏" width="110" />
        <el-table-column label="在养批次" width="90" align="center">
          <template #default="{ row }">
            <span class="badge" :class="{ zero: !row.active_batch_count }">{{ row.active_batch_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="历史批次" width="90" align="center">
          <template #default="{ row }">{{ row.batch_count }}</template>
        </el-table-column>
        <el-table-column label="冻存管" width="100" align="center">
          <template #default="{ row }">{{ row.in_stock_vials }} / {{ row.total_vials }}</template>
        </el-table-column>
        <el-table-column prop="notes" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="$router.push({ path: '/', query: { mode: 'line', line: row.id } })">查看</el-button>
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="removeLine(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑细胞株' : '添加细胞株'" width="min(540px, 94vw)">
      <el-form :model="form" label-width="120px" label-position="left">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="例如 HeLa、1#PWMF-LT" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="永生化" value="永生化" />
            <el-option label="原代" value="原代" />
          </el-select>
        </el-form-item>
        <el-form-item label="首次复苏日期">
          <el-date-picker v-model="form.revival_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="默认传代间隔">
          <el-input-number v-model="form.default_passage_interval" :min="0" :step="1" />
          <span class="small faint" style="margin-left: 8px">天，0 表示不设默认提醒</span>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ editing ? '保存修改' : '添加' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { lineApi } from '../api'
import { loadMeta } from '../store'
import { todayISO } from '../utils'

const lines = ref([])
const search = ref('')
const dialogVisible = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = ref(emptyForm())

const activeCount = computed(() => lines.value.filter((line) => line.active_batch_count > 0).length)
const filteredLines = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return lines.value
  return lines.value.filter(
    (line) =>
      line.name.toLowerCase().includes(keyword) ||
      (line.notes || '').toLowerCase().includes(keyword),
  )
})

function emptyForm() {
  return {
    id: null,
    name: '',
    type: '永生化',
    revival_date: todayISO(),
    default_passage_interval: 0,
    notes: '',
  }
}

async function reload() {
  lines.value = await lineApi.list()
  await loadMeta()
}

function openCreate() {
  editing.value = false
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = true
  form.value = {
    id: row.id,
    name: row.name,
    type: row.type || '永生化',
    revival_date: row.revival_date,
    default_passage_interval: row.default_passage_interval || 0,
    notes: row.notes || '',
  }
  dialogVisible.value = true
}

async function save() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请输入细胞株名称')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await lineApi.update(form.value.id, form.value)
      ElMessage.success('细胞株信息已更新')
    } else {
      await lineApi.create(form.value)
      ElMessage.success('细胞株已添加')
    }
    dialogVisible.value = false
    await reload()
  } finally {
    saving.value = false
  }
}

async function removeLine(row) {
  try {
    await ElMessageBox.confirm(
      `删除「${row.name}」会级联删除 ${row.batch_count} 个批次、其全部传代记录、${row.total_vials} 支冻存管及分组关系，且不可恢复。`,
      '删除细胞株',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await lineApi.remove(row.id)
  ElMessage.success('细胞株已删除')
  await reload()
}

onMounted(reload)
</script>

<style scoped>
.line-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #cfd8d6;
}

.dot.on {
  background: var(--ct-accent);
  box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.14);
}

.name {
  font-weight: 550;
}

.badge {
  display: inline-flex;
  min-width: 24px;
  height: 22px;
  padding: 0 7px;
  border-radius: 999px;
  align-items: center;
  justify-content: center;
  background: var(--ct-primary-soft);
  color: var(--ct-primary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.badge.zero {
  background: #f3f5f5;
  color: var(--ct-faint);
}
</style>
