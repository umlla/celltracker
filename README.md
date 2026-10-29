# 🧬 CellTracker v4 · 细胞培养追踪系统

用 **Flask + Vue 3** 重写的细胞培养管理工具。既能在一台电脑上单机使用，也可以在局域网内多人共享；旧版 Streamlit 的 `cell_data.db` 可以直接迁移，**原有 id、批次、传代记录、冻存管、细胞组关系全部保留**。

- 后端：Flask 3 + SQLite（沿用旧版表结构）+ openpyxl
- 前端：Vue 3 + Vite + Element Plus + ECharts
- 部署：源码 + `start.bat` 双击启动，无需 Docker

---

## ✨ 功能一览

| 模块 | 能力 |
| --- | --- |
| 在养总览 | 在养细胞株/批次/待传代数/在库冻存管统计；按细胞株或按细胞组切换；批次当前盘数、细胞数、累计 PD、传代倒计时；点击「需要传代」可查看具体细胞、所属分组和剩余天数 |
| 生长曲线 | 每个批次的双 Y 轴曲线（累计 PD / 单次 PD / 收获细胞数，右轴对数）；组内多批次曲线；按起始日期标准化对比；已终止批次虚线加入 |
| 传代记录 | 按组批量录入（表格勾选）、单批次录入、按组批量编辑、单条记录编辑/删除，保存后自动重算整批 PD |
| 在养页新增冻存管 | 在「在养细胞 → 冻存状态」点「＋新增冻存管」，自动带出当天日期和当前累计 PD；可直接从历史传代记录中选择某一代的 PD（累计/本次可切换），补录之前冻存的细胞；只需填每管细胞数（×10⁵）和复管数；原代必填 PD，永生化可选；位置可留空后补 |
| 培养批次 | 复苏建批次、绑定在库冻存管（自动标记「已复苏」）、终止批次、删除批次、导出 CSV |
| 冻存管 | 9×9 冻存盒网格点选、搜索编辑删除、Excel 按 Sheet 导入、清空盒子、待补位置筛选 |
| 细胞株 | 新增/编辑/删除，类型（永生化/原代）、默认传代间隔、冻存状态汇总 |
| 细胞组 | 创建分组、成员增删与排序、组内批量终止/批量建批次、状态表红黄绿提醒、组内速率对比、整组 Excel 导出 |
| 数据安全 | 一键下载数据库快照、上传恢复（自动备份当前库）、旧库导入并生成校验报告、PD 修复、全量 Excel 导出 |
| 认证 | 默认单用户免登录；在 `config.json` 打开 `auth.enabled` 即启用用户名密码登录（接口层已预留，含会话与用户表） |

---

## 🚀 快速启动

1. 安装 **Python 3.10+**（推荐 3.11/3.12/3.13）；首次构建前端还需要 **Node.js 20+**。
2. 双击桌面上的 **「CellTracker 细胞培养追踪」** 快捷方式，或项目根目录的 **`start.bat`**。
3. 脚本会自动：
   - 创建 `.venv` 并安装后端依赖；
   - 首次运行时 `npm install && npm run build` 构建前端；
   - 启动服务并打开 <http://127.0.0.1:18600>。

> 快捷方式指向 `start.bat`，图标为 `assets/app.ico`。如果移动了项目目录，右键快捷方式 →「属性」把目标和工作目录改到新路径即可。

> 只在本机使用无需任何配置。要让同事通过局域网访问，把 `config.json` 里的 `"host"` 改成 `"0.0.0.0"`，重启后在启动窗口查看局域网地址。

### 手动启动（开发或排错）

```powershell
# 后端
.\.venv\Scripts\python.exe -m backend.serve --no-browser

# 前端开发模式（另开终端，热更新）
cd frontend
npm run dev        # http://localhost:5173 ，/api 自动代理到 18600
```

其他启动参数：

```powershell
python -m backend.serve --host 0.0.0.0 --port 18600 --no-browser
```

---

## 📦 从旧版迁移数据

### 自动迁移（推荐）

首次启动时，如果 `data/cell_data.db` 不存在而项目根目录有旧版 `cell_data.db`，系统会自动：

1. 用 SQLite 在线备份 API 整库复制（保留所有 id 与外键关系）；
2. 补齐新版本辅助表与索引（`sort_order` 等）；
3. 逐表计算 SHA256 校验和，对比源库与目标库；
4. 用当前规则重算全体记录的单次/累计 PD 做**只读**体检；
5. 把报告写到 `data/migration-report.json`，并在「数据与工具」页展示。

旧库文件不会被修改或删除。

### 手动迁移 / 从另一台电脑导入

```powershell
# 命令行迁移（目标已存在时加 --force，会先备份）
python -m backend.migrate --source cell_data.db --target data/cell_data.db --force

# 仅迁移并重算 PD（可选，历史数据有偏差时用）
python -m backend.migrate --source cell_data.db --target data/cell_data.db --force --fix-pd
```

也可以打开「数据与工具 → 导入旧版数据库」直接上传 `.db` 文件，系统会先备份当前库，再替换并生成报告。

### 迁移校验内容

- 6 张核心表的行数完全一致
- 按源库列集合逐表比对的 SHA256 校验和一致
- 外键孤儿、同批次多条活跃记录、已终止批次活跃记录等完整性问题
- 556 条记录（示例库）的 PD 与当前公式偏差数；示例数据实测为 **0 条偏差**

迁移报告示例字段：`source_counts`、`target_counts`、`checksums_equal`、`pd_audit`、`active_record_problems`、`status`。

### 回滚

- 迁移前的原始库仍然在项目根目录：`cell_data.db`
- 每次恢复/导入/迁移前，系统会自动在 `backups/` 留一份 `*-before-*.db`
- 旧版 Streamlit 文件（`cell_tracker.py`、`run.py`）保留未动，可继续 `streamlit run cell_tracker.py` 使用旧版

> ⚠️ 不要同时用旧版和新版写同一个数据库文件：新版默认使用 WAL 模式，建议只运行其中一个。

---

## 🗄️ 数据模型

与旧版完全一致的 6 张表：

```
cell_lines(id, name, revival_date, type, default_passage_interval, notes)
culture_batches(id, cell_line_id, batch_name, revival_date, source_freeze_date,
                initial_pd, initial_cell_count, is_active, end_date, end_reason, notes)
culture_records(id, batch_id, passage, date, inoculum_cells, inoculum_dishes,
                harvested_cells, pd, cumulative_pd, status, next_passage_date, is_active, notes)
frozen_vials(id, cell_line_id, batch_id, freeze_date, cell_count, location, pd, status, notes)
cell_groups(id, group_name, notes)
cell_group_members(group_id, cell_line_id, sort_order)
```

新增辅助表（旧版不会读取）：`_schema_meta`、`users`、`audit_log`。

计算规则与旧版一致：

- 单次 PD = `log2(本次收获 / 上次接种)`，两者都 > 0 才计算，否则记 0
- 累计 PD = 批次初始 PD + 每次 `max(0, 单次 PD)`
- 同一批次只有「日期最新、同日期 id 最大」的一条记录是活跃记录
- 批次名允许重复（旧数据中存在同名批次），所有关联都按 id 进行

---

## 📁 目录结构

```
celltracker/
├─ start.bat                 # 双击启动
├─ config.json               # 端口、监听地址、认证开关（另有 config.example.json 模板）
├─ data/
│  ├─ cell_data.db           # 新版数据库（从旧库迁移）
│  └─ migration-report.json  # 迁移校验报告
├─ backups/                  # 自动备份
├─ backend/
│  ├─ __init__.py            # Flask 应用工厂
│  ├─ api.py                 # /api 路由
│  ├─ auth.py                # 认证（默认关闭）
│  ├─ config.py              # 配置加载
│  ├─ db.py                  # 连接、建表、备份、校验和
│  ├─ domain.py              # PD 公式、日期/数字解析
│  ├─ migrate.py             # 旧库迁移 CLI 与校验
│  ├─ serve.py               # 启动入口（waitress）
│  ├─ services/              # 业务服务
│  └─ tests/                 # pytest（41 项）
├─ frontend/
│  ├─ src/                   # Vue 页面、组件、图表配置
│  └─ dist/                  # 构建产物（Flask 直接托管）
├─ cell_tracker.py           # 旧版 Streamlit（保留回滚）
└─ cell_data.db              # 旧版原始数据库（保留回滚）
```

---

## ⚙️ 配置说明

`config.json`（可参考 `config.example.json`，项目根目录默认已生成一份可直接修改）：

```json
{
  "host": "127.0.0.1",
  "port": 18600,
  "open_browser": true,
  "database": "data/cell_data.db",
  "backup_dir": "backups",
  "auth": {
    "enabled": false,
    "session_days": 30,
    "bootstrap_username": "admin",
    "bootstrap_password": "celltracker"
  }
}
```

- `host`：`127.0.0.1` 仅本机；`0.0.0.0` 允许局域网访问
- `database`：可指向任意路径的 SQLite 文件（相对项目根目录或绝对路径）
- `auth.enabled`：改为 `true` 后重启即启用登录；首次开启自动创建 `bootstrap_username` 账号
- 环境变量可覆盖：`CELLTRACKER_HOST`、`CELLTRACKER_PORT`、`CELLTRACKER_DB`、`CELLTRACKER_CONFIG`

### 用户管理（启用认证后）

```powershell
python -m backend.auth create-user --username alice --password 你的密码
python -m backend.auth set-password --username alice --password 新密码
python -m backend.auth list-users
```

---

## 🔌 API 摘要

所有接口以 `/api` 为前缀，返回 JSON；错误格式统一为 `{"error": {"code", "message"}}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/meta` `/dashboard` | 版本、表计数、迁移状态、看板数据 |
| GET/POST/PATCH/DELETE | `/cell-lines[/id]` | 细胞株 CRUD |
| GET/POST/PATCH/DELETE | `/batches[/id]`、`/batches/id/terminate`、`/batches/id/records.csv` | 批次管理 |
| POST | `/records`、`/records/bulk`、`/records/bulk-update` | 单条/批量录入与编辑 |
| GET/POST/PATCH/DELETE | `/vials[/id]`、`/vials/boxes`、`/vials/import` | 冻存管与盒子 |
| GET/POST/PUT/DELETE | `/groups[/id]`、`/groups/id/members`、`/status`、`/rates`、`/curves`、`/export` | 细胞组、状态表、曲线、导出 |
| GET/POST | `/maintenance/audit`、`/recalculate`、`/backup`、`/restore`、`/import-legacy` | 体检、修复、备份恢复 |
| GET | `/auth/status` `/auth/me`，POST `/auth/login` `/auth/logout` | 认证（预留） |

---

## 🧪 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

覆盖：PD 公式与负数语义、日期/科学计数解析、批次重算与活跃记录、批量录入异常隔离、冻存管/冻存盒/Excel 导入、细胞组曲线与标准化、Excel 导出、备份恢复、认证开关、迁移校验。

---

## ⚠️ 注意事项

- 默认端口是 **18600**。如果启动窗口提示端口被占用（例如 maibot 或其他后台服务），把 `config.json` 里的 `"port"` 改成别的数字再启动即可；重复双击时如果服务已在运行，会直接打开浏览器
- 如果浏览器提示「现有实例正在以提升的权限运行」，说明系统里有一个管理员权限的浏览器在后台：点「是」让浏览器以普通权限重启，或直接手动访问 <http://127.0.0.1:18600>；也可以先彻底退出该浏览器再启动
- 备份文件在 `backups/`，默认保留最近 30 份
- 恢复/导入会替换当前数据库，操作前系统会自动备份；建议在无人写入时操作
- 局域网多人同时写会由应用层写锁串行化，SQLite 仍不适合高并发；日常实验室规模足够
- 前端构建需要 Node.js；如果只在目标机器运行，可以把本机的 `frontend/dist` 一起复制过去，就不需要 Node
- 旧版导出的 Excel 列名保持不变（细胞株信息 / 培养批次 / 传代记录 / 冻存管）

---

## 📄 许可证

Apache License 2.0，详见 [LICENSE](LICENSE)。
