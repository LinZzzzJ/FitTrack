from fittrack.routes import COOKIE

from conftest import register


def test_mobile_pairing_is_one_time_and_bearer_scoped(client):
    register(client, "pair-user")
    created = client.post("/api/mobile/pair/create")
    assert created.status_code == 200
    code = created.json()["code"]
    assert len(code) == 8 and code.isdigit()

    redeemed = client.post("/api/mobile/pair/redeem", json={"code": code})
    assert redeemed.status_code == 200, redeemed.text
    token = redeemed.json()["token"]
    assert token

    second = client.post("/api/mobile/pair/redeem", json={"code": code})
    assert second.status_code == 401
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "pair-user"

    logged_out = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logged_out.status_code == 204
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert COOKIE not in logged_out.cookies


def test_mobile_pairing_rejects_malformed_code(client):
    register(client, "pair-invalid")
    response = client.post("/api/mobile/pair/redeem", json={"code": "abc"})
    assert response.status_code == 400


def test_native_origin_preflight_is_limited_to_mobile_headers(client):
    response = client.options(
        "/api/mobile/pair/redeem",
        headers={
            "Origin": "capacitor://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "capacitor://localhost"
    assert "Authorization" in response.headers["access-control-allow-headers"]


def test_untrusted_origin_is_rejected(client):
    register(client, "origin-user")
    response = client.get("/api/me", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_native_origin_cannot_reuse_pc_cookie(client):
    register(client, "cookie-owner")
    assert client.get("/api/me", headers={"Origin": "capacitor://localhost"}).status_code == 403


def test_pairing_expiry_and_replacement(client, store):
    register(client, "expiring-owner")
    old = client.post("/api/mobile/pair/create").json()["code"]
    new = client.post("/api/mobile/pair/create").json()["code"]
    assert client.post("/api/mobile/pair/redeem", json={"code": old}).status_code == 401
    store.db.execute("UPDATE mobile_pairings SET expires_at=0")
    assert client.post("/api/mobile/pair/redeem", json={"code": new}).status_code == 401


def test_device_revoke_is_owner_scoped(client):
    register(client, "device-owner")
    code = client.post("/api/mobile/pair/create").json()["code"]
    token = client.post("/api/mobile/pair/redeem", json={"code": code}).json()["token"]
    device = client.get("/api/mobile/devices").json()[0]["id"]
    assert client.delete("/api/mobile/devices/" + device).status_code == 204
    assert client.get("/api/me", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_pairing_limiter_is_per_application_and_bounded(client):
    for _ in range(10):
        assert client.post("/api/mobile/pair/redeem", json={"code": "00000000"}).status_code == 401
    assert client.post("/api/mobile/pair/redeem", json={"code": "00000000"}).status_code == 429
