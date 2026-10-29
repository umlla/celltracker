"""旧版数据库迁移与校验。

用法：
    python -m backend.migrate --source cell_data.db --target data/cell_data.db
    python -m backend.migrate --source old.db --target data/cell_data.db --fix-pd

迁移使用 SQLite 在线备份 API 做整库复制（保留全部 id 与外键关系），
随后逐表计算 SHA256 校验和，并对 PD 计算、活跃记录标记做一致性审计。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import db
from .config import PROJECT_ROOT, SCHEMA_VERSION, Config
from .domain import calc_pd, recalculate_batch

LEGACY_DB_CANDIDATES = (
    PROJECT_ROOT / "cell_data.db",
    PROJECT_ROOT / "cell_data.sqlite",
    PROJECT_ROOT / "data" / "legacy.db",
)


def audit_pd(conn: sqlite3.Connection, limit: int = 20) -> dict[str, Any]:
    """用当前规则离线重算 PD，与库中存储值比对（只读）。"""
    batches = conn.execute(
        "SELECT id, initial_pd, initial_cell_count FROM culture_batches ORDER BY id"
    ).fetchall()
    checked = 0
    mismatch_count = 0
    mismatches: list[dict[str, Any]] = []

    for batch in batches:
        cumulative = float(batch["initial_pd"] or 0.0)
        prev_inoculum = batch["initial_cell_count"]
        rows = conn.execute(
            "SELECT id, passage, date, harvested_cells, inoculum_cells, pd, cumulative_pd "
            "FROM culture_records WHERE batch_id = ? ORDER BY date ASC, id ASC",
            (batch["id"],),
        ).fetchall()
        for row in rows:
            checked += 1
            expected_pd = calc_pd(row["harvested_cells"], prev_inoculum) if prev_inoculum else 0.0
            cumulative += max(0.0, expected_pd)
            expected_cumulative = round(cumulative, 2)
            stored_pd = float(row["pd"] or 0.0)
            stored_cumulative = float(row["cumulative_pd"] or 0.0)
            if abs(stored_pd - expected_pd) > 0.005 or abs(stored_cumulative - expected_cumulative) > 0.01:
                mismatch_count += 1
                if len(mismatches) < limit:
                    mismatches.append({
                        "batch_id": batch["id"],
                        "record_id": row["id"],
                        "passage": row["passage"],
                        "date": row["date"],
                        "stored_pd": stored_pd,
                        "expected_pd": expected_pd,
                        "stored_cumulative_pd": stored_cumulative,
                        "expected_cumulative_pd": expected_cumulative,
                    })
            prev_inoculum = row["inoculum_cells"]

    return {"records_checked": checked, "mismatch_count": mismatch_count, "examples": mismatches}


def audit_active_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """检查活跃批次是否把「最新记录」标为活跃。"""
    problems: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT cb.id AS batch_id, cb.batch_name, "
        "  (SELECT id FROM culture_records r WHERE r.batch_id = cb.id ORDER BY r.date DESC, r.id DESC LIMIT 1) AS latest_id, "
        "  (SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1 LIMIT 1) AS active_id "
        "FROM culture_batches cb WHERE cb.is_active = 1"
    ).fetchall()
    for row in rows:
        if row["latest_id"] is not None and row["active_id"] != row["latest_id"]:
            problems.append({
                "batch_id": row["batch_id"],
                "batch_name": row["batch_name"],
                "latest_record_id": row["latest_id"],
                "active_record_id": row["active_id"],
            })
    return problems


def _copy_database(source: Path, target: Path) -> None:
    """复制为一个自包含（非 WAL）的数据库文件。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = db.connect(source, readonly=True, wal=False)
    try:
        target_conn = sqlite3.connect(str(target))
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()

    # 若源库是 WAL 模式，页头可能带 WAL 标记；转回 DELETE 模式并清理 -wal/-shm
    checkpoint = sqlite3.connect(str(target))
    try:
        checkpoint.execute("PRAGMA journal_mode = DELETE")
        checkpoint.commit()
    finally:
        checkpoint.close()
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)


def migrate_database(
    source: str | Path,
    target: str | Path,
    *,
    force: bool = False,
    fix_pd: bool = False,
    report_path: str | Path | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    source_path = Path(source).resolve()
    target_path = Path(target).resolve()

    if source_path == target_path:
        raise ValueError("源数据库与目标数据库相同，无需迁移")

    info = db.validate_database_file(source_path)
    if not info.get("ok"):
        raise ValueError(f"源数据库校验失败：{info.get('reason')}")

    previous = None
    if target_path.exists():
        if not force:
            raise FileExistsError(f"目标数据库已存在：{target_path}（使用 force=True 覆盖）")
        backup_path = target_path.parent / (
            f"{target_path.stem}-before-migrate-{datetime.now():%Y%m%d-%H%M%S}.db"
        )
        try:
            previous = db.backup_database(target_path, backup_path)
        except sqlite3.DatabaseError:
            # 目标文件不是有效数据库，直接原样留档
            shutil.copyfile(target_path, backup_path)
            previous = backup_path

    staging = target_path.with_suffix(target_path.suffix + ".migrating")
    staging.unlink(missing_ok=True)
    _copy_database(source_path, staging)

    check = db.validate_database_file(staging)
    if not check.get("ok"):
        staging.unlink(missing_ok=True)
        raise ValueError(f"复制后的数据库不完整：{check.get('reason')}")

    source_conn = db.connect(source_path, readonly=True, wal=False)
    try:
        source_counts = db.table_counts(source_conn)
        source_columns = {table: db.table_columns(source_conn, table) for table in db.CORE_TABLES}
        source_checksums = {
            table: db.table_checksum(source_conn, table, source_columns[table])
            for table in db.CORE_TABLES
        }
        source_pd_audit = audit_pd(source_conn)
    finally:
        source_conn.close()

    conn = db.connect(staging, wal=False)
    try:
        db.init_schema(conn)

        # 先比对「纯复制」是否逐表一致（此时尚未做任何修正）
        target_counts = db.table_counts(conn)
        copy_checksums = {
            table: db.table_checksum(conn, table, source_columns[table])
            for table in db.CORE_TABLES
        }
        counts_equal = target_counts == source_counts
        copy_checksums_equal = copy_checksums == source_checksums

        fixes: dict[str, Any] = {"recalculated_batches": 0}
        if fix_pd:
            for row in conn.execute("SELECT id FROM culture_batches").fetchall():
                if recalculate_batch(conn, int(row["id"])) is not None:
                    fixes["recalculated_batches"] += 1
            conn.commit()

        active_problems = audit_active_records(conn)
        final_pd_audit = audit_pd(conn)

        db.set_meta(conn, "schema_version", str(SCHEMA_VERSION))
        db.set_meta(conn, "migrated_from", str(source_path))
        db.set_meta(conn, "migrated_at", datetime.now().isoformat(timespec="seconds"))
        conn.commit()
    finally:
        conn.close()

    for suffix in ("-wal", "-shm"):
        Path(str(staging) + suffix).unlink(missing_ok=True)
        Path(str(target_path) + suffix).unlink(missing_ok=True)
    try:
        staging.replace(target_path)
    except PermissionError:
        # 某些 Windows 环境下覆盖只读/特殊 ACL 的旧文件会失败，退化为先删后换
        target_path.unlink(missing_ok=True)
        staging.replace(target_path)

    pd_clean = final_pd_audit["mismatch_count"] == 0

    if not counts_equal or not copy_checksums_equal:
        status = "mismatch"
    elif not pd_clean or active_problems:
        status = "ok_with_warnings"
    else:
        status = "ok"

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(source_path),
        "target": str(target_path),
        "previous_target_backup": str(previous) if previous else None,
        "source_counts": source_counts,
        "target_counts": target_counts,
        "counts_equal": counts_equal,
        "checksums_equal": copy_checksums_equal,
        "source_pd_audit": source_pd_audit,
        "pd_audit": final_pd_audit,
        "active_record_problems": active_problems,
        "fixes": fixes,
        "source_issues": info.get("issues", []),
        "status": status,
    }

    if write_report:
        destination = Path(report_path) if report_path else target_path.parent / "migration-report.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(destination)

    if not counts_equal or not copy_checksums_equal:
        raise RuntimeError(
            "迁移校验失败：源库与目标库数据不一致（目标库已保留以便排查）\n"
            + json.dumps({"source": source_counts, "target": target_counts}, ensure_ascii=False, indent=2)
        )

    return report


def find_legacy_database() -> Path | None:
    for candidate in LEGACY_DB_CANDIDATES:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def ensure_database(config: Config, *, auto_migrate: bool = True) -> dict[str, Any]:
    """确保目标数据库存在；首次运行时自动从旧版数据库迁移。"""
    config.ensure_dirs()
    if config.db_path.exists() and config.db_path.stat().st_size > 0:
        conn = db.connect(config.db_path)
        try:
            db.init_schema(conn)
        finally:
            conn.close()
        return {"created": False, "migrated": False, "db_path": str(config.db_path)}

    legacy = find_legacy_database() if auto_migrate else None
    if legacy is not None and legacy.resolve() != config.db_path.resolve():
        report = migrate_database(
            legacy,
            config.db_path,
            write_report=True,
            report_path=config.db_path.parent / "migration-report.json",
        )
        return {
            "created": True,
            "migrated": True,
            "db_path": str(config.db_path),
            "source": str(legacy),
            "report": report,
        }

    conn = db.connect(config.db_path)
    try:
        db.init_schema(conn)
        db.set_meta(conn, "created_at", datetime.now().isoformat(timespec="seconds"))
    finally:
        conn.close()
    return {"created": True, "migrated": False, "db_path": str(config.db_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="迁移并校验旧版 CellTracker 数据库")
    parser.add_argument("--source", required=True, help="旧版 cell_data.db 路径")
    parser.add_argument("--target", required=True, help="新数据库路径")
    parser.add_argument("--force", action="store_true", help="目标已存在时覆盖（会先备份）")
    parser.add_argument("--fix-pd", action="store_true", help="迁移时按当前规则重算累计 PD")
    parser.add_argument("--report", default=None, help="校验报告输出路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出报告")
    args = parser.parse_args(argv)

    try:
        report = migrate_database(
            args.source,
            args.target,
            force=args.force,
            fix_pd=args.fix_pd,
            report_path=args.report,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 输出友好错误
        print(f"迁移失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"源数据库：{report['source']}")
        print(f"目标数据库：{report['target']}")
        print("表行数：" + "，".join(f"{name}={count}" for name, count in report["target_counts"].items()))
        print(f"逐表校验和一致：{'是' if report['checksums_equal'] else '否'}")
        print(f"PD 历史偏差：{report['pd_audit']['mismatch_count']} / {report['pd_audit']['records_checked']}")
        if report.get("report_path"):
            print(f"校验报告：{report['report_path']}")
        print(f"状态：{report['status']}")
    return 0 if report["status"].startswith("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
