import importlib
import sys

from fastapi.testclient import TestClient


def load_server(monkeypatch, tmp_path):
    monkeypatch.setenv("LICENSE_DB_PATH", str(tmp_path / "licenses.db"))
    monkeypatch.setenv("LICENSE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("LICENSE_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("LICENSE_PRODUCT_ID", "autopiar")

    sys.modules.pop("license_server.server", None)
    module = importlib.import_module("license_server.server")
    module.init_db()
    return module


def test_license_key_lifecycle(monkeypatch, tmp_path):
    server = load_server(monkeypatch, tmp_path)
    client = TestClient(server.app)
    headers = {"x-admin-token": "test-admin-token"}

    created = client.post(
        "/admin/keys",
        headers=headers,
        json={"owner": "client", "days": 30, "max_devices": 1, "license_type": "user"},
    )
    assert created.status_code == 200
    license_key = created.json()["license"]["key"]

    first_activation = client.post(
        "/api/activate",
        json={
            "license_key": license_key,
            "device_id": "device-0001",
            "product": "autopiar",
            "hostname": "pc-one",
            "platform": "Windows",
        },
    )
    assert first_activation.status_code == 200
    assert first_activation.json()["ok"] is True
    assert first_activation.json()["devices"] == 1

    over_limit = client.post(
        "/api/activate",
        json={
            "license_key": license_key,
            "device_id": "device-0002",
            "product": "autopiar",
            "hostname": "pc-two",
            "platform": "Windows",
        },
    )
    assert over_limit.status_code == 200
    assert over_limit.json()["ok"] is False

    revoked = client.post(f"/admin/keys/{license_key}/revoke", headers=headers)
    assert revoked.status_code == 200
    assert revoked.json()["ok"] is True

    after_revoke = client.post(
        "/api/activate",
        json={
            "license_key": license_key,
            "device_id": "device-0001",
            "product": "autopiar",
            "hostname": "pc-one",
            "platform": "Windows",
        },
    )
    assert after_revoke.status_code == 200
    assert after_revoke.json()["ok"] is False


def test_admin_html_uses_cookie_not_query_token(monkeypatch, tmp_path):
    server = load_server(monkeypatch, tmp_path)
    client = TestClient(server.app)

    login = client.post(
        "/admin/login",
        data={"token": "test-admin-token"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert server.ADMIN_COOKIE_NAME in login.cookies

    client.cookies.set(server.ADMIN_COOKIE_NAME, login.cookies[server.ADMIN_COOKIE_NAME])
    page = client.get("/admin")
    assert page.status_code == 200
    assert "?token=" not in page.text
    assert 'name="token"' not in page.text

    export_response = client.get("/admin/export.json")
    assert export_response.status_code == 200
    assert export_response.json()["product"] == "autopiar"
