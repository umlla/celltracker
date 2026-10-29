"""认证层测试：默认关闭、开启后登录/登出、账号管理。"""

from __future__ import annotations

from backend import db
from backend.auth import create_user, list_users, set_password


def test_auth_disabled_by_default(client):
    status = client.get("/api/auth/status").get_json()
    assert status["enabled"] is False
    assert status["authenticated"] is True
    assert status["username"] == "local"
    assert client.get("/api/cell-lines").status_code == 200
    # 未启用时登录接口给出明确提示
    assert client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code == 400


def test_auth_enabled_guards_api(auth_app):
    client = auth_app.test_client()
    assert client.get("/api/healthz").status_code == 200
    protected = client.get("/api/cell-lines")
    assert protected.status_code == 401
    assert protected.get_json()["error"]["code"] == "unauthorized"

    wrong = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert wrong.status_code == 401

    login = client.post("/api/auth/login", json={"username": "admin", "password": "celltracker"})
    assert login.status_code == 200
    assert login.get_json()["username"] == "admin"

    assert client.get("/api/cell-lines").status_code == 200
    me = client.get("/api/auth/me").get_json()
    assert me["authenticated"] is True
    assert me["username"] == "admin"

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/cell-lines").status_code == 401


def test_user_management(auth_config):
    conn = db.connect(auth_config.db_path)
    try:
        db.init_schema(conn)
        user = create_user(conn, "alice", "secret123", "Alice")
        assert user["username"] == "alice"
        assert len(list_users(conn)) == 1
        set_password(conn, "alice", "newsecret")
        conn.commit()
    finally:
        conn.close()

    from backend import create_app

    app = create_app(auth_config)
    client = app.test_client()
    assert client.post("/api/auth/login", json={
        "username": "alice", "password": "secret123",
    }).status_code == 401
    assert client.post("/api/auth/login", json={
        "username": "alice", "password": "newsecret",
    }).status_code == 200
