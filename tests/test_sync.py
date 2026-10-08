import pytest

from core.sync import SyncAction as A
from core.sync import decide, md5_hex


@pytest.mark.parametrize("local,remote,base,empty,expected", [
    (None, None, None, True, A.NOTHING),       # brand new everywhere
    ("L", None, None, False, A.UPLOAD),        # first time signing in: push to Drive
    ("L", None, "B", False, A.UPLOAD),         # Drive copy deleted: push again
    (None, "R", None, True, A.DOWNLOAD),       # new computer, no local file
    ("X", "X", "B", False, A.NOTHING),         # identical
    ("L", "B", "B", False, A.UPLOAD),          # only this computer changed
    ("B", "R", "B", False, A.DOWNLOAD),        # only Drive changed
    ("L", "R", "B", False, A.CONFLICT),        # both changed
    ("L", "R", None, True, A.DOWNLOAD),        # new computer with an empty local db
    ("L", "R", None, False, A.CONFLICT),       # new computer that already has its own data
])
def test_decide(local, remote, base, empty, expected):
    assert decide(local, remote, base, empty) is expected


def test_md5():
    assert md5_hex(b"abc") == "900150983cd24fb0d6963f7d28e17f72"
