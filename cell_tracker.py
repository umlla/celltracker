import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import math

# ==================== 数据库初始化 ====================
DB_NAME = "cell_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS cell_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            revival_date TEXT,
            type TEXT,
            default_passage_interval INTEGER DEFAULT 0,
            notes TEXT
        )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS culture_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cell_line_id INTEGER,
        batch_name TEXT NOT NULL,
        revival_date TEXT,
        source_freeze_date TEXT,
        initial_pd REAL DEFAULT 0,
        initial_cell_count REAL,
        is_active INTEGER DEFAULT 1,
        end_date TEXT,
        end_reason TEXT,
        notes TEXT,
        FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id)
    )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS culture_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER,
            passage INTEGER,
            date TEXT,
            inoculum_cells REAL,
            inoculum_dishes INTEGER,
            harvested_cells REAL,
            pd REAL,
            cumulative_pd REAL,
            status TEXT,
            next_passage_date TEXT,
            is_active INTEGER DEFAULT 1,
            notes TEXT,
            FOREIGN KEY(batch_id) REFERENCES culture_batches(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS frozen_vials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cell_line_id INTEGER,
            batch_id INTEGER,
            freeze_date TEXT,
            cell_count REAL,
            location TEXT DEFAULT '',
            pd REAL ,
            status TEXT DEFAULT '在库',
            notes TEXT,
            FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id),
            FOREIGN KEY(batch_id) REFERENCES culture_batches(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS cell_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT NOT NULL UNIQUE,
            notes TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS cell_group_members (
            group_id INTEGER,
            cell_line_id INTEGER,
            FOREIGN KEY(group_id) REFERENCES cell_groups(id),
            FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id),
            PRIMARY KEY(group_id, cell_line_id)
        )
    ''')

    conn.commit()
    conn.close()

init_db()
def upgrade_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # ... 其他已有升级 ...
    # 新增排序字段
    try:
        c.execute("ALTER TABLE cell_group_members ADD COLUMN sort_order INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
upgrade_db()

# ==================== 辅助函数 ====================


def get_connection():
    return sqlite3.connect(DB_NAME)

def calculate_pd(harvested, inoculum):
    if inoculum and inoculum > 0 and harvested and harvested > 0:
        return round(math.log2(harvested / inoculum), 2)
    return 0

def get_batch_active_record(batch_id):
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM culture_records WHERE batch_id = ? AND is_active = 1 ORDER BY date DESC LIMIT 1",
        conn, params=(batch_id,))
    conn.close()
    return df.iloc[0] if not df.empty else None

def get_batch_all_records(batch_id):
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM culture_records WHERE batch_id = ? ORDER BY date ASC",
        conn, params=(batch_id,))
    conn.close()
    return df

def get_cell_line_frozen_vials(cell_line_id):
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM frozen_vials WHERE cell_line_id = ? ORDER BY freeze_date DESC",
        conn, params=(cell_line_id,))
    conn.close()
    return df

def get_cell_line_info(cell_line_id):
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM cell_lines WHERE id = ?", conn, params=(cell_line_id,))
    conn.close()
    return df.iloc[0] if not df.empty else None

def get_all_cell_lines():
    conn = get_connection()
    df = pd.read_sql("SELECT id, name, type FROM cell_lines ORDER BY name", conn)
    conn.close()
    return df

def get_groups():
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM cell_groups ORDER BY group_name", conn)
    conn.close()
    return df

def get_group_members(group_id):
    conn = get_connection()
    # 检查列是否存在，若不存在则添加
    cols = [row[1] for row in conn.execute("PRAGMA table_info(cell_group_members)").fetchall()]
    if 'sort_order' not in cols:
        conn.execute("ALTER TABLE cell_group_members ADD COLUMN sort_order INTEGER DEFAULT 0")
        conn.commit()
    df = pd.read_sql_query('''
        SELECT cl.id, cl.name, cl.type, gm.sort_order
        FROM cell_group_members gm
        JOIN cell_lines cl ON gm.cell_line_id = cl.id
        WHERE gm.group_id = ?
        ORDER BY gm.sort_order, cl.name
    ''', conn, params=(group_id,))
    conn.close()
    return df
def get_batch_last_record(batch_id):
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM culture_records WHERE batch_id = ? ORDER BY date DESC LIMIT 1",
        conn, params=(batch_id,))
    conn.close()
    return df.iloc[0] if not df.empty else None
def recalculate_cumulative_pd(batch_id):
    conn = get_connection()
    batch = pd.read_sql_query(
        "SELECT initial_pd, initial_cell_count FROM culture_batches WHERE id = ?",
        conn, params=(batch_id,))
    if batch.empty:
        conn.close()
        return
    initial_pd = batch.iloc[0]['initial_pd'] or 0.0
    initial_cell_count = batch.iloc[0]['initial_cell_count']

    records = pd.read_sql_query(
        "SELECT * FROM culture_records WHERE batch_id = ? ORDER BY date ASC, id ASC",
        conn, params=(batch_id,))

    cumulative = initial_pd
    prev_inoculum = initial_cell_count   # None 作为首次分母
    for _, row in records.iterrows():
        harvested = row['harvested_cells']
        if prev_inoculum is not None and prev_inoculum > 0 and harvested > 0:
            pd_val = round(math.log2(harvested / prev_inoculum), 2)
        else:
            pd_val = 0
        cumulative += pd_val
        conn.execute("UPDATE culture_records SET pd = ?, cumulative_pd = ? WHERE id = ?",
                     (pd_val, round(cumulative, 2), row['id']))
        prev_inoculum = row['inoculum_cells']
    conn.commit()
    conn.close()
# ==================== 页面配置 ====================
st.set_page_config(page_title="细胞培养追踪系统 v3.0", layout="wide")
st.title("🧬 细胞培养追踪系统 v3.0")

menu = st.sidebar.radio("功能菜单", [
    "🧫 在养细胞",
    "➕ 添加细胞株",
    "📂 管理细胞组",
    "🧬 新建传代记录",
    "❄️ 添加冻存管",
    "🧊 冻存盒视图", 
    "🧪 新建培养批次"
])

# ==================== 1. 在养细胞 ====================
if menu == "🧫 在养细胞":
    st.header("在养细胞总览")

    # 计算在养细胞株总数（有不重复活跃批次）
    conn = get_connection()
    active_line_count = pd.read_sql_query('''
        SELECT COUNT(DISTINCT cl.id) as cnt
        FROM culture_batches cb
        JOIN cell_lines cl ON cb.cell_line_id = cl.id
        WHERE cb.is_active = 1
    ''', conn).iloc[0, 0]
    conn.close()
    st.metric("在养细胞株总数", active_line_count)

    view_mode = st.radio("查看模式", ["按细胞株查看", "按细胞组查看"])

    if view_mode == "按细胞株查看":
        all_lines = get_all_cell_lines()
        if all_lines.empty:
            st.info("暂无细胞株，请先添加。")
        else:
            # ---------- 使用 session_state 避免删除/改名后崩溃 ----------
            if 'selected_line_id' not in st.session_state:
                st.session_state.selected_line_id = None

            all_names = all_lines["name"].tolist()
            if st.session_state.selected_line_id is not None:
                mask = all_lines["id"] == st.session_state.selected_line_id
                if mask.any():
                    default_name = all_lines.loc[mask, "name"].values[0]
                    default_index = all_names.index(default_name)
                else:
                    default_index = 0
                    st.session_state.selected_line_id = None
            else:
                default_index = 0

            selected_name = st.selectbox("选择细胞株（可输入搜索）", all_names, index=default_index)
            selected_id = int(all_lines[all_lines["name"] == selected_name]["id"].iloc[0])
            st.session_state.selected_line_id = selected_id

            line_info = get_cell_line_info(selected_id)

            # 显示基本信息
            st.subheader(f"细胞株: {line_info['name']}")
            st.caption(f"类型: {line_info['type']}  |  默认传代间隔: {line_info['default_passage_interval']} 天")

            # 可选显示已终止批次
            show_ended = st.checkbox("显示已终止的批次", key=f"show_ended_{selected_id}")

            conn = get_connection()
            if show_ended:
                batches_df = pd.read_sql_query(
                    "SELECT * FROM culture_batches WHERE cell_line_id = ? ORDER BY is_active DESC, revival_date DESC",
                    conn, params=(selected_id,))
            else:
                batches_df = pd.read_sql_query(
                    "SELECT * FROM culture_batches WHERE cell_line_id = ? AND is_active = 1",
                    conn, params=(selected_id,))
            conn.close()

            st.write("---")
            st.subheader("🧪 培养批次")
            if batches_df.empty:
                st.warning("没有符合条件的批次。")
            else:
                for _, batch in batches_df.iterrows():
                    batch_id = batch['id']
                    is_alive = batch['is_active'] == 1

                    # 获取用于展示的记录
                    if is_alive:
                        active_record = get_batch_active_record(batch_id)
                        display_record = active_record
                    else:
                        active_record = None
                        display_record = get_batch_last_record(batch_id)

                    # 构建标题
                    if display_record is not None:
                        title = f"📌 {batch['batch_name']} (P{display_record['passage']})"
                    else:
                        title = f"⚪ {batch['batch_name']}"

                    if not is_alive:
                        title += f"  🔴 已终止（{batch['end_reason']}，{batch['end_date']}）"

                    with st.expander(title):
                        if display_record is not None:
                            col1, col2, col3, col4 = st.columns(4)
                            col1.metric("当前盘数", display_record["inoculum_dishes"])
                            col2.metric("细胞总数", f'{display_record["inoculum_cells"]:,.0f}')
                            col3.metric("传代次数", f'P{display_record["passage"]}')
                            col4.metric("累计PD", display_record["cumulative_pd"])
                            st.write(f"**状态**: {display_record['status'] or '—'}")
                            st.write(f"**传代时间**: {display_record['date']}")
                            if display_record["next_passage_date"]:
                                st.write(f"**建议下次传代时间**: {display_record['next_passage_date']}")

                           

                            # ----- 查看所有传代记录与生长曲线（所有批次均可用） -----
                            with st.expander("📜 查看所有传代记录与生长曲线"):
                                all_records = get_batch_all_records(batch_id)
                                if not all_records.empty:
                                    st.caption(f"总传代次数：{len(all_records)}")
                                    st.dataframe(
                                        all_records[["passage","date","inoculum_cells","harvested_cells","pd","cumulative_pd"]]
                                        .style.format({
                                            "passage": "{:.0f}",
                                            "inoculum_cells": "{:.2f}",
                                            "harvested_cells": "{:.2f}",
                                            "pd": "{:.2f}",
                                            "cumulative_pd": "{:.2f}"
                                        }),
                                        width='stretch'
                                    )
                                    fig = go.Figure()
                                    fig.add_trace(go.Scatter(x=all_records["date"], y=all_records["cumulative_pd"],
                                                             mode="lines+markers", name="累计PD", yaxis="y1"))
                                    fig.add_trace(go.Scatter(x=all_records["date"], y=all_records["harvested_cells"],
                                                             mode="lines+markers", name="收获细胞数", yaxis="y2",
                                                             line=dict(dash="dot")))
                                    fig.update_layout(xaxis_title="日期",
                                                      yaxis=dict(title="累计PD", side="left"),
                                                      yaxis2=dict(title="细胞总数", overlaying="y", side="right", type="log"),
                                                      hovermode="x unified",
                                                      legend=dict(x=0.01, y=0.99))
                                    st.plotly_chart(fig, width='stretch')
                                    csv = all_records.to_csv(index=False).encode('utf-8')
                                    st.download_button("📥 导出记录为CSV", csv, f"{batch['batch_name']}_records.csv", "text/csv")

                                    # ========= 记录管理（编辑 / 删除） =========
                                    st.write("---")
                                    st.subheader("🔧 管理传代记录")
                                    record_labels = all_records.apply(
                                        lambda r: f"{r['date']} - P{int(r['passage'])} (ID:{r['id']})", axis=1
                                    ).tolist()
                                    selected_label = st.selectbox(
                                        "选择要编辑或删除的记录",
                                        record_labels,
                                        key=f"manage_sel_{batch_id}"
                                    )
                                    selected_idx = record_labels.index(selected_label)
                                    record_to_manage = all_records.iloc[selected_idx]
                                    manage_id = int(record_to_manage['id'])

                                    tab1, tab2 = st.tabs(["✏️ 编辑记录", "🗑 删除记录"])

                                    # ----- 编辑功能 -----
                                    with tab1:
                                        with st.form(key=f"edit_form_{batch_id}"):
                                            st.markdown(f"**正在编辑：{selected_label}**")
                                            new_date = st.date_input("传代日期",
                                                                     value=datetime.strptime(record_to_manage['date'], "%Y-%m-%d").date())
                                            new_passage = st.number_input("传代次数 (P)", min_value=1,
                                                                          value=int(record_to_manage['passage']))
                                            new_harvested = st.number_input("本次收获细胞总数",
                                                                            value=float(record_to_manage['harvested_cells']),
                                                                            format="%.2f")
                                            new_dishes = st.number_input("种下盘数", min_value=1,
                                                                         value=int(record_to_manage['inoculum_dishes']))
                                            new_per_dish = st.number_input("每盘细胞数",
                                                                           value=float(record_to_manage['inoculum_cells']) / new_dishes,
                                                                           format="%.2f")
                                            new_inoculum = new_dishes * new_per_dish
                                            new_status = st.selectbox("细胞状态",
                                                                      ["良好", "一般", "较差", "污染"],
                                                                      index=["良好", "一般", "较差", "污染"].index(record_to_manage['status']) if record_to_manage['status'] in ["良好", "一般", "较差", "污染"] else 0)
                                            new_next_days = st.number_input("建议下次传代间隔天数（仅对最新记录有意义）",
                                                                           min_value=0, value=0)
                                            new_notes = st.text_area("备注", value=record_to_manage['notes'] if record_to_manage['notes'] else "")
                                            if st.form_submit_button("保存修改"):
                                                conn_edit = get_connection()
                                                # 如果修改后是当前活跃记录，才更新 next_passage_date
                                                is_active_record = (is_alive and active_record is not None and active_record['id'] == manage_id)
                                                next_date = None
                                                if is_active_record and new_next_days > 0:
                                                    next_date = (new_date + timedelta(days=new_next_days)).isoformat()
                                                conn_edit.execute('''UPDATE culture_records
                                                                    SET passage = ?, date = ?, inoculum_cells = ?, inoculum_dishes = ?,
                                                                        harvested_cells = ?, status = ?, next_passage_date = ?, notes = ?
                                                                    WHERE id = ?''',
                                                                  (new_passage, new_date.isoformat(), new_inoculum, new_dishes,
                                                                   new_harvested, new_status, next_date, new_notes, manage_id))
                                                conn_edit.commit()
                                                conn_edit.close()
                                                recalculate_cumulative_pd(batch_id)
                                                st.success("记录已更新，累计 PD 已重新计算。")
                                                st.rerun()

                                    # ----- 删除功能（保留原有安全删除逻辑） -----
                                    with tab2:
                                        st.warning(f"将要删除记录：{selected_label}")
                                        confirm_delete = st.checkbox(
                                            "我确认要删除这条传代记录，此操作不可恢复。",
                                            key=f"confirm_del_{batch_id}"
                                        )
                                        if confirm_delete:
                                            if st.button("执行删除", key=f"exec_del_{batch_id}"):
                                                conn_del = get_connection()
                                                try:
                                                    conn_del.execute("BEGIN")
                                                    conn_del.execute("DELETE FROM culture_records WHERE id = ?", (manage_id,))
                                                    # 如果删除的是当前活跃记录，将剩余最新记录设为活跃
                                                    if is_alive and active_record is not None and active_record['id'] == manage_id:
                                                        latest_remaining = conn_del.execute(
                                                            "SELECT id FROM culture_records WHERE batch_id = ? ORDER BY date DESC LIMIT 1",
                                                            (batch_id,)
                                                        ).fetchone()
                                                        if latest_remaining:
                                                            conn_del.execute("UPDATE culture_records SET is_active = 1 WHERE id = ?",
                                                                             (latest_remaining[0],))
                                                    conn_del.commit()
                                                except Exception as e:
                                                    conn_del.rollback()
                                                    st.error(f"删除失败：{e}")
                                                    st.stop()
                                                finally:
                                                    conn_del.close()
                                                recalculate_cumulative_pd(batch_id)
                                                st.success("记录已删除，累计 PD 已更新。")
                                                st.rerun()
                                else:
                                    st.info("暂无传代记录。")

                        # ----- 终止此批次培养（仅活跃批次） -----
                        if is_alive:
                            st.write("---")
                            with st.expander("⏹️ 终止此批次培养"):
                                end_reason = st.selectbox(
                                    "终止原因",
                                    ["污染", "全部冻存", "丢弃", "实验结束", "其他"],
                                    key=f"end_reason_{batch_id}"
                                )
                                if st.button("确认终止", key=f"end_btn_{batch_id}"):
                                    conn = get_connection()
                                    today_str = date.today().isoformat()
                                    conn.execute(
                                        "UPDATE culture_batches SET is_active = 0, end_date = ?, end_reason = ? WHERE id = ?",
                                        (today_str, end_reason, batch_id)
                                    )
                                    conn.execute(
                                        "UPDATE culture_records SET is_active = 0 WHERE batch_id = ? AND is_active = 1",
                                        (batch_id,)
                                    )
                                    conn.commit()
                                    conn.close()
                                    st.success(f"批次「{batch['batch_name']}」已终止（原因：{end_reason}）")
                                    st.rerun()
                            st.write("---")
                            with st.expander("🗑 删除此批次（危险操作）"):
                                st.error("此操作将永久删除该批次及其所有传代记录，且不可恢复！")
                                del_batch_confirm = st.checkbox(
                                    "我确认要删除此批次及所有传代记录",
                                    key=f"del_batch_confirm_{batch_id}"
                                )
                                if del_batch_confirm:
                                    if st.button("删除批次", key=f"btn_del_batch_{batch_id}"):
                                        conn = get_connection()
                                        conn.execute("DELETE FROM culture_records WHERE batch_id = ?", (batch_id,))
                                        conn.execute("UPDATE frozen_vials SET batch_id = NULL WHERE batch_id = ?", (batch_id,))
                                        conn.execute("DELETE FROM culture_batches WHERE id = ?", (batch_id,))
                                        conn.commit()
                                        conn.close()
                                        st.success(f"批次「{batch['batch_name']}」及其传代记录已删除。")
                                        st.rerun()

            # 冻存状态
            st.subheader("❄️ 冻存状态")
            vials = get_cell_line_frozen_vials(selected_id)
            if not vials.empty:
                total_vials = len(vials)
                total_cells = vials["cell_count"].sum()
                st.write(f"总冻存管数: {total_vials}  |  总冻存细胞数: {total_cells:,.0f}")
                vials_display = vials[["freeze_date", "cell_count", "location", "pd", "status"]].copy()
                vials_display["pd"] = vials_display["pd"].apply(
                    lambda x: "" if pd.isna(x) else f"{x:.2f}"
                )
                st.dataframe(vials_display, width='stretch',
                            column_config={"status": "状态"})
            else:
                st.info("暂无冻存记录。")

            # 编辑细胞株信息
            st.write("---")
            with st.expander("✏️ 编辑细胞株信息"):
                with st.form("edit_line_in_view"):
                    new_name = st.text_input("细胞株名称", value=line_info["name"])
                    new_interval = st.number_input("默认传代间隔（天）", min_value=0,
                                                   value=int(line_info["default_passage_interval"]))
                    new_revival = st.date_input("复苏日期",
                                                value=datetime.strptime(line_info["revival_date"], "%Y-%m-%d").date()
                                                if line_info["revival_date"] else datetime.today())
                    new_notes = st.text_area("备注", value=line_info["notes"] if line_info["notes"] else "")
                    if st.form_submit_button("保存修改"):
                        if new_name != line_info["name"]:
                            conn = get_connection()
                            conflict = conn.execute("SELECT id FROM cell_lines WHERE name = ? AND id != ?",
                                                    (new_name, selected_id)).fetchone()
                            conn.close()
                            if conflict:
                                st.error("该名称已被其他细胞株使用，请更换。")
                                st.stop()
                        conn = get_connection()
                        conn.execute("UPDATE cell_lines SET name = ?, default_passage_interval = ?, revival_date = ?, notes = ? WHERE id = ?",
                                     (new_name, new_interval, new_revival.isoformat(), new_notes, selected_id))
                        conn.commit()
                        conn.close()
                        st.success("信息已更新")
                        st.session_state.selected_line_id = None   # ← 清除选中缓存
                        st.rerun()

            # 删除细胞株
            st.write("---")
            st.warning("⚠️ 危险操作：删除细胞株将同时删除其所有批次、传代记录、冻存管及分组关系。")
            del_cell_confirm = st.checkbox("我确认要删除此细胞株及其所有数据", key=f"del_cell_{selected_id}")
            if del_cell_confirm:
                if st.button("删除此细胞株", key=f"btn_del_cell_{selected_id}"):
                    conn = get_connection()
                    conn.execute("DELETE FROM frozen_vials WHERE cell_line_id = ?", (selected_id,))
                    conn.execute("DELETE FROM culture_records WHERE batch_id IN (SELECT id FROM culture_batches WHERE cell_line_id = ?)", (selected_id,))
                    conn.execute("DELETE FROM culture_batches WHERE cell_line_id = ?", (selected_id,))
                    conn.execute("DELETE FROM cell_group_members WHERE cell_line_id = ?", (selected_id,))
                    conn.execute("DELETE FROM cell_lines WHERE id = ?", (selected_id,))
                    conn.commit()
                    conn.close()
                    st.success("细胞株已删除。")
                    st.session_state.selected_line_id = None   # ← 清除选中缓存
                    st.rerun()

    else:  # 按细胞组查看
        groups_df = get_groups()
        if groups_df.empty:
            st.info("暂无细胞组，请先创建。")
        else:
            group_name = st.selectbox("选择细胞组", groups_df["group_name"].tolist())
            group_id = int(groups_df[groups_df["group_name"] == group_name]["id"].iloc[0])
            members_df = get_group_members(group_id)
            if members_df.empty:
                st.warning("该组暂无成员。")
            else:
                member_ids = members_df["id"].tolist()
                conn = get_connection()
                placeholders = ','.join(['?'] * len(member_ids))
                query = f'''
                    SELECT cb.id as batch_id, cb.batch_name, cl.name as cell_name, cl.type,
                           cr.passage, cr.date as last_passage, cr.inoculum_cells, cr.inoculum_dishes,
                           cr.cumulative_pd, cr.status, cr.next_passage_date
                    FROM culture_batches cb
                    JOIN cell_lines cl ON cb.cell_line_id = cl.id
                    LEFT JOIN culture_records cr ON cr.batch_id = cb.id AND cr.is_active = 1
                        AND cr.date = (SELECT MAX(date) FROM culture_records WHERE batch_id = cb.id AND is_active = 1)
                    WHERE cb.is_active = 1 AND cl.id IN ({placeholders})
                    ORDER BY cl.name, cb.batch_name
                '''
                df = pd.read_sql_query(query, conn, params=member_ids)
                conn.close()

                if df.empty:
                    st.info("组内无正在培养的批次。")
                else:
                    today = date.today()
                    df['delta'] = df['next_passage_date'].apply(
                        lambda x: (datetime.strptime(x, "%Y-%m-%d").date() - today).days if pd.notnull(x) else None)
                    def color_delta(val):
                        if val is None or pd.isna(val):
                            return ''
                        elif val <= 0:
                            return 'background-color: #ffcccc'
                        elif val <= 2:
                            return 'background-color: #fff3cd'
                        else:
                            return 'background-color: #d4edda'
                    styled_df = df.style.map(color_delta, subset=['delta'])
                    st.dataframe(styled_df, column_config={
                        "batch_name": "批次", "cell_name": "细胞株", "type": "类型",
                        "passage": "代次", "last_passage": "上次传代",
                        "inoculum_dishes": "盘数", "inoculum_cells": "细胞总数",
                        "cumulative_pd": "累计PD", "status": "状态",
                        "next_passage_date": "建议下次传代", "delta": "剩余天数"
                    }, width='stretch')

# ==================== 2. 添加细胞株 ====================
elif menu == "➕ 添加细胞株":
    st.header("添加新细胞株")
    with st.form("add_line"):
        name = st.text_input("细胞株名称 *")
        revival_date = st.date_input("首次复苏日期", value=datetime.today())
        line_type = st.selectbox("类型", ["永生化", "原代"])
        default_interval = st.number_input("默认传代间隔（天，0表示不设默认）", min_value=0, value=0, step=1)
        notes = st.text_area("备注")
        if st.form_submit_button("添加"):
            if not name:
                st.error("名称不能为空")
            else:
                conn = get_connection()
                try:
                    conn.execute("INSERT INTO cell_lines (name, revival_date, type, default_passage_interval, notes) VALUES (?,?,?,?,?)",
                                 (name, revival_date.isoformat(), line_type, default_interval, notes))
                    conn.commit()
                    st.success(f"已添加细胞株「{name}」")
                except sqlite3.IntegrityError:
                    st.error("该细胞株名称已存在。")
                finally:
                    conn.close()

# ==================== 3. 管理细胞组 ====================
elif menu == "📂 管理细胞组":
    st.header("管理细胞组")
    tab1, tab2 = st.tabs(["创建/删除组", "管理组成员"])

    with tab1:
        st.subheader("创建新细胞组")
        with st.form("add_group"):
            group_name = st.text_input("组名")
            notes = st.text_area("备注")
            if st.form_submit_button("创建"):
                if group_name:
                    conn = get_connection()
                    try:
                        conn.execute("INSERT INTO cell_groups (group_name, notes) VALUES (?,?)", (group_name, notes))
                        conn.commit()
                        st.success(f"已创建组「{group_name}」")
                    except sqlite3.IntegrityError:
                        st.error("组名已存在。")
                    finally:
                        conn.close()
                else:
                    st.error("组名不能为空。")

        groups_df = get_groups()
        if not groups_df.empty:
            st.subheader("现有组（点击删除）")
            for _, group in groups_df.iterrows():
                col1, col2 = st.columns([4,1])
                col1.write(f"**{group['group_name']}**")
                if col2.button("删除", key=f"del_{group['id']}"):
                    conn = get_connection()
                    conn.execute("DELETE FROM cell_group_members WHERE group_id = ?", (group['id'],))
                    conn.execute("DELETE FROM cell_groups WHERE id = ?", (group['id'],))
                    conn.commit()
                    conn.close()
                    st.rerun()

        with tab2:
            st.subheader("修改组成员与排序")
            groups_df = get_groups()
            if groups_df.empty:
                st.info("请先创建细胞组。")
            else:
                group_name = st.selectbox("选择细胞组", groups_df["group_name"].tolist())
                group_id = int(groups_df[groups_df["group_name"] == group_name]["id"].iloc[0])
                members_df = get_group_members(group_id)

                # ---------- 成员选择（不变） ----------
                all_lines = get_all_cell_lines()
                all_names = all_lines["name"].tolist() if not all_lines.empty else []
                current_members = members_df["name"].tolist()
                new_members = st.multiselect("组成员（勾选添加，取消勾选移除）",
                                            options=all_names, default=current_members)
                if st.button("保存成员更改"):
                    to_add = list(set(new_members) - set(current_members))
                    to_remove = list(set(current_members) - set(new_members))
                    conn = get_connection()
                    # 添加新成员，sort_order 取当前最大值+1
                    max_order = conn.execute("SELECT MAX(sort_order) FROM cell_group_members WHERE group_id = ?",
                                            (group_id,)).fetchone()[0] or 0
                    for name in to_add:
                        line_id = int(all_lines[all_lines["name"] == name]["id"].iloc[0])
                        max_order += 1
                        conn.execute("INSERT OR IGNORE INTO cell_group_members (group_id, cell_line_id, sort_order) VALUES (?,?,?)",
                                    (group_id, line_id, max_order))
                    for name in to_remove:
                        line_id = int(all_lines[all_lines["name"] == name]["id"].iloc[0])
                        conn.execute("DELETE FROM cell_group_members WHERE group_id = ? AND cell_line_id = ?",
                                    (group_id, line_id))
                    conn.commit()
                    conn.close()
                    st.success("成员已更新。")
                    st.rerun()

                         # ---------- 排序调整 ----------
                        # ---------- 排序调整 ----------
                if not members_df.empty:
                    if 'sort_order' not in members_df.columns:
                        members_df['sort_order'] = 0
                    st.markdown("---")
                    st.subheader("调整排序（修改数字后点击保存）")

                    # 准备用于编辑的表格
                    order_df = members_df[['id', 'name', 'sort_order']].copy()
                    order_df['sort_order'] = order_df['sort_order'].astype(int)

                    edited_order = st.data_editor(
                        order_df,
                        column_config={
                            "id": None,  # 隐藏ID列
                            "name": st.column_config.TextColumn("细胞株", disabled=True),
                            "sort_order": st.column_config.NumberColumn("排序号", min_value=0, step=1)
                        },
                        width='stretch',
                        hide_index=True,
                        num_rows="fixed"
                    )

                    if st.button("保存排序"):
                        conn = get_connection()
                        for _, row in edited_order.iterrows():
                            conn.execute(
                                "UPDATE cell_group_members SET sort_order = ? WHERE group_id = ? AND cell_line_id = ?",
                                (int(row["sort_order"]), group_id, int(row["id"]))
                            )
                        conn.commit()
                        conn.close()
                        st.success("排序已更新")
                        st.rerun()


# ==================== 4. 新建传代记录 ====================
elif menu == "🧬 新建传代记录":
    st.header("新建传代记录")
    mode = st.radio("录入模式", ["按组录入（表格式）", "单批次录入"], horizontal=True, index=0)

    # ========================= 按组录入（表格式） =========================
    if mode == "按组录入（表格式）":
        groups_df = get_groups()
        if groups_df.empty:
            st.warning("暂无细胞组，请先创建或切换到单批次录入。")
        else:
            group_name = st.selectbox("选择细胞组", groups_df["group_name"].tolist())
            group_id = int(groups_df[groups_df["group_name"] == group_name]["id"].iloc[0])
            members_df = get_group_members(group_id)
            if members_df.empty:
                st.warning("该组暂无成员。")
            else:
                # 构建表格数据：每个细胞株的活跃批次，预填默认值
                table_data = []
                today_str = datetime.today().strftime("%Y-%m-%d")
                for _, member in members_df.iterrows():
                    line_id = member["id"]
                    line_name = member["name"]
                    line_info = get_cell_line_info(line_id)
                    default_interval = line_info["default_passage_interval"]

                    conn = get_connection()
                    batches = pd.read_sql_query(
                        "SELECT id, batch_name FROM culture_batches WHERE cell_line_id = ? AND is_active = 1",
                        conn, params=(line_id,))
                    conn.close()

                    if batches.empty:
                        continue
                    for _, batch in batches.iterrows():
                        batch_id = batch["id"]
                        batch_name = batch["batch_name"]
                        # 获取当前最大代次
                        conn = get_connection()
                        max_p = pd.read_sql_query(
                            "SELECT MAX(passage) FROM culture_records WHERE batch_id = ?",
                            conn, params=(batch_id,)).iloc[0, 0]
                        conn.close()
                        next_p = int(max_p) + 1 if max_p is not None else 1
                        table_data.append({
                            "细胞株": line_name,
                            "批次": batch_name,
                            "批次ID": batch_id,
                            "传代次数": next_p,
                            "传代日期": today_str,
                            "收获细胞总数": 0.0,
                            "种下盘数": 1,
                            "每盘细胞数": 0.0,
                            "细胞状态": "良好",
                            "建议间隔天数": default_interval,
                            "备注": ""
                        })

                if not table_data:
                    st.info("该组内所有细胞株均无活跃批次，请先创建批次。")
                else:
                    st.subheader(f"批量传代 - {group_name}")
                    df = pd.DataFrame(table_data)

                    # 配置列的显示与编辑规则
                    column_config = {
                        "细胞株": st.column_config.TextColumn("细胞株", disabled=True, width="small"),
                        "批次": st.column_config.TextColumn("批次", disabled=True, width="small"),
                        "批次ID": None,  # 隐藏该列
                        "传代次数": st.column_config.NumberColumn("传代次数", min_value=1, step=1, width="small"),
                        "传代日期": st.column_config.TextColumn("传代日期", width="small"),
                        "收获细胞总数": st.column_config.NumberColumn("收获总数", min_value=0.0, format="%.2f", width="small"),
                        "种下盘数": st.column_config.NumberColumn("盘数", min_value=1, step=1, width="small"),
                        "每盘细胞数": st.column_config.NumberColumn("每盘细胞数", min_value=0.0, format="%.2f", width="small"),
                        "细胞状态": st.column_config.SelectboxColumn("状态", options=["良好", "一般", "较差", "污染"], width="small"),
                        "建议间隔天数": st.column_config.NumberColumn("间隔天数", min_value=0, step=1, width="small"),
                        "备注": st.column_config.TextColumn("备注", width="small")
                    }

                    edited_df = st.data_editor(
                        df,
                        column_config=column_config,
                        width='stretch',  
                        hide_index=True,
                        num_rows="fixed",
                        column_order=["细胞株", "批次", "传代次数", "传代日期", "收获细胞总数",
                                      "种下盘数", "每盘细胞数", "细胞状态", "建议间隔天数", "备注"]
                    )

                    if st.button("批量提交", type="primary"):
                        errors = []
                        success_count = 0
                        # 提交时，从原始 df 获取隐藏的批次ID
                        for idx, row in edited_df.iterrows():
                            try:
                                batch_id = int(df.at[idx, "批次ID"])
                                passage = int(row["传代次数"])
                                date_str = str(row["传代日期"])[:10]
                                try:
                                    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                                except:
                                    errors.append(f"第{idx+1}行日期格式错误，请使用YYYY-MM-DD")
                                    continue
                                harvested_cells = float(row["收获细胞总数"])
                                inoculum_dishes = int(row["种下盘数"])
                                per_dish_cells = float(row["每盘细胞数"])
                                inoculum_cells = inoculum_dishes * per_dish_cells
                                status = row["细胞状态"]
                                next_days = int(row["建议间隔天数"])
                                notes = row["备注"]

                                # 计算 PD
                                prev_active = get_batch_active_record(batch_id)
                                if prev_active is not None:
                                    prev_inoculum = prev_active["inoculum_cells"]
                                    prev_cumulative_pd = prev_active["cumulative_pd"]
                                else:
                                    conn = get_connection()
                                    batch_info = pd.read_sql_query(
                                        "SELECT initial_pd, initial_cell_count FROM culture_batches WHERE id = ?",
                                        conn, params=(batch_id,))
                                    conn.close()
                                    initial_pd = batch_info.iloc[0]['initial_pd'] if not batch_info.empty else 0.0
                                    initial_cell_count = batch_info.iloc[0]['initial_cell_count'] if not batch_info.empty else None
                                    prev_inoculum = initial_cell_count if initial_cell_count else 0
                                    prev_cumulative_pd = initial_pd

                                pd_value = calculate_pd(harvested_cells, prev_inoculum)
                                cumulative_pd = round(prev_cumulative_pd + pd_value, 2)

                                conn = get_connection()
                                conn.execute("UPDATE culture_records SET is_active = 0 WHERE batch_id = ? AND is_active = 1", (batch_id,))
                                next_date = None
                                if next_days > 0:
                                    next_date = (date_obj + timedelta(days=next_days)).isoformat()
                                conn.execute('''INSERT INTO culture_records
                                    (batch_id, passage, date, inoculum_cells, inoculum_dishes, harvested_cells,
                                     pd, cumulative_pd, status, next_passage_date, is_active, notes)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,1,?)''',
                                    (batch_id, passage, date_obj.isoformat(), inoculum_cells, inoculum_dishes,
                                     harvested_cells, pd_value, cumulative_pd, status, next_date, notes))
                                conn.commit()
                                conn.close()
                                success_count += 1
                            except Exception as e:
                                errors.append(f"第{idx+1}行提交失败：{e}")

                        if errors:
                            for e in errors:
                                st.error(e)
                        st.success(f"成功提交 {success_count} 条传代记录。")
                        if not errors:
                            st.rerun()

    # ========================= 单批次录入（保留原逻辑） =========================
    else:
        all_lines = get_all_cell_lines()
        if all_lines.empty:
            st.warning("请先添加细胞株和批次。")
        else:
            line_name = st.selectbox("选择细胞株", all_lines["name"].tolist())
            selected_line_id = int(all_lines[all_lines["name"] == line_name]["id"].iloc[0])
            line_info = get_cell_line_info(selected_line_id)
            default_interval = line_info["default_passage_interval"]

            conn = get_connection()
            batches_df = pd.read_sql_query(
                "SELECT id, batch_name FROM culture_batches WHERE cell_line_id = ? AND is_active = 1",
                conn, params=(selected_line_id,))
            conn.close()

            if batches_df.empty:
                st.error("该细胞株没有活跃批次，请先创建批次。")
            else:
                batch_choice = st.selectbox("选择培养批次", batches_df["batch_name"].tolist())
                selected_batch_id = int(batches_df[batches_df["batch_name"] == batch_choice]["id"].iloc[0])

                # 获取默认代次
                conn = get_connection()
                max_passage = pd.read_sql_query(
                    "SELECT MAX(passage) FROM culture_records WHERE batch_id = ?",
                    conn, params=(selected_batch_id,)).iloc[0, 0]
                conn.close()
                default_passage = int(max_passage) + 1 if max_passage is not None else 1

                with st.form("add_culture"):
                    passage = st.number_input("传代次数 (P)", min_value=1, value=default_passage, step=1)
                    date_input = st.date_input("传代日期", value=datetime.today())
                    harvested_cells = st.number_input("本次收获细胞总数（×10⁵ cells）", min_value=0.0, format="%.2f")
                    inoculum_dishes = st.number_input("本次传代种下盘数", min_value=1, value=1)
                    per_dish_cells = st.number_input("每盘细胞数（×10⁵ cells）", min_value=0.0, format="%.2f")
                    inoculum_cells = inoculum_dishes * per_dish_cells
                    status = st.selectbox("细胞状态", ["良好", "一般", "较差", "污染"])
                    next_days = st.number_input("建议下次传代间隔天数",
                                                min_value=0,
                                                value=default_interval if default_interval > 0 else 0)
                    notes = st.text_area("备注")
                    if st.form_submit_button("提交"):
                        conn = get_connection()
                        batch_info = pd.read_sql_query(
                            "SELECT initial_pd, initial_cell_count FROM culture_batches WHERE id = ?",
                            conn, params=(selected_batch_id,))
                        conn.close()
                        initial_pd = batch_info.iloc[0]['initial_pd'] if not batch_info.empty else 0.0
                        initial_cell_count = batch_info.iloc[0]['initial_cell_count'] if not batch_info.empty else None

                        prev_active = get_batch_active_record(selected_batch_id)
                        if prev_active is not None:
                            prev_inoculum = prev_active["inoculum_cells"]
                            prev_cumulative_pd = prev_active["cumulative_pd"]
                        else:
                            prev_inoculum = initial_cell_count if initial_cell_count else 0
                            prev_cumulative_pd = initial_pd

                        pd_value = calculate_pd(harvested_cells, prev_inoculum)
                        cumulative_pd = round(prev_cumulative_pd + pd_value, 2)

                        conn = get_connection()
                        conn.execute("UPDATE culture_records SET is_active = 0 WHERE batch_id = ? AND is_active = 1",
                                     (selected_batch_id,))
                        next_date = None
                        if next_days > 0:
                            next_date = (date_input + timedelta(days=next_days)).isoformat()
                        conn.execute('''INSERT INTO culture_records
                            (batch_id, passage, date, inoculum_cells, inoculum_dishes, harvested_cells,
                             pd, cumulative_pd, status, next_passage_date, is_active, notes)
                            VALUES (?,?,?,?,?,?,?,?,?,?,1,?)''',
                            (selected_batch_id, passage, date_input.isoformat(), inoculum_cells, inoculum_dishes,
                             harvested_cells, pd_value, cumulative_pd, status, next_date, notes))
                        conn.commit()
                        conn.close()
                        st.success("传代记录已添加。")

# ==================== 5. 添加冻存管（含孔位点选） ====================
elif menu == "❄️ 添加冻存管":
    st.header("添加冻存管记录")
    all_lines = get_all_cell_lines()
    if all_lines.empty:
        st.warning("请先添加细胞株。")
    else:
        # 细胞株选择在表单外
        line_name = st.selectbox("选择细胞株", all_lines["name"].tolist())
        selected_line_id = int(all_lines[all_lines["name"] == line_name]["id"].iloc[0])

        # ========= 新增：冻存盒孔位点选区 =========
                # ========= 多选孔位（9×9 网格点选版） =========
        with st.expander("📌 从冻存盒选择孔位（可多选）"):
            conn = get_connection()
            all_vials_df = pd.read_sql_query("SELECT location FROM frozen_vials", conn)
            conn.close()

            boxes = set()
            if not all_vials_df.empty:
                for loc in all_vials_df["location"]:
                    parts = loc.split("/")
                    if len(parts) >= 3:
                        boxes.add("/".join(parts[:3]))
            box_list = sorted(boxes)

            if box_list:
                selected_box = st.selectbox("选择已有冻存盒", box_list, key="box_selector")

                # 获取该盒子的占用情况
                conn = get_connection()
                box_vials = pd.read_sql_query('''
                    SELECT fv.id, fv.location, cl.name as cell_name, fv.status
                    FROM frozen_vials fv
                    JOIN cell_lines cl ON fv.cell_line_id = cl.id
                    WHERE fv.location LIKE ?
                ''', conn, params=(f"{selected_box}/%",))
                conn.close()

                # 计算占用孔位
                occupied_holes = {}
                for _, row in box_vials.iterrows():
                    hole = row["location"].split("/")[-1]
                    occupied_holes[hole] = {"cell_name": row["cell_name"], "status": row["status"]}

                # 9×9 孔位定义
                rows = "ABCDEFGHI"
                cols = list(range(1, 10))

                # 初始化或获取已选孔位（通过 session_state 管理多选集合）
                grid_key = f"selected_holes_{selected_box}"
                if grid_key not in st.session_state:
                    st.session_state[grid_key] = set()
                selected_set = st.session_state[grid_key]

                # 渲染网格，每个孔位是一个复选框
                st.caption(f"盒：{selected_box} | 已占用 {len(occupied_holes)} 孔，点击空格勾选")
                for r in rows:
                    cols_grid = st.columns(9)
                    for idx, c in enumerate(cols):
                        hole_id = f"{r}{c}"
                        with cols_grid[idx]:
                            if hole_id in occupied_holes:
                                vial = occupied_holes[hole_id]
                                label = f"🚫 {hole_id}"
                                st.checkbox(label, value=False, disabled=True,
                                            key=f"occ_{selected_box}_{hole_id}",
                                            help=f"{vial['cell_name']} ({vial['status']})")
                            else:
                                # 空闲孔位，可勾选
                                is_checked = hole_id in selected_set
                                cb = st.checkbox(f"⬜ {hole_id}", value=is_checked,
                                                 key=f"free_{selected_box}_{hole_id}")
                                if cb and hole_id not in selected_set:
                                    selected_set.add(hole_id)
                                elif not cb and hole_id in selected_set:
                                    selected_set.remove(hole_id)
                                # st.checkbox 的 on_change 不便，这里借助循环后的判断更新 session_state
                                # 注意：由于 Streamlit 重跑机制，这里 set 会即时更新，无需额外处理

                # 同步更新 session_state 中的选中集合
                st.session_state[grid_key] = selected_set

                # 生成选中的位置字符串（逗号分隔）
                if selected_set:
                    locations = [f"{selected_box}/{h}" for h in sorted(selected_set)]
                    st.session_state["selected_location"] = ",".join(locations)
                    st.success(f"已选中 {len(selected_set)} 个孔位：{', '.join(sorted(selected_set))}")
                else:
                    # 不选中任何孔时，清除之前可能残留的位置
                    if "selected_location" in st.session_state:
                        del st.session_state["selected_location"]

            else:
                st.info("暂无冻存盒，请先手动添加一支冻存管（位置格式：罐A/架1/盒1/A1）。")

        # ========= 原表单（位置自动填入并允许修改） =========
        with st.form("add_vial"):
            vial_count = st.number_input("添加管数", min_value=1, value=1, step=1)
            freeze_date = st.date_input("冻存日期", value=datetime.today())
            cell_count_per_vial = st.number_input("每管细胞数（×10⁵ cells）", min_value=0.0, format="%.2f")

            # 位置输入框，从点选结果自动填入，也可手动修改
            default_location = st.session_state.get("selected_location", "")
            location = st.text_input("冻存位置（格式：罐/架/盒/孔，例如：罐1/架1/盒1/A1）", value=default_location)

            pd_str = st.text_input("冻存时PD值（可留空，未知可不填）", value="")
            notes = st.text_area("备注")
            if st.form_submit_button("添加"):
                # ---- 解析 PD 值 ----
                pd_value = None
                if pd_str.strip():
                    try:
                        pd_value = float(pd_str)
                    except ValueError:
                        st.error("PD值格式错误，请输入数字或留空。")
                        st.stop()

                conn = get_connection()
                replace_id = st.session_state.get('replace_vial_id')
                if replace_id:
                    # 更新已有冻存管（已复苏孔位替换）
                    conn.execute('''UPDATE frozen_vials 
                                    SET cell_line_id = ?, freeze_date = ?, cell_count = ?, 
                                        location = ?, pd = ?, status = '在库', notes = ?
                                    WHERE id = ?''',
                                (selected_line_id, freeze_date.isoformat(), cell_count_per_vial, 
                                 location, pd_value, notes, replace_id))
                    st.success(f"已更新冻存管记录（孔位 {location}）")
                else:
                    # 插入新记录
                    for _ in range(vial_count):
                        conn.execute('''INSERT INTO frozen_vials
                            (cell_line_id, freeze_date, cell_count, location, pd, notes)
                            VALUES (?,?,?,?,?,?)''',
                            (selected_line_id, freeze_date.isoformat(), cell_count_per_vial, location, pd_value, notes))
                    st.success(f"已添加 {vial_count} 支冻存管。")
                conn.commit()
                conn.close()
                # 清除临时状态
                for key in ['selected_location', 'replace_vial_id']:
                    if key in st.session_state:
                        del st.session_state[key]
# ==================== 冻存盒视图 ====================
# ==================== 冻存盒管理（搜索编辑 / 网格视图） ====================
elif menu == "🧊 冻存盒视图":
    st.header("冻存管管理")
    mode = st.radio("选择模式", ["🔍 搜索编辑", "📦 冻存盒网格视图"], horizontal=True, index=0)

    # ========================= 搜索编辑模式（默认） =========================
    if mode == "🔍 搜索编辑":
        st.subheader("搜索并编辑冻存管")
        search_term = st.text_input("输入细胞株名称或位置关键词", "")

        if search_term.strip():
            like_str = f"%{search_term.strip()}%"
            conn = get_connection()
            df_edit = pd.read_sql_query("""
                SELECT fv.id, fv.location, cl.name as cell_name, fv.freeze_date, fv.cell_count, fv.pd, fv.status, fv.notes
                FROM frozen_vials fv
                JOIN cell_lines cl ON fv.cell_line_id = cl.id
                WHERE cl.name LIKE ? OR fv.location LIKE ?
                ORDER BY fv.id
            """, conn, params=(like_str, like_str))
            conn.close()

            if df_edit.empty:
                st.info("没有找到匹配的冻存管。")
            else:
                st.write(f"找到 {len(df_edit)} 支冻存管")
                for _, row in df_edit.iterrows():
                    vial_id = int(row["id"])
                    with st.expander(f"{row['cell_name']} - {row['location']}  ({row['status']})"):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.write(f"**冻存日期**：{row['freeze_date']}  |  **细胞数**：{row['cell_count']}  |  **PD**：{row['pd'] if pd.notna(row['pd']) else '未填'}")
                            if row['notes']:
                                st.write(f"**备注**：{row['notes']}")
                        with col2:
                            if st.button("✏️ 编辑", key=f"edit_vial_{vial_id}"):
                                st.session_state["edit_vial_id"] = vial_id
                                st.rerun()
                            # ---------- 新增：删除按钮 ----------
                            if st.button("🗑 删除", key=f"del_vial_{vial_id}"):
                                st.session_state["delete_vial_id"] = vial_id
                                st.rerun()
                            # ------------------------------------

                # 编辑表单（原有部分）
                if "edit_vial_id" in st.session_state:
                    vid = st.session_state["edit_vial_id"]
                    conn = get_connection()
                    cur = conn.execute("SELECT * FROM frozen_vials WHERE id = ?", (vid,))
                    record = cur.fetchone()
                    conn.close()
                    if record:
                        col_names = ["id", "cell_line_id", "batch_id", "freeze_date", "cell_count", "location", "pd", "status", "notes"]
                        vox = dict(zip(col_names, record))
                        st.markdown("---")
                        with st.form(key=f"edit_form_vial_{vid}"):
                            st.subheader(f"编辑冻存管 ID {vid}")
                            new_location = st.text_input("位置", value=vox["location"])
                            new_freeze_date = st.date_input("冻存日期", value=datetime.strptime(vox["freeze_date"], "%Y-%m-%d").date() if vox["freeze_date"] else datetime.today())
                            new_cell_count = st.number_input("细胞数", value=float(vox["cell_count"]) if vox["cell_count"] else 0.0, format="%.2f")
                            new_pd = st.text_input("PD值（可留空）", value=str(vox["pd"]) if vox["pd"] is not None else "")
                            new_status = st.selectbox("状态", ["在库", "已复苏", "已丢弃"], index=["在库", "已复苏", "已丢弃"].index(vox["status"]) if vox["status"] in ["在库", "已复苏", "已丢弃"] else 0)
                            new_notes = st.text_area("备注", value=vox["notes"] if vox["notes"] else "")
                            col_save, col_cancel = st.columns(2)
                            with col_save:
                                if st.form_submit_button("保存修改"):
                                    pd_val = None
                                    if new_pd.strip():
                                        try:
                                            pd_val = float(new_pd)
                                        except ValueError:
                                            st.error("PD格式错误")
                                            st.stop()
                                    conn_up = get_connection()
                                    conn_up.execute('''UPDATE frozen_vials
                                        SET location=?, freeze_date=?, cell_count=?, pd=?, status=?, notes=?
                                        WHERE id=?''',
                                        (new_location, new_freeze_date.isoformat(), new_cell_count, pd_val, new_status, new_notes, vid))
                                    conn_up.commit()
                                    conn_up.close()
                                    del st.session_state["edit_vial_id"]
                                    st.success("修改已保存")
                                    st.rerun()
                            with col_cancel:
                                if st.form_submit_button("取消"):
                                    del st.session_state["edit_vial_id"]
                                    st.rerun()

                # ---------- 新增：删除确认逻辑 ----------
                if "delete_vial_id" in st.session_state:
                    vid = st.session_state["delete_vial_id"]
                    conn = get_connection()
                    cur = conn.execute(
                        "SELECT fv.location, cl.name FROM frozen_vials fv JOIN cell_lines cl ON fv.cell_line_id = cl.id WHERE fv.id = ?",
                        (vid,)
                    )
                    del_info = cur.fetchone()
                    conn.close()
                    if del_info:
                        location, cell_name = del_info
                        st.warning(f"确认删除冻存管：{cell_name} - {location}？此操作不可恢复。")
                        col_yes, col_no = st.columns(2)
                        if col_yes.button("✅ 确认删除", key=f"confirm_del_vial_{vid}"):
                            conn_del = get_connection()
                            conn_del.execute("DELETE FROM frozen_vials WHERE id = ?", (vid,))
                            conn_del.commit()
                            conn_del.close()
                            del st.session_state["delete_vial_id"]
                            st.success("已删除。")
                            st.rerun()
                        if col_no.button("❌ 取消", key=f"cancel_del_vial_{vid}"):
                            del st.session_state["delete_vial_id"]
                            st.rerun()
                # ------------------------------------------
        else:
            st.info("请输入关键词开始搜索。")

    # ========================= 冻存盒网格视图 =========================
    else:
        conn = get_connection()
        df_all = pd.read_sql_query("""
            SELECT fv.id, fv.location, cl.name as cell_name, fv.freeze_date, fv.cell_count, fv.pd, fv.status
            FROM frozen_vials fv
            JOIN cell_lines cl ON fv.cell_line_id = cl.id
        """, conn)
        conn.close()

        if df_all.empty:
            st.info("暂无冻存管数据。")
        else:
            def extract_box_id(loc):
                parts = loc.split("/")
                if len(parts) >= 3:
                    return "/".join(parts[:3])
                return "格式不符"

            df_all["box_id"] = df_all["location"].apply(extract_box_id)
            df_valid = df_all[df_all["box_id"] != "格式不符"]
            if df_valid.empty:
                st.warning("没有符合“罐/架/盒/孔”格式的冻存管，请先按此格式录入。")
            else:
                boxes = sorted(df_valid["box_id"].unique())
                selected_box = st.selectbox("选择冻存盒", boxes, key="box_view_selector")
                box_df = df_valid[df_valid["box_id"] == selected_box]

                st.subheader(f"{selected_box}  （共 {len(box_df)} 支管）")

                # 构建孔位映射（清洗孔号前缀）
                hole_map = {}
                for _, row in box_df.iterrows():
                    hole = row["location"].split("/")[-1]
                    if hole.startswith("孔"):
                        hole = hole[1:]
                    hole_map[hole] = {"id": row["id"], "cell_name": row["cell_name"], "status": row["status"]}

                # 删除确认
                if "pending_delete" in st.session_state and st.session_state.pending_delete.get("box") == selected_box:
                    st.warning(f"确认删除孔位 {st.session_state.pending_delete['hole']} 的冻存管（{st.session_state.pending_delete['cell_name']}）吗？")
                    col1, col2 = st.columns(2)
                    if col1.button("✅ 确认删除", key="confirm_del_box"):
                        conn_del = get_connection()
                        conn_del.execute("DELETE FROM frozen_vials WHERE id = ?", (st.session_state.pending_delete["id"],))
                        conn_del.commit()
                        conn_del.close()
                        del st.session_state.pending_delete
                        st.success("已删除。")
                        st.rerun()
                    if col2.button("❌ 取消", key="cancel_del_box"):
                        del st.session_state.pending_delete
                        st.rerun()

                # 使用 HTML 表格渲染 9x9 网格，避免大量按钮造成卡顿
                rows = "ABCDEFGHI"
                cols = list(range(1, 10))
                html = '<table style="border-collapse: collapse; width: 100%; font-size:12px;">'
                html += '<tr><th></th>' + ''.join([f'<th style="border:1px solid #ddd; background:#f0f0f0;">{c}</th>' for c in cols]) + '</tr>'
                for r in rows:
                    html += '<tr>'
                    html += f'<td style="font-weight:bold; border:1px solid #ddd; background:#f0f0f0; text-align:center;">{r}</td>'
                    for c in cols:
                        hole_id = f"{r}{c}"
                        if hole_id in hole_map:
                            vial = hole_map[hole_id]
                            cell = vial['cell_name']
                            status = vial['status']
                            bg = "#d4edda" if status == "在库" else "#fff3cd"
                            txt = "🚫" if status == "在库" else "🗑"
                            # 点击删除按钮通过表单提交，但 HTML 无法直接删除，改为生成可点击的链接
                            # 我们用 Streamlit 的 markdown 无法做到点按，所以保留少量按钮或使用 HTML 表单？为了流畅，暂时只展示不可操作。
                            # 若需要删除，用户可切换到搜索编辑模式。
                            html += f'<td style="border:2px solid {"#28a745" if status=="在库" else "#ffc107"}; background:{bg}; text-align:center; padding:2px;" title="{cell} ({status})">{txt}<br><small>{cell}</small></td>'
                        else:
                            html += f'<td style="border:1px solid #ddd; color:#ccc; text-align:center;">＋</td>'
                    html += '</tr>'
                html += '</table>'
                st.markdown(html, unsafe_allow_html=True)
                st.markdown("**图例**：🟢 在库（🚫）  🟡 已复苏（🗑）  ➕ 空孔")
                st.caption("💡 如需删除或编辑冻存管，请切换到“搜索编辑”模式。")

# ==================== 6. 新建培养批次 ====================
elif menu == "🧪 新建培养批次":
    st.header("新建培养批次（复苏）")
    all_lines = get_all_cell_lines()
    if all_lines.empty:
        st.warning("请先添加细胞株。")
    else:
        line_name = st.selectbox("选择细胞株", all_lines["name"].tolist())
        selected_line_id = int(all_lines[all_lines["name"] == line_name]["id"].iloc[0])

        with st.form("add_batch"):
            revival_date = st.date_input("复苏日期", value=datetime.today())

            # 获取该细胞株所有在库冻存管
            vials_df = get_cell_line_frozen_vials(selected_line_id)
            in_storage = vials_df[vials_df['status'] == '在库'] if not vials_df.empty else pd.DataFrame()

            vial_options = ["不绑定（手动输入冻存日期）"]
            vial_id_map = {0: None}  # 索引 0 → 不绑定
            for i, (_, vial) in enumerate(in_storage.iterrows(), start=1):
                label = f"{vial['freeze_date']} | {vial['location']} | {vial['cell_count']:.0f} cells"
                vial_options.append(label)
                vial_id_map[i] = vial['id']

            vial_choice = st.selectbox("选择来源冻存管（可选）", vial_options)
            selected_vial_id = vial_id_map[vial_options.index(vial_choice)]

            # 自动填入或手动输入冻存日期
            if selected_vial_id is not None:
                default_freeze_date = datetime.strptime(
                    in_storage.loc[in_storage['id'] == selected_vial_id, 'freeze_date'].values[0],
                    "%Y-%m-%d"
                ).date()
            else:
                default_freeze_date = datetime.today()
            source_freeze_date = st.date_input("所复苏冻存细胞的原始冻存日期", value=default_freeze_date)

            initial_pd = st.number_input("初始PD值", min_value=0.0, value=0.0, format="%.2f")
            initial_cell_count = st.number_input("复苏接种细胞数（可选）", min_value=0.0, value=0.0, format="%.2f")

            notes = st.text_area("批次备注（可选）")
            if st.form_submit_button("创建批次"):
                batch_name = f"{line_name}-{revival_date.strftime('%y%m%d')}"
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute('''INSERT INTO culture_batches
                    (cell_line_id, batch_name, revival_date, source_freeze_date,
                     initial_pd, initial_cell_count, is_active, notes)
                    VALUES (?,?,?,?,?,?,1,?)''',
                    (selected_line_id, batch_name, revival_date.isoformat(),
                     source_freeze_date.isoformat(), initial_pd,
                     initial_cell_count if initial_cell_count > 0 else None,
                     notes))
                # 获取新插入的批次 ID
                new_batch_id = cursor.lastrowid
                # 如果绑定了冻存管，更新其状态
                if selected_vial_id is not None:
                    cursor.execute(
                        "UPDATE frozen_vials SET status = '已复苏', batch_id = ? WHERE id = ?",
                        (new_batch_id, selected_vial_id)
                    )
                conn.commit()
                conn.close()
                st.success(f"已创建批次「{batch_name}」")