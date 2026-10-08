"""Drive sync tests with an in-memory fake Drive (no network)."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from core.sync import SyncAction as A
from services import db
from services.drive_sync import (
    DriveAuthError, DriveClient, DriveError, DriveSync, local_snapshot, replace_local,
)


class FakeDrive:
    def __init__(self):
        self.data = None
        self.uploads = 0

    def find(self):
        if self.data is None:
            return None
        return {"id": "file1", "md5Checksum": hashlib.md5(self.data).hexdigest()}

    def download(self, file_id):
        assert file_id == "file1"
        return self.data

    def upload(self, data, file_id=None):
        self.data = data
        self.uploads += 1
        return {"id": "file1", "md5Checksum": hashlib.md5(data).hexdigest()}


def _make_db(path, *codes):
    with db.open_db(path) as conn:
        db.init_db(conn)
        for code in codes:
            db.add_course(conn, code)


def _codes(path):
    with db.open_db(path) as conn:
        return [c["code"] for c in db.list_courses(conn)]


@pytest.fixture
def drive():
    return FakeDrive()


def _computer(tmp_path, name, drive, account="me@gmail.com"):
    folder = tmp_path / name
    return DriveSync(folder / "app.db", folder / "sync_state.json", drive, account)


def test_snapshot_hash_matches_file_bytes(tmp_path):
    path = tmp_path / "app.db"
    _make_db(path, "ME 214")
    assert local_snapshot(path) == path.read_bytes()


def test_init_db_does_not_change_an_existing_file(tmp_path):
    path = tmp_path / "app.db"
    _make_db(path, "ME 214")
    before = path.read_bytes()
    with db.open_db(path) as conn:
        db.init_db(conn)
    assert path.read_bytes() == before


def test_first_sign_in_uploads(tmp_path, drive):
    a = _computer(tmp_path, "laptop", drive)
    _make_db(a.db_path, "ME 214")
    assert a.has_local_changes()
    assert a.sync().action is A.UPLOAD
    assert drive.uploads == 1 and not a.has_local_changes()
    assert a.sync().action is A.NOTHING


def test_second_computer_downloads(tmp_path, drive):
    a = _computer(tmp_path, "laptop", drive)
    _make_db(a.db_path, "ME 214")
    a.sync()
    b = _computer(tmp_path, "desktop", drive)
    _make_db(b.db_path)  # app started there first: empty database
    assert b.sync().action is A.DOWNLOAD
    assert _codes(b.db_path) == ["ME 214"]


def test_changes_flow_both_ways(tmp_path, drive):
    a, b = _computer(tmp_path, "laptop", drive), _computer(tmp_path, "desktop", drive)
    _make_db(a.db_path, "ME 214")
    a.sync()
    b.sync()
    _make_db(b.db_path, "MATH 220")           # edit on desktop
    assert b.sync().action is A.UPLOAD
    assert a.sync().action is A.DOWNLOAD      # laptop picks it up
    assert _codes(a.db_path) == ["MATH 220", "ME 214"]


def test_conflict_waits_then_resolves_with_backup(tmp_path, drive):
    a, b = _computer(tmp_path, "laptop", drive), _computer(tmp_path, "desktop", drive)
    _make_db(a.db_path, "ME 214")
    a.sync()
    b.sync()
    _make_db(a.db_path, "A-ONLY")
    _make_db(b.db_path, "B-ONLY")
    assert b.sync().action is A.UPLOAD
    uploads = drive.uploads
    assert a.sync().action is A.CONFLICT
    assert drive.uploads == uploads           # nothing overwritten
    result = a.sync(resolve=A.DOWNLOAD)
    assert result.action is A.DOWNLOAD and result.backup.exists()
    assert "B-ONLY" in _codes(a.db_path) and "A-ONLY" not in _codes(a.db_path)
    assert "A-ONLY" in _codes(result.backup)  # old data kept in data/backups


def test_conflict_resolved_by_keeping_local(tmp_path, drive):
    a, b = _computer(tmp_path, "laptop", drive), _computer(tmp_path, "desktop", drive)
    _make_db(a.db_path, "ME 214")
    a.sync()
    b.sync()
    _make_db(a.db_path, "A-ONLY")
    _make_db(b.db_path, "B-ONLY")
    b.sync()
    assert a.sync(resolve=A.UPLOAD).action is A.UPLOAD
    assert b.sync().action is A.DOWNLOAD
    assert "A-ONLY" in _codes(b.db_path)


def test_new_computer_with_own_data_conflicts(tmp_path, drive):
    a, b = _computer(tmp_path, "laptop", drive), _computer(tmp_path, "desktop", drive)
    _make_db(a.db_path, "ME 214")
    a.sync()
    _make_db(b.db_path, "LOCAL")
    assert b.sync().action is A.CONFLICT


def test_different_account_ignores_old_state(tmp_path, drive):
    a = _computer(tmp_path, "laptop", drive)
    _make_db(a.db_path, "ME 214")
    a.sync()
    other = DriveSync(a.db_path, a.state_path, FakeDrive(), "someone@else.com")
    assert other.has_local_changes()


def test_replace_local_rejects_non_database(tmp_path):
    with pytest.raises(DriveError):
        replace_local(tmp_path / "app.db", b"<html>nope</html>", tmp_path / "backups")


# --- HTTP client ------------------------------------------------------------

class FakeResponse:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code, self._payload, self.content = status, payload or {}, content
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def _record(self, method, url, **kw):
        self.calls.append(SimpleNamespace(method=method, url=url, **kw))
        return self.response

    def get(self, url, **kw):
        return self._record("GET", url, **kw)

    def post(self, url, **kw):
        return self._record("POST", url, **kw)

    def patch(self, url, **kw):
        return self._record("PATCH", url, **kw)


def test_client_find_uses_app_data_folder():
    session = FakeSession(FakeResponse(payload={"files": [{"id": "x", "md5Checksum": "m"}]}))
    found = DriveClient("tok", session).find()
    assert found["id"] == "x"
    call = session.calls[0]
    assert call.params["spaces"] == "appDataFolder"
    assert call.headers["Authorization"] == "Bearer tok"


def test_client_create_then_update():
    session = FakeSession(FakeResponse(payload={"id": "x", "md5Checksum": "m"}))
    client = DriveClient("tok", session)
    client.upload(b"data")
    client.upload(b"data", "x")
    assert session.calls[0].method == "POST" and session.calls[0].params["uploadType"] == "multipart"
    assert session.calls[1].method == "PATCH" and session.calls[1].url.endswith("/x")


@pytest.mark.parametrize("status,error", [(401, DriveAuthError), (403, DriveAuthError), (500, DriveError)])
def test_client_errors(status, error):
    with pytest.raises(error):
        DriveClient("tok", FakeSession(FakeResponse(status=status))).find()


def test_client_requires_token():
    with pytest.raises(DriveAuthError):
        DriveClient("")
