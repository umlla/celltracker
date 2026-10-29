"""业务规则单元测试：PD 公式、日期/数字解析、Excel 单元格解析。"""

from __future__ import annotations

import math

import pytest

from backend import db
from backend.domain import (
    calc_pd,
    parse_cell_text,
    parse_date_value,
    parse_number,
    recalculate_batch,
    refresh_active_record,
)


def test_calc_pd_basic():
    assert calc_pd(4.0, 4.0) == 0.0
    assert calc_pd(8.0, 4.0) == 1.0
    assert calc_pd(16.0, 2.0) == 3.0
    assert calc_pd(4.12, 4.12) == 0.0


def test_calc_pd_invalid_and_negative():
    assert calc_pd(0, 4) == 0.0
    assert calc_pd(4, 0) == 0.0
    assert calc_pd(None, 4) == 0.0
    assert calc_pd("abc", 4) == 0.0
    # 收获少于接种时单次 PD 为负，但累计 PD 只加正数（由 recalculate_batch 处理）
    assert calc_pd(1.0, 4.0) == pytest.approx(-2.0, abs=0.01)


def test_parse_number_variants():
    assert parse_number("5.1X10^5") == pytest.approx(510000)
    assert parse_number("5.1×105") == pytest.approx(510000)
    assert parse_number("1.2*10^6") == pytest.approx(1_200_000)
    assert parse_number("1,200") == 1200
    assert parse_number("3.5") == 3.5
    assert parse_number("") is None
    assert parse_number("未知") is None
    assert parse_number(None) is None
    assert parse_number(True) is None


def test_parse_date_variants():
    assert parse_date_value("2026-04-15") == "2026-04-15"
    assert parse_date_value("2022.4.15") == "2022-04-15"
    assert parse_date_value("2022/04/15") == "2022-04-15"
    assert parse_date_value("2026-1-5") == "2026-01-05"
    assert parse_date_value("2026") == "2026-01-01"
    assert parse_date_value("2026-02") == "2026-02-01"
    assert parse_date_value("不是日期") is None
    assert parse_date_value("") is None


def test_parse_cell_text_multiline():
    parsed = parse_cell_text("HeLa\n5.1X10^5\nPD=10.26\n2022.4.15\n2023.5.1")
    assert parsed["cell_name"] == "HeLa"
    assert parsed["cell_count"] == pytest.approx(510000)
    assert parsed["pd"] == pytest.approx(10.26)
    assert parsed["freeze_date"] == "2022-04-15"
    assert parsed["revived_date"] == "2023-05-01"
    assert parsed["status"] == "已复苏"


def test_parse_cell_text_single_line_and_notes():
    parsed = parse_cell_text("A549  3.2X10^6  2024.1.2  备用")
    assert parsed["cell_name"] == "A549"
    assert parsed["cell_count"] == pytest.approx(3.2e6)
    assert parsed["freeze_date"] == "2024-01-02"
    assert parsed["status"] == "在库"
    assert "备用" in parsed["notes"]
    assert parse_cell_text("   ") is None


def test_recalculate_only_adds_positive_pd(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO cell_lines (name, type, revival_date) VALUES ('L', '永生化', '2026-01-01')"
    )
    line_id = conn.execute("SELECT id FROM cell_lines").fetchone()[0]
    conn.execute(
        "INSERT INTO culture_batches (cell_line_id, batch_name, revival_date, initial_pd, "
        "initial_cell_count, is_active) VALUES (?, 'B', '2026-01-01', 1.0, 4.0, 1)",
        (line_id,),
    )
    batch_id = conn.execute("SELECT id FROM culture_batches").fetchone()[0]
    conn.execute(
        "INSERT INTO culture_records (batch_id, passage, date, inoculum_cells, inoculum_dishes, "
        "harvested_cells, is_active) VALUES (?, 1, '2026-01-02', 2.0, 1, 1.0, 1)",
        (batch_id,),
    )
    conn.execute(
        "INSERT INTO culture_records (batch_id, passage, date, inoculum_cells, inoculum_dishes, "
        "harvested_cells, is_active) VALUES (?, 2, '2026-01-04', 2.0, 1, 8.0, 1)",
        (batch_id,),
    )
    conn.commit()

    result = recalculate_batch(conn, batch_id)
    rows = conn.execute(
        "SELECT passage, pd, cumulative_pd FROM culture_records ORDER BY passage"
    ).fetchall()
    conn.commit()

    # 第一次收获 1 / 起始 4 => PD=-2，累计仍为 1
    assert rows[0]["pd"] == pytest.approx(-2.0)
    assert rows[0]["cumulative_pd"] == pytest.approx(1.0)
    # 第二次收获 8 / 上次接种 2 => PD=2，累计 3
    assert rows[1]["pd"] == pytest.approx(2.0)
    assert rows[1]["cumulative_pd"] == pytest.approx(3.0)
    assert result["cumulative_pd"] == pytest.approx(3.0)

    active = refresh_active_record(conn, batch_id)
    assert active == conn.execute(
        "SELECT id FROM culture_records WHERE passage = 2"
    ).fetchone()["id"]
    assert conn.execute(
        "SELECT SUM(is_active) FROM culture_records WHERE batch_id = ?", (batch_id,)
    ).fetchone()[0] == 1
    conn.close()
