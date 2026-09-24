from __future__ import annotations

import hashlib
import io
import time

from PIL import Image


def _png(color=(200, 30, 30), size=(800, 400)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _pdf() -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    pdf.new_page(595, 842)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _upload(c, bucket, name, data, path=None):
    files = {"file": (name, data)}
    return c.post(f"/storage/{bucket}/upload", files=files, data={"path": path} if path else None)


def test_upload_download_roundtrip_and_ledger(client_for):
    from kila.settings import get_settings
    from kila.storage.store import blob_path

    eng = client_for("engineer")
    data = _png()
    r = _upload(eng, "uploads", "scan.png", data)
    assert r.status_code == 200, r.text
    obj = r.json()
    assert obj["sha256"] == hashlib.sha256(data).hexdigest()
    assert obj["mime"] == "image/png" and obj["path"] == "scan.png"

    sha = obj["sha256"]
    expected = get_settings().buckets_dir / "uploads" / "objects" / sha[:2] / sha[2:4] / sha
    assert blob_path("uploads", sha) == expected and expected.exists()

    got = eng.get(f"/storage/object/{obj['object_id']}")
    assert got.status_code == 200 and got.content == data

    events = eng.get("/ledger/events?limit=1000").json()
    uploads = [e for e in events if e["event_type"] == "storage.upload" and e["payload"]["sha256"] == sha]
    reads = [e for e in events if e["event_type"] == "storage.read" and e["payload"]["sha256"] == sha]
    assert uploads and reads
    assert eng.get("/ledger/verify").json()["ok"]


def test_dedup_same_content_one_blob_two_rows(client_for):
    from kila.storage.store import blob_path

    eng = client_for("engineer")
    data = b"same bytes\n"
    a = _upload(eng, "uploads", "a.txt", data).json()
    b = _upload(eng, "uploads", "b.txt", data).json()
    assert a["sha256"] == b["sha256"] and a["object_id"] != b["object_id"]
    shard = blob_path("uploads", a["sha256"]).parent
    assert [p.name for p in shard.iterdir()] == [a["sha256"]]


def test_list_prefix_and_soft_delete(client_for):
    from kila.storage.store import blob_path

    eng = client_for("engineer")
    one = _upload(eng, "uploads", "r1.txt", b"one", path="reports/r1.txt").json()
    _upload(eng, "uploads", "x.txt", b"two", path="other/x.txt")
    listed = eng.get("/storage/uploads/list", params={"prefix": "reports/"}).json()
    assert [o["object_id"] for o in listed] == [one["object_id"]]

    assert eng.delete(f"/storage/object/{one['object_id']}").status_code == 204
    assert eng.get("/storage/uploads/list", params={"prefix": "reports/"}).json() == []
    assert eng.get(f"/storage/object/{one['object_id']}").status_code == 404
    assert blob_path("uploads", one["sha256"]).exists()  # blob retained for audit
    events = eng.get("/ledger/events?event_type=storage.delete").json()
    assert events[0]["payload"]["object_id"] == one["object_id"] and events[0]["payload"]["soft"] is True


def test_thumbnails_for_image_and_pdf(client_for):
    eng = client_for("engineer")
    for name, data in (("photo.png", _png()), ("report.pdf", _pdf())):
        obj = _upload(eng, "uploads", name, data).json()
        assert obj["metadata"].get("thumbnail_object_id"), name
        assert obj["thumbnail_url"].startswith("/storage/signed/")
        thumb = eng.get(obj["thumbnail_url"])
        assert thumb.status_code == 200
        im = Image.open(io.BytesIO(thumb.content))
        assert max(im.size) <= 320


def test_signed_url_works_without_cookie_and_expires(app_env, client_for):
    from fastapi.testclient import TestClient

    from kila.storage import signing

    app, _ = app_env
    eng = client_for("engineer")
    obj = _upload(eng, "uploads", "a.txt", b"hello").json()
    url = eng.post(f"/storage/object/{obj['object_id']}/signed-url", params={"expires": 60}).json()["url"]

    anon = TestClient(app)
    assert anon.get(f"/storage/object/{obj['object_id']}").status_code == 401
    assert anon.get(url).content == b"hello"
    assert anon.get(url.replace("sig=", "sig=00")).status_code == 403

    past = int(time.time()) - 1
    expired = f"/storage/signed/{obj['object_id']}?exp={past}&sig={signing._sig(obj['object_id'], past)}"
    assert anon.get(expired).status_code == 403


def test_bucket_role_checks(client_for):
    eng = client_for("engineer")
    rev = client_for("reviewer")
    admin = client_for("admin")
    assert _upload(rev, "kb", "sop.txt", b"x").status_code == 403
    assert _upload(eng, "kb", "sop.txt", b"x").status_code == 200
    assert _upload(eng, "models", "m.bin", b"x").status_code == 403
    assert eng.get("/storage/models/list").status_code == 403
    assert _upload(admin, "models", "m.bin", b"x").status_code == 200
    assert _upload(eng, "nope", "a.txt", b"x").status_code in (403, 404)


def test_unsafe_mime_is_served_as_attachment(client_for):
    eng = client_for("engineer")
    obj = _upload(eng, "uploads", "evil.html", b"<script>alert(1)</script>").json()
    r = eng.get(f"/storage/object/{obj['object_id']}")
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_mime_detection():
    from kila.storage.store import detect_mime

    assert detect_mime(b"PK\x03\x04" + b"\0" * 40, "sheet.xlsx").endswith("spreadsheetml.sheet")
    assert detect_mime(b"%PDF-1.7\n", "x.bin") == "application/pdf"
    assert detect_mime(b"import os\n", "main.py") == "text/plain"
    assert detect_mime(b"\xff\xfe\x00\x01garbage\x80", "blob") == "application/octet-stream"


def test_ledger_filter_by_object_and_head(client_for):
    eng = client_for("engineer")
    obj = _upload(eng, "uploads", "p.txt", b"provenance").json()
    eng.get(f"/storage/object/{obj['object_id']}")
    evs = eng.get("/ledger/events", params={"object_id": obj["object_id"]}).json()
    assert {e["event_type"] for e in evs} == {"storage.upload", "storage.read"}
    head = eng.get("/ledger/head").json()
    assert head["length"] == max(e["seq"] for e in eng.get("/ledger/events").json())
