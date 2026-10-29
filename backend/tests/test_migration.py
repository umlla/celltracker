"""迁移与校验测试：旧库整库复制、校验和、PD/活跃记录审计。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend import db
from backend.config import Config
from backend.migrate import (
    audit_active_records,
    audit_pd,
    ensure_database,
    migrate_database,
)

LEGACY_SCHEMA = """
CREATE TABLE cell_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    revival_date TEXT,
    type TEXT,
    default_passage_interval INTEGER DEFAULT 0,
    notes TEXT
);
CREATE TABLE culture_batches (
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
    notes TEXT
);
CREATE TABLE culture_records (
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
    notes TEXT
);
CREATE TABLE frozen_vials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_line_id INTEGER,
    batch_id INTEGER,
    freeze_date TEXT,
    cell_count REAL,
    location TEXT DEFAULT '',
    pd REAL,
    status TEXT DEFAULT '在库',
    notes TEXT
);
CREATE TABLE cell_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL UNIQUE,
    notes TEXT
);
CREATE TABLE cell_group_members (
    group_id INTEGER,
    cell_line_id INTEGER,
    PRIMARY KEY (group_id, cell_line_id)
);
"""


def build_legacy_db(path: Path, *, corrupt_pd: bool = False, wrong_active: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO cell_lines (id, name, revival_date, type, default_passage_interval, notes) "
        "VALUES (1, '旧细胞', '2026-01-01', '永生化', 2, '旧库')"
    )
    conn.execute(
        "INSERT INTO culture_batches (id, cell_line_id, batch_name, revival_date, source_freeze_date, "
        "initial_pd, initial_cell_count, is_active, notes) VALUES (1, 1, '旧细胞-260101', "
        "'2026-01-01', '2025-12-01', 1.0, 2.0, 1, '')"
    )
    first_cumulative = 2.0 + (99 if corrupt_pd else 0)
    conn.execute(
        "INSERT INTO culture_records (id, batch_id, passage, date, inoculum_cells, inoculum_dishes, "
        "harvested_cells, pd, cumulative_pd, status, next_passage_date, is_active, notes) "
        "VALUES (1, 1, 1, '2026-01-02', 2.0, 2, 4.0, 1.0, ?, '良好', '2026-01-04', ?, '')",
        (first_cumulative, 1 if wrong_active else 0),
    )
    conn.execute(
        "INSERT INTO culture_records (id, batch_id, passage, date, inoculum_cells, inoculum_dishes, "
        "harvested_cells, pd, cumulative_pd, status, next_passage_date, is_active, notes) "
        "VALUES (2, 1, 2, '2026-01-04', 2.0, 2, 8.0, 2.0, ?, '良好', NULL, ?, '')",
        (4.0 + (99 if corrupt_pd else 0), 0 if wrong_active else 1),
    )
    conn.execute("INSERT INTO cell_groups (id, group_name, notes) VALUES (1, '旧组', '')")
    conn.execute("INSERT INTO cell_group_members (group_id, cell_line_id) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO frozen_vials (id, cell_line_id, batch_id, freeze_date, cell_count, location, pd, status, notes) "
        "VALUES (1, 1, NULL, '2025-12-01', 1000000, '罐A/架1/盒1/A1', 3.5, '在库', '')"
    )
    conn.commit()
    conn.close()


def test_migrate_copies_everything_and_adds_schema(tmp_path: Path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "data" / "cell_data.db"
    build_legacy_db(source)

    report = migrate_database(source, target)

    assert report["status"] == "ok"
    assert report["counts_equal"] is True
    assert report["checksums_equal"] is True
    assert report["pd_audit"]["mismatch_count"] == 0
    assert report["source_counts"] == {
        "cell_lines": 1, "culture_batches": 1, "culture_records": 2,
        "frozen_vials": 1, "cell_groups": 1, "cell_group_members": 1,
    }
    assert Path(report["report_path"]).exists()

    conn = db.connect(target)
    try:
        columns = db.table_columns(conn, "cell_group_members")
        assert "sort_order" in columns
        assert db.get_meta(conn, "schema_version") == "1"
        assert db.get_meta(conn, "migrated_from") == str(source.resolve())
        # 原有 id 全部保留
        assert conn.execute("SELECT id FROM culture_batches").fetchone()["id"] == 1
        assert conn.execute("SELECT COUNT(*) FROM culture_records").fetchone()[0] == 2
    finally:
        conn.close()


def test_migrate_reports_pd_mismatch_and_can_fix(tmp_path: Path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "target.db"
    build_legacy_db(source, corrupt_pd=True)

    report = migrate_database(source, target)
    assert report["status"] == "ok_with_warnings"
    assert report["checksums_equal"] is True
    assert report["pd_audit"]["mismatch_count"] == 2

    conn = db.connect(target, readonly=True, wal=False)
    try:
        assert audit_pd(conn)["mismatch_count"] == 2
    finally:
        conn.close()

    fixed = migrate_database(source, target, force=True, fix_pd=True)
    assert fixed["status"] == "ok"
    assert fixed["fixes"]["recalculated_batches"] == 1
    assert fixed["pd_audit"]["mismatch_count"] == 0

    conn = db.connect(target, readonly=True, wal=False)
    try:
        rows = conn.execute(
            "SELECT pd, cumulative_pd FROM culture_records ORDER BY id"
        ).fetchall()
        assert [row["cumulative_pd"] for row in rows] == pytest.approx([2.0, 4.0])
    finally:
        conn.close()


def test_migrate_reports_active_record_problem_without_changing_data(tmp_path: Path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "target.db"
    build_legacy_db(source, wrong_active=True)

    source_conn = db.connect(source, readonly=True, wal=False)
    try:
        expected = db.table_checksum(source_conn, "culture_records")
    finally:
        source_conn.close()

    report = migrate_database(source, target)
    assert report["status"] == "ok_with_warnings"
    assert report["checksums_equal"] is True
    assert len(report["active_record_problems"]) == 1
    assert report["active_record_problems"][0]["latest_record_id"] == 2

    conn = db.connect(target, readonly=True, wal=False)
    try:
        assert db.table_checksum(conn, "culture_records") == expected
        assert audit_active_records(conn)[0]["active_record_id"] == 1
    finally:
        conn.close()


def test_migrate_requires_force_when_target_exists(tmp_path: Path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "target.db"
    build_legacy_db(source)
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        migrate_database(source, target)

    report = migrate_database(source, target, force=True)
    assert report["status"] == "ok"
    assert report["previous_target_backup"] is not None


def test_migrate_rejects_unknown_database(tmp_path: Path):
    source = tmp_path / "random.db"
    conn = sqlite3.connect(str(source))
    conn.execute("CREATE TABLE random (id INTEGER PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError):
        migrate_database(source, tmp_path / "target.db")


def test_ensure_database_auto_migrates_legacy(tmp_path: Path, monkeypatch):
    legacy = tmp_path / "cell_data.db"
    build_legacy_db(legacy)
    import backend.migrate as migrate_module

    monkeypatch.setattr(migrate_module, "LEGACY_DB_CANDIDATES", (legacy,))
    config = Config(
        db_path=tmp_path / "data" / "cell_data.db",
        backup_dir=tmp_path / "backups",
        frontend_dist=tmp_path / "dist",
    )
    info = ensure_database(config)
    assert info["migrated"] is True
    assert info["source"] == str(legacy)
    assert config.db_path.exists()
    assert (config.db_path.parent / "migration-report.json").exists()

    # 再次启动不会重复迁移
    again = ensure_database(config)
    assert again["migrated"] is False
