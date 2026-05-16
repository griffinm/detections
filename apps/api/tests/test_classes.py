"""Tests for the classes endpoint."""


async def test_list_classes_returns_seeded_builtins(client):  # type: ignore[no-untyped-def]
    resp = await client.get("/api/classes")
    assert resp.status_code == 200

    by_name = {c["name"]: c for c in resp.json()}
    assert set(by_name) == {"person", "car", "dog", "bear"}
    assert by_name["person"]["yolo_class_index"] == 0
    assert by_name["dog"]["yolo_class_index"] == 16
    assert by_name["car"]["source"] == "builtin"


async def test_create_update_delete_class(client):  # type: ignore[no-untyped-def]
    created = await client.post(
        "/api/classes", json={"name": "deer", "color_hex": "#22c55e"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["source"] == "custom"
    assert body["is_active"] is True
    class_id = body["id"]

    # Duplicate name is rejected.
    dup = await client.post("/api/classes", json={"name": "deer"})
    assert dup.status_code == 409

    patched = await client.patch(
        f"/api/classes/{class_id}", json={"color_hex": "#000000"}
    )
    assert patched.status_code == 200
    assert patched.json()["color_hex"] == "#000000"

    # Delete is a soft deactivate.
    assert (await client.delete(f"/api/classes/{class_id}")).status_code == 204
    listing = await client.get("/api/classes")
    deer = next(c for c in listing.json() if c["id"] == class_id)
    assert deer["is_active"] is False
