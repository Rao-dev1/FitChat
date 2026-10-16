import base64
from datetime import date, timedelta

import pytest

from app.services import body as bd

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def b64(b):
    return "data:image/jpeg;base64," + base64.b64encode(b).decode()


@pytest.fixture(autouse=True)
def photos(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "PHOTOS_DIR", tmp_path / "photos")
    return tmp_path / "photos"


def test_measures_merge_and_changes(client):
    d1 = (date.today() - timedelta(days=14)).isoformat()
    assert client.post("/api/body/measures", json={"day": d1, "waist_cm": 98, "chest_cm": 105}).status_code == 200
    client.post("/api/body/measures", json={"waist_cm": 95.5})
    client.post("/api/body/measures", json={"arm_cm": 36})  # same day: merges
    o = client.get("/api/body").json()
    assert len(o["measures"]) == 2
    today = o["measures"][-1]
    assert today["waist_cm"] == 95.5 and today["arm_cm"] == 36
    assert o["changes"]["waist_cm"]["change_cm"] == -2.5
    assert o["changes"]["arm_cm"]["change_cm"] is None
    assert o["days_since_measure"] == 0 and "Waist" in o["summary"]


@pytest.mark.parametrize("body", [{}, {"waist_cm": 5}, {"waist_cm": 400}, {"waist_cm": -3}])
def test_measures_validation(client, body):
    assert client.post("/api/body/measures", json=body).status_code == 422


def test_measures_future_refused_and_delete(client):
    assert client.post("/api/body/measures", json={"waist_cm": 90, "day": (date.today() + timedelta(days=1)).isoformat()}).status_code == 422
    client.post("/api/body/measures", json={"waist_cm": 90})
    assert client.delete(f"/api/body/measures/{date.today().isoformat()}").status_code == 200
    assert client.delete(f"/api/body/measures/{date.today().isoformat()}").status_code == 404


def test_photo_roundtrip(client, photos):
    r = client.post("/api/body/photos", json={"pose": "side", "image": b64(JPEG)})
    assert r.status_code == 200, r.text
    p = r.json()
    img = client.get(p["url"])
    assert img.status_code == 200 and img.content == JPEG
    assert len(list(photos.iterdir())) == 1
    assert client.get("/api/body").json()["photos"][0]["pose"] == "side"
    assert client.delete(f"/api/body/photos/{p['id']}").status_code == 200
    assert not list(photos.iterdir())
    assert client.get(p["url"]).status_code == 404


def test_photo_png_ok_and_validation(client):
    assert client.post("/api/body/photos", json={"image": base64.b64encode(PNG).decode()}).status_code == 200
    assert client.post("/api/body/photos", json={"image": b64(b"GIF89a" + b"0" * 60)}).status_code == 422  # not an image type we allow
    assert client.post("/api/body/photos", json={"image": "data:image/jpeg;base64,!!!notbase64!!!notbase64"}).status_code == 422
    assert client.post("/api/body/photos", json={"image": b64(JPEG), "pose": "top"}).status_code == 422
    big = b"\xff\xd8\xff" + b"0" * (bd.MAX_PHOTO_BYTES + 1)
    assert client.post("/api/body/photos", json={"image": b64(big)}).status_code in (422,)


def test_photo_filename_is_server_made(client, db, photos):
    r = client.post("/api/body/photos", json={"image": b64(JPEG)}).json()
    from app.models import ProgressPhoto
    row = db.get(ProgressPhoto, r["id"])
    assert "/" not in row.filename and ".." not in row.filename
    row.filename = "../../etc/passwd"  # a poisoned row can never escape the folder
    db.commit()
    assert client.get(r["url"]).status_code == 404
