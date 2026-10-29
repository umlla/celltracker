<template>
  <div class="tools-layout">
    <div class="panel">
      <div class="panel-head">
        <div>
          <h2>数据库状态</h2>
          <p class="sub">旧版 cell_data.db 已迁移到新版数据目录，Schema 与旧版兼容</p>
        </div>
        <el-button size="small" @click="reloadAll">刷新</el-button>
      </div>
      <div class="panel-body">
        <div class="kv-grid">
          <div class="kv"><span>数据库文件</span><b class="mono">{{ meta?.database || '—' }}</b></div>
          <div class="kv"><span>大小</span><b>{{ formatBytes(audit?.size_bytes) }}</b></div>
          <div class="kv"><span>Schema 版本</span><b>v{{ meta?.schema_version }}</b></div>
          <div class="kv"><span>迁移来源</span><b class="mono">{{ audit?.meta?.migrated_from || '—' }}</b></div>
          <div class="kv"><span>迁移时间</span><b>{{ audit?.meta?.migrated_at || '—' }}</b></div>
          <div class="kv">
            <span>迁移校验</span>
            <b>
              <el-tag v-if="migration" :type="migration.checksums_equal ? 'success' : 'danger'" size="small" effect="light">
                {{ migration.checksums_equal ? '逐表校验和一致' : '校验不一致' }}
              </el-tag>
              <span v-else class="faint">无迁移记录</span>
            </b>
          </div>
        </div>

        <div class="count-grid">
          <div v-for="(count, table) in audit?.counts || {}" :key="table" class="count-tile">
            <span>{{ tableLabels[table] || table }}</span>
            <b>{{ count }}</b>
          </div>
        </div>

        <el-collapse v-if="migration" style="margin-top: 14px">
          <el-collapse-item title="查看迁移报告详情" name="report">
            <div class="small">
              <div>状态：{{ migration.status }} · PD 偏差 {{ migration.pd_mismatch_count ?? 0 }} 条 · 校验和一致：{{ migration.checksums_equal ? '是' : '否' }}</div>
              <div>源数据库：<span class="mono">{{ migration.source }}</span></div>
              <div v-if="migration.report_path">报告路径：<span class="mono">{{ migration.report_path }}</span></div>
              <div v-if="meta?.migration?.counts" style="margin-top: 6px">
                表行数：
                <span v-for="(value, key) in meta.migration.counts" :key="key" style="margin-right: 10px">
                  {{ tableLabels[key] || key }} {{ value }}
                </span>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <h2>数据体检</h2>
          <p class="sub">检查外键、活跃记录标记与累计 PD 是否符合计算规则</p>
        </div>
        <el-button size="small" type="primary" :loading="recalculating" @click="recalculate">修复累计 PD</el-button>
      </div>
      <div class="panel-body">
        <div class="health-row">
          <el-tag :type="health.type" effect="light" size="large">{{ health.label }}</el-tag>
          <span class="small muted">共检查 {{ audit?.pd_audit?.records_checked ?? 0 }} 条传代记录</span>
        </div>
        <div class="health-items">
          <div class="health-item">
            <span>数据完整性问题</span>
            <b :class="audit?.issues?.length ? 'bad' : 'ok'">{{ audit?.issues?.length || 0 }} 项</b>
          </div>
          <div class="health-item">
            <span>PD 计算偏差</span>
            <b :class="audit?.pd_audit?.mismatch_count ? 'bad' : 'ok'">{{ audit?.pd_audit?.mismatch_count || 0 }} 条</b>
          </div>
          <div class="health-item">
            <span>活跃记录异常</span>
            <b :class="audit?.active_record_problems?.length ? 'bad' : 'ok'">{{ audit?.active_record_problems?.length || 0 }} 项</b>
          </div>
        </div>
        <div v-if="audit?.issues?.length" class="issue-list">
          <div v-for="issue in audit.issues" :key="issue" class="small bad">· {{ issue }}</div>
        </div>
        <div class="small faint" style="margin-top: 10px">
          「修复累计 PD」会按旧版规则重算全部批次：单次 PD = log2(收获 / 上次接种)，累计 PD 只累加正数。
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <h2>备份与恢复</h2>
          <p class="sub">备份使用 SQLite 在线快照，可在服务运行时安全下载</p>
        </div>
        <el-button size="small" type="primary" @click="downloadBackup">下载当前数据库</el-button>
      </div>
      <div class="panel-body">
        <div class="action-grid">
          <div class="action-card">
            <div class="dialog-section-title">恢复备份</div>
            <p class="small muted">上传之前下载的 .db 文件，替换当前数据库（会先自动备份当前库）。</p>
            <el-upload :auto-upload="false" :limit="1" accept=".db,.sqlite,.sqlite3" :on-change="onRestoreFileChange" :on-remove="resetRestoreFile">
              <el-button size="small">选择备份文件</el-button>
            </el-upload>
            <el-button size="small" type="danger" plain :disabled="!restoreFile" :loading="restoring" style="margin-top: 8px" @click="restore">
              上传并恢复
            </el-button>
          </div>

          <div class="action-card">
            <div class="dialog-section-title">导入旧版数据库</div>
            <p class="small muted">从另一台电脑或旧版 Streamlit 应用导入 cell_data.db，自动补齐新表结构并生成迁移报告。</p>
            <el-upload :auto-upload="false" :limit="1" accept=".db,.sqlite,.sqlite3" :on-change="onLegacyFileChange" :on-remove="resetLegacyFile">
              <el-button size="small">选择旧版 .db</el-button>
            </el-upload>
            <el-button size="small" type="primary" plain :disabled="!legacyFile" :loading="importingLegacy" style="margin-top: 8px" @click="importLegacy">
              导入并校验
            </el-button>
          </div>

          <div class="action-card">
            <div class="dialog-section-title">导出全量 Excel</div>
            <p class="small muted">导出细胞株、批次、传代记录、冻存管、细胞组为多 Sheet 工作簿。</p>
            <el-button size="small" @click="exportAll">下载 Excel</el-button>
          </div>
        </div>

        <div class="dialog-section-title" style="margin-top: 20px">已有备份（最近 {{ backups.length }} 份）</div>
        <el-table :data="backups" size="small" max-height="220">
          <el-table-column prop="name" label="文件名" min-width="240" show-overflow-tooltip />
          <el-table-column label="大小" width="100" align="right">
            <template #default="{ row }">{{ formatBytes(row.size) }}</template>
          </el-table-column>
          <el-table-column prop="modified" label="修改时间" width="170" />
        </el-table>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div>
          <h2>登录认证（预留）</h2>
          <p class="sub">当前为单用户本地模式；如需局域网多人使用，可开启用户名密码登录</p>
        </div>
        <el-tag :type="meta?.auth?.enabled ? 'success' : 'info'" effect="light">
          {{ meta?.auth?.enabled ? '已启用' : '未启用' }}
        </el-tag>
      </div>
      <div class="panel-body">
        <ol class="auth-steps">
          <li>编辑项目根目录的 <code>config.json</code>，把 <code>auth.enabled</code> 改为 <code>true</code>，并重启服务。</li>
          <li>首次开启会自动创建账号 <code>{{ meta?.auth?.bootstrap_username || 'admin' }}</code>（密码在 config.json 的 <code>bootstrap_password</code>）。</li>
          <li>登录后可在命令行修改密码：<code>python -m backend.auth set-password --username admin --password 新密码</code></li>
        </ol>
        <pre class="config-sample">{
  "host": "0.0.0.0",
  "port": 18600,
  "auth": { "enabled": true }
}</pre>
        <p class="small faint">
          提示：未启用认证时默认只监听 127.0.0.1。若要让同事通过局域网访问，请同时把 host 改为 0.0.0.0 并开启认证。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { metaApi } from '../api'
import { loadMeta, store } from '../store'
import { downloadUrl } from '../utils'

const meta = ref(store.meta)
const audit = ref(null)
const migration = ref(null)
const backups = ref([])
const recalculating = ref(false)
const restoreFile = ref(null)
const restoring = ref(false)
const legacyFile = ref(null)
const importingLegacy = ref(false)

const tableLabels = {
  cell_lines: '细胞株',
  culture_batches: '培养批次',
  culture_records: '传代记录',
  frozen_vials: '冻存管',
  cell_groups: '细胞组',
  cell_group_members: '组成员',
}

const health = computed(() => {
  if (!audit.value) return { type: 'info', label: '检查中' }
  const issues = audit.value.issues?.length || 0
  const pd = audit.value.pd_audit?.mismatch_count || 0
  const active = audit.value.active_record_problems?.length || 0
  if (issues || pd || active) return { type: 'warning', label: '发现需要关注的问题' }
  return { type: 'success', label: '数据健康，未发现问题' }
})

function formatBytes(bytes) {  if (!bytes && bytes !== 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

async function reloadAll() {
  meta.value = await metaApi.meta()
  store.meta = meta.value
  const [auditData, report, backupList] = await Promise.all([
    metaApi.audit(),
    metaApi.migrationReport(),
    metaApi.backups(),
  ])
  audit.value = auditData
  migration.value = report
  backups.value = backupList
}

function onRestoreFileChange(file) {
  restoreFile.value = file.raw
}

function resetRestoreFile() {
  restoreFile.value = null
}

function onLegacyFileChange(file) {
  legacyFile.value = file.raw
}

function resetLegacyFile() {
  legacyFile.value = null
}

function downloadBackup() {
  downloadUrl('/api/maintenance/backup')
}

async function recalculate() {
  try {
    await ElMessageBox.confirm('按当前规则重算全部批次的单次与累计 PD？此操作会覆盖数据库中的 PD 字段。', '修复累计 PD', {
      type: 'warning',
      confirmButtonText: '开始重算',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  recalculating.value = true
  try {
    const result = await metaApi.recalculate()
    ElMessage.success(`已重算 ${result.batches} 个批次`)
    await reloadAll()
  } finally {
    recalculating.value = false
  }
}

async function restore() {
  if (!restoreFile.value) return
  try {
    await ElMessageBox.confirm('恢复会替换当前数据库（先自动备份当前库），确定继续？', '恢复备份', {
      type: 'warning',
      confirmButtonText: '恢复',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  restoring.value = true
  try {
    const formData = new FormData()
    formData.append('file', restoreFile.value)
    const result = await metaApi.restore(formData)
    ElMessage.success(`已恢复数据库；原库备份：${result.previous_backup || '无'}`)
    restoreFile.value = null
    await reloadAll()
  } finally {
    restoring.value = false
  }
}

async function importLegacy() {
  if (!legacyFile.value) return
  try {
    await ElMessageBox.confirm('导入会替换当前数据库（先自动备份当前库），并生成迁移校验报告，确定继续？', '导入旧版数据库', {
      type: 'warning',
      confirmButtonText: '导入',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  importingLegacy.value = true
  try {
    const formData = new FormData()
    formData.append('file', legacyFile.value)
    const report = await metaApi.importLegacy(formData)
    const pdMismatch = report.pd_audit?.mismatch_count ?? 0
    ElMessage.success(`导入完成：${Object.values(report.target_counts || {}).reduce((a, b) => a + b, 0)} 条记录，PD 偏差 ${pdMismatch} 条`)
    legacyFile.value = null
    await reloadAll()
  } finally {
    importingLegacy.value = false
  }
}

function exportAll() {
  downloadUrl('/api/export/full')
}

onMounted(reloadAll)
</script>

<style scoped>
.tools-layout {
  display: grid;
  gap: 16px;
}

.kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 22px;
}

.kv {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  font-size: 12.5px;
  border-bottom: 1px dashed var(--ct-border);
  padding-bottom: 8px;
  min-width: 0;
}

.kv span {
  color: var(--ct-faint);
  white-space: nowrap;
  font-size: 11.5px;
}

.kv b {
  font-weight: 500;
  overflow-wrap: anywhere;
  text-align: left;
  max-width: 100%;
}

.count-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.count-tile {
  background: #f8fbfa;
  border: 1px solid var(--ct-border);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.count-tile span {
  font-size: 11px;
  color: var(--ct-faint);
}

.count-tile b {
  font-size: 19px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.health-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.health-items {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.health-item {
  border: 1px solid var(--ct-border);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 12.5px;
  color: var(--ct-muted);
}

.health-item b.ok { color: var(--ct-success); }
.health-item b.bad { color: var(--ct-danger); }
.bad { color: var(--ct-danger); }

.issue-list {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 9px;
  background: #fff7f6;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.action-card {
  border: 1px solid var(--ct-border);
  border-radius: 11px;
  padding: 14px;
  background: #fbfdfc;
}

.auth-steps {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.9;
  color: var(--ct-muted);
}

.auth-steps code,
.config-sample {
  background: #f2f7f6;
  padding: 1px 6px;
  border-radius: 5px;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
}

.config-sample {
  margin-top: 12px;
  padding: 12px 14px;
  line-height: 1.6;
  overflow-x: auto;
}

@media (max-width: 1000px) {
  .count-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .action-grid,
  .health-items {
    grid-template-columns: 1fr;
  }
  .kv-grid {
    grid-template-columns: 1fr;
  }
}
</style>
