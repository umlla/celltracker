"""服务层公共工具。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator, Sequence

from ..errors import NotFound, ValidationError


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def audit(
    conn: sqlite3.Connection,
    username: str | None,
    action: str,
    entity: str | None = None,
    entity_id: int | None = None,
    detail: Any = None,
) -> None:
    import json

    conn.execute(
        "INSERT INTO audit_log(ts, username, action, entity, entity_id, detail) VALUES(?,?,?,?,?,?)",
        (now_iso(), username, action, entity, entity_id,
         json.dumps(detail, ensure_ascii=False) if detail is not None else None),
    )


@contextmanager
def savepoint(conn: sqlite3.Connection, name: str = "sp") -> Iterator[None]:
    """S AVEPOINT 包裹单个条目，批量操作时隔离失败项。"""
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    else:
        conn.execute(f"RELEASE {name}")


def placeholders(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


def fetch_one(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, tuple(params)).fetchone()
    return dict(row) if row is not None else None


def fetch_all(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def get_or_404(conn: sqlite3.Connection, table: str, entity_id: int, label: str = "记录") -> dict[str, Any]:
    row = fetch_one(conn, f'SELECT * FROM "{table}" WHERE id = ?', (entity_id,))
    if row is None:
        raise NotFound(f"{label}不存在（id={entity_id}）")
    return row


def require_non_empty(value: Any, field: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValidationError(f"{field}不能为空")
    return text
