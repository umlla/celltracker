"""传代记录服务。"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from ..domain import (
    STATUS_CHOICES,
    normalize_choice,
    normalize_date,
    normalize_int,
    normalize_number,
    normalize_text,
    recalculate_batch,
    refresh_active_record,
    today_iso,
)
from ..errors import Conflict, NotFound, ValidationError
from . import audit, fetch_all, fetch_one, get_or_404, savepoint


def _per_dish(record: dict[str, Any]) -> float:
    dishes = record.get("inoculum_dishes") or 0
    cells = record.get("inoculum_cells") or 0
    return round(cells / dishes, 2) if dishes else 0.0


def list_records(conn: sqlite3.Connection, batch_id: int) -> list[dict[str, Any]]:
    get_or_404(conn, "culture_batches", batch_id, "培养批次")
    records = fetch_all(
        conn,
        "SELECT * FROM culture_records WHERE batch_id = ? ORDER BY date ASC, id ASC",
        (batch_id,),
    )
    for record in records:
        record["per_dish_cells"] = _per_dish(record)
    return records


def _require_active_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any]:
    batch = get_or_404(conn, "culture_batches", batch_id, "培养批次")
    if not int(batch["is_active"]):
        raise Conflict("该批次已终止，不能再新增传代记录")
    return batch


def _next_passage(conn: sqlite3.Connection, batch_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(passage) AS max_passage FROM culture_records WHERE batch_id = ?", (batch_id,)
    ).fetchone()
    return int(row["max_passage"] or 0) + 1


MAX_FREEZE_VIALS = 200


def _parse_freeze_config(payload: dict[str, Any]) -> dict[str, Any] | None:
    """解析「传代时顺手冻存」的配置；未启用时返回 None。"""
    raw = payload.get("freeze_vials")
    if raw in (None, "", False):
        return None
    if not isinstance(raw, dict):
        raise ValidationError("冻存管参数格式不正确")
    if not bool(raw.get("enabled", True)):
        return None
    count = normalize_int(raw.get("count", 1), "复管数量", minimum=1)
    if count is None:
        count = 1
    if count > MAX_FREEZE_VIALS:
        raise ValidationError(f"一次最多添加 {MAX_FREEZE_VIALS} 支冻存管")
    per_vial = normalize_number(
        raw.get("cell_count_per_vial"), "每管冻存细胞数", required=True, minimum=0.0001
    )
    return {
        "count": count,
        "cell_count": per_vial,
        "include_pd": bool(raw.get("include_pd", True)),
    }


def _create_freeze_vials(
    conn: sqlite3.Connection, batch_id: int, record_id: int, config: dict[str, Any]
) -> list[int]:
    """按传代记录创建冻存管：日期取传代日期，PD 取当前累计 PD，位置留空。"""
    record = conn.execute(
        "SELECT date, passage, cumulative_pd FROM culture_records WHERE id = ?", (record_id,)
    ).fetchone()
    batch = conn.execute(
        "SELECT cell_line_id FROM culture_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    line = conn.execute(
        "SELECT type FROM cell_lines WHERE id = ?", (batch["cell_line_id"],)
    ).fetchone()

    cumulative = float(record["cumulative_pd"] or 0.0)
    # 原代细胞必须记录 PD；永生化细胞由调用方决定是否记录
    is_primary = bool(line and line["type"] == "原代")
    pd_value: float | None = cumulative if (is_primary or config["include_pd"]) else None

    created: list[int] = []
    for _ in range(config["count"]):
        cursor = conn.execute(
            "INSERT INTO frozen_vials "
            "(cell_line_id, batch_id, freeze_date, cell_count, location, pd, status, notes) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                int(batch["cell_line_id"]),
                int(batch_id),
                record["date"],
                config["cell_count"],
                "",
                pd_value,
                "在库",
                f"传代 P{record['passage']} 时自动添加",
            ),
        )
        created.append(int(cursor.lastrowid))
    return created


def _insert_record(conn: sqlite3.Connection, payload: dict[str, Any]) -> tuple[int, list[int]]:
    batch_id = normalize_int(payload.get("batch_id"), "批次", required=True)
    batch = _require_active_batch(conn, int(batch_id))
    freeze_config = _parse_freeze_config(payload)

    passage = normalize_int(payload.get("passage"), "传代次数", minimum=1)
    if passage is None:
        passage = _next_passage(conn, int(batch_id))

    record_date = normalize_date(payload.get("date"), "传代日期") or today_iso()
    harvested = normalize_number(payload.get("harvested_cells"), "收获细胞数", required=True, minimum=0)
    dishes = normalize_int(payload.get("inoculum_dishes"), "种下盘数", minimum=1)
    if dishes is None:
        dishes = 1

    per_dish = normalize_number(payload.get("per_dish_cells"), "每盘细胞数", minimum=0)
    inoculum = normalize_number(payload.get("inoculum_cells"), "接种细胞数", minimum=0)
    if per_dish is not None:
        inoculum = round(dishes * per_dish, 4)
    if inoculum is None:
        inoculum = 0.0

    status = normalize_choice(payload.get("status"), STATUS_CHOICES, "细胞状态", default="良好")
    notes = normalize_text(payload.get("notes"))

    next_days = normalize_int(payload.get("next_passage_days"), "下次传代间隔", minimum=0) or 0
    if next_days > 0:
        next_date: str | None = (date.fromisoformat(record_date) + timedelta(days=next_days)).isoformat()
    else:
        next_date = normalize_date(payload.get("next_passage_date"), "建议下次传代日期")

    cursor = conn.execute(
        "INSERT INTO culture_records (batch_id, passage, date, inoculum_cells, inoculum_dishes, "
        "harvested_cells, pd, cumulative_pd, status, next_passage_date, is_active, notes) "
        "VALUES (?,?,?,?,?,?,0,0,?,?,0,?)",
        (int(batch_id), passage, record_date, inoculum, dishes, harvested, status, next_date, notes),
    )
    record_id = int(cursor.lastrowid)
    recalculate_batch(conn, int(batch_id))
    refresh_active_record(conn, int(batch_id))

    vial_ids: list[int] = []
    if freeze_config is not None:
        vial_ids = _create_freeze_vials(conn, int(batch_id), record_id, freeze_config)
    return record_id, vial_ids


def create_record(conn: sqlite3.Connection, payload: dict[str, Any], user: str | None = None) -> dict[str, Any]:
    record_id, vial_ids = _insert_record(conn, payload)
    audit(conn, user, "create", "record", record_id,
          {"batch_id": payload.get("batch_id"), "vials": len(vial_ids)})
    record = fetch_one(conn, "SELECT * FROM culture_records WHERE id = ?", (record_id,))
    record["vials_created"] = vial_ids
    record["vials_count"] = len(vial_ids)
    return record


def bulk_create(conn: sqlite3.Connection, entries: list[dict[str, Any]],
                user: str | None = None) -> dict[str, Any]:
    if not isinstance(entries, list) or not entries:
        raise ValidationError("提交内容为空")
    results: list[dict[str, Any]] = []
    success = 0
    vials_total = 0
    for index, entry in enumerate(entries):
        try:
            with savepoint(conn, f"rec{index}"):
                record_id, vial_ids = _insert_record(conn, entry)
            success += 1
            vials_total += len(vial_ids)
            results.append({"index": index, "ok": True, "record_id": record_id,
                            "batch_id": entry.get("batch_id"), "vials_created": len(vial_ids)})
        except Exception as exc:  # noqa: BLE001 - 逐条返回错误
            results.append({"index": index, "ok": False, "batch_id": entry.get("batch_id"),
                            "error": getattr(exc, "message", str(exc))})
    audit(conn, user, "create_bulk", "record", None,
          {"success": success, "failed": len(results) - success, "vials": vials_total})
    return {"success": success, "failed": len(results) - success,
            "vials_created": vials_total, "results": results}


def update_record(conn: sqlite3.Connection, record_id: int, payload: dict[str, Any],
                  user: str | None = None) -> dict[str, Any]:
    record = get_or_404(conn, "culture_records", record_id, "传代记录")
    batch_id = int(record["batch_id"])

    assignments: dict[str, Any] = {}
    if "passage" in payload:
        passage = normalize_int(payload.get("passage"), "传代次数", minimum=1, required=True)
        assignments["passage"] = passage
    if "date" in payload:
        assignments["date"] = normalize_date(payload.get("date"), "传代日期", required=True)
    if "harvested_cells" in payload:
        assignments["harvested_cells"] = normalize_number(
            payload.get("harvested_cells"), "收获细胞数", required=True, minimum=0
        )
    if "inoculum_dishes" in payload:
        assignments["inoculum_dishes"] = normalize_int(
            payload.get("inoculum_dishes"), "种下盘数", minimum=1, required=True
        )
    if "per_dish_cells" in payload:
        per_dish = normalize_number(payload.get("per_dish_cells"), "每盘细胞数", minimum=0) or 0
        dishes = assignments.get("inoculum_dishes", record["inoculum_dishes"] or 1)
        assignments["inoculum_cells"] = round(float(dishes) * per_dish, 4)
    elif "inoculum_cells" in payload:
        assignments["inoculum_cells"] = normalize_number(
            payload.get("inoculum_cells"), "接种细胞数", minimum=0
        )
    if "status" in payload:
        assignments["status"] = normalize_choice(payload.get("status"), STATUS_CHOICES, "细胞状态")
    if "notes" in payload:
        assignments["notes"] = normalize_text(payload.get("notes"))

    record_date = assignments.get("date", record["date"])
    if "next_passage_days" in payload:
        days = normalize_int(payload.get("next_passage_days"), "下次传代间隔", minimum=0) or 0
        if days > 0:
            assignments["next_passage_date"] = (
                date.fromisoformat(record_date) + timedelta(days=days)
            ).isoformat()
        # 与旧版一致：填 0 表示不改动原有的下次传代日期
    elif "next_passage_date" in payload:
        assignments["next_passage_date"] = normalize_date(payload.get("next_passage_date"), "建议下次传代日期")

    if assignments:
        clause = ", ".join(f"{key} = ?" for key in assignments)
        conn.execute(
            f"UPDATE culture_records SET {clause} WHERE id = ?", (*assignments.values(), record_id)
        )
        recalculate_batch(conn, batch_id)
        refresh_active_record(conn, batch_id)
        audit(conn, user, "update", "record", record_id, {"fields": list(assignments)})

    updated = fetch_one(conn, "SELECT * FROM culture_records WHERE id = ?", (record_id,))
    if updated is None:
        raise NotFound("传代记录已被删除")
    updated["per_dish_cells"] = _per_dish(updated)
    return updated


def bulk_update(conn: sqlite3.Connection, entries: list[dict[str, Any]],
                user: str | None = None) -> dict[str, Any]:
    if not isinstance(entries, list) or not entries:
        raise ValidationError("提交内容为空")
    results: list[dict[str, Any]] = []
    success = 0
    for index, entry in enumerate(entries):
        record_id = entry.get("id") or entry.get("record_id")
        if not record_id:
            results.append({"index": index, "ok": False, "error": "缺少记录 id"})
            continue
        try:
            with savepoint(conn, f"upd{index}"):
                update_record(conn, int(record_id), entry, user=user)
            success += 1
            results.append({"index": index, "ok": True, "record_id": int(record_id)})
        except Exception as exc:  # noqa: BLE001
            results.append({"index": index, "ok": False, "record_id": int(record_id),
                            "error": getattr(exc, "message", str(exc))})
    return {"success": success, "failed": len(results) - success, "results": results}


def delete_record(conn: sqlite3.Connection, record_id: int, user: str | None = None) -> dict[str, Any]:
    record = get_or_404(conn, "culture_records", record_id, "传代记录")
    batch_id = int(record["batch_id"])
    conn.execute("DELETE FROM culture_records WHERE id = ?", (record_id,))
    recalculate_batch(conn, batch_id)
    refresh_active_record(conn, batch_id)
    audit(conn, user, "delete", "record", record_id, {"batch_id": batch_id})
    return {"deleted": record_id, "batch_id": batch_id}
