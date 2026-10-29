"""认证层（默认关闭）。

单用户本地使用时无需登录；在 config.json 中把 auth.enabled 设为 true
即可启用基于会话的用户名/密码登录。密码使用 werkzeug 的 PBKDF2 哈希。

命令行管理用户：
    python -m backend.auth create-user --username alice --password secret
    python -m backend.auth list-users
    python -m backend.auth set-password --username alice --password newsecret
"""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .config import Config
from .errors import ApiError, ValidationError

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

AUTH_ALLOWLIST = ("/api/auth/", "/api/healthz")
USERNAME_MAX = 60


def get_config() -> Config:
    return current_app.config["CELLTRACKER_CONFIG"]


def load_or_create_secret(config: Config) -> str:
    path = config.db_path.parent / ".secret_key"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


def _hash(password: str) -> str:
    return generate_password_hash(password)


def create_user(conn, username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
    username = (username or "").strip()
    if not username or len(username) > USERNAME_MAX:
        raise ValidationError(f"用户名不能为空且不超过 {USERNAME_MAX} 字符")
    if len(password or "") < 6:
        raise ValidationError("密码至少 6 位")
    if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        raise ValidationError(f"用户「{username}」已存在")
    cursor = conn.execute(
        "INSERT INTO users (username, password_hash, display_name, is_active, created_at) VALUES (?,?,?,1,?)",
        (username, _hash(password), display_name or username, datetime.now().isoformat(timespec="seconds")),
    )
    return {"id": int(cursor.lastrowid), "username": username, "display_name": display_name or username}


def set_password(conn, username: str, password: str) -> dict[str, Any]:
    if len(password or "") < 6:
        raise ValidationError("密码至少 6 位")
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row is None:
        raise ValidationError(f"用户「{username}」不存在")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash(password), row["id"]))
    return {"id": int(row["id"]), "username": username}


def list_users(conn) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, username, display_name, is_active, created_at FROM users ORDER BY username"
        ).fetchall()
    ]


def bootstrap_user(config: Config) -> None:
    conn = db.connect(config.db_path)
    try:
        with conn:
            db.init_schema(conn)
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                create_user(conn, config.bootstrap_username, config.bootstrap_password, "管理员")
                print(
                    f"[auth] 已创建默认账号 {config.bootstrap_username} / {config.bootstrap_password}，"
                    "请登录后立即修改密码"
                )
    finally:
        conn.close()


def authenticate(conn, username: str, password: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, username, password_hash, display_name, is_active FROM users WHERE username = ?",
        ((username or "").strip(),),
    ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        raise ApiError("用户名或密码不正确", status=401, code="invalid_credentials")
    if not int(row["is_active"]):
        raise ApiError("该账号已被禁用", status=403, code="user_disabled")
    return {"id": int(row["id"]), "username": row["username"], "display_name": row["display_name"]}


def current_username() -> str | None:
    config = get_config()
    if not config.auth_enabled:
        return "local"
    return session.get("username")


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(*args, **kwargs):
        config = get_config()
        if config.auth_enabled and not session.get("username"):
            return jsonify({"error": {"code": "unauthorized", "message": "请先登录"}}), 401
        return view(*args, **kwargs)

    return wrapper


@auth_bp.get("/status")
def auth_status():
    config = get_config()
    return jsonify({
        "enabled": config.auth_enabled,
        "authenticated": (not config.auth_enabled) or bool(session.get("username")),
        "username": (session.get("username") if config.auth_enabled else "local"),
        "display_name": session.get("display_name") if config.auth_enabled else "本地用户",
    })


@auth_bp.get("/me")
def auth_me():
    config = get_config()
    if not config.auth_enabled:
        return jsonify({"authenticated": True, "username": "local", "display_name": "本地用户",
                        "auth_enabled": False})
    username = session.get("username")
    return jsonify({
        "authenticated": bool(username),
        "username": username,
        "display_name": session.get("display_name"),
        "auth_enabled": True,
    })


@auth_bp.post("/login")
def auth_login():
    config = get_config()
    if not config.auth_enabled:
        raise ApiError("当前未启用登录认证", status=400, code="auth_disabled")
    payload = request.get_json(silent=True) or request.form or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or not password:
        raise ValidationError("请输入用户名和密码")
    conn = db.connect(config.db_path)
    try:
        user = authenticate(conn, username, password)
        session.permanent = True
        session["username"] = user["username"]
        session["display_name"] = user["display_name"]
        session["user_id"] = user["id"]
    finally:
        conn.close()
    return jsonify({"authenticated": True, **user})


@auth_bp.post("/logout")
def auth_logout():
    session.clear()
    return jsonify({"authenticated": False})


def init_auth(app, config: Config) -> None:
    app.secret_key = load_or_create_secret(config)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=config.session_days),
    )
    app.register_blueprint(auth_bp)

    @app.before_request
    def _guard():
        if not config.auth_enabled:
            return None
        path = request.path
        if not path.startswith("/api/"):
            return None
        if any(path.startswith(prefix) for prefix in AUTH_ALLOWLIST):
            return None
        if session.get("username"):
            return None
        return jsonify({"error": {"code": "unauthorized", "message": "请先登录"}}), 401

    if config.auth_enabled:
        bootstrap_user(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CellTracker 用户管理")
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create-user", help="创建用户")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument("--password", required=True)
    create_parser.add_argument("--display-name", default=None)

    password_parser = sub.add_parser("set-password", help="修改密码")
    password_parser.add_argument("--username", required=True)
    password_parser.add_argument("--password", required=True)

    sub.add_parser("list-users", help="列出用户")

    args = parser.parse_args(argv)
    config = Config.load()
    conn = db.connect(config.db_path)
    try:
        with conn:
            db.init_schema(conn)
            if args.command == "create-user":
                user = create_user(conn, args.username, args.password, args.display_name)
                print(f"已创建用户 {user['username']}（id={user['id']}）")
            elif args.command == "set-password":
                set_password(conn, args.username, args.password)
                print(f"已更新 {args.username} 的密码")
            else:
                for user in list_users(conn):
                    print(f"{user['id']:>3}  {user['username']:<20} {user['display_name'] or ''}  "
                          f"{'启用' if user['is_active'] else '禁用'}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
