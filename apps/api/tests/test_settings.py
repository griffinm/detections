"""Tests for the DB-backed settings router + runtime override layer."""

import pytest


async def test_list_settings_reports_defaults(client):  # type: ignore[no-untyped-def]
    items = {s["key"]: s for s in (await client.get("/api/settings")).json()}
    assert "detect_batch_size" in items
    assert items["detect_batch_size"]["type"] == "integer"
    assert items["delete_frames_without_objects"]["type"] == "boolean"
    # With no overrides stored, effective value equals the env default.
    assert items["detect_batch_size"]["value"] == items["detect_batch_size"]["default"]


async def test_put_persists_and_changes_effective_value(client):  # type: ignore[no-untyped-def]
    resp = await client.put("/api/settings/detect_batch_size", json={"value": 8})
    assert resp.status_code == 200
    assert resp.json()["value"] == 8

    again = {s["key"]: s for s in (await client.get("/api/settings")).json()}
    assert again["detect_batch_size"]["value"] == 8
    assert again["detect_batch_size"]["default"] != 8  # override, not the default


async def test_put_unknown_key_is_404(client):  # type: ignore[no-untyped-def]
    # database_url is a real Settings field but not overridable.
    resp = await client.put("/api/settings/database_url", json={"value": "x"})
    assert resp.status_code == 404


async def test_put_bad_value_is_422(client):  # type: ignore[no-untyped-def]
    resp = await client.put(
        "/api/settings/detect_batch_size", json={"value": "not-a-number"}
    )
    assert resp.status_code == 422


async def test_delete_resets_to_default(client):  # type: ignore[no-untyped-def]
    await client.put("/api/settings/frame_fps", json={"value": 4})
    resp = await client.delete("/api/settings/frame_fps")
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == body["default"] == pytest.approx(1.0)
