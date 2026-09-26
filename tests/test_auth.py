import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import keyring
import auth
from playwright.sync_api import sync_playwright

real_state = auth.load_state()
assert real_state is not None, "real session should decrypt"

tmp = Path(tempfile.mkdtemp())
auth.STATE_FILE = tmp / "state.enc"
auth.KEYRING_SERVICE = "d2l-scraper-test"

def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        global failed
        failed = True

failed = False
try:
    check("missing file -> None", auth.load_state() is None)

    sample = {"cookies": [{"name": "x", "value": "y"}], "origins": []}
    auth.save_state(sample)
    check("round trip", auth.load_state() == sample)
    check("file is not plaintext", b'"cookies"' not in auth.STATE_FILE.read_bytes())

    keyring.delete_password(auth.KEYRING_SERVICE, auth.KEYRING_USER)
    check("wrong key -> None", auth.load_state() is None)

    auth.STATE_FILE.write_bytes(b"garbage")
    check("corrupted file -> None", auth.load_state() is None)

    with sync_playwright() as p:
        bogus = {"cookies": [{"name": "d2lSessionVal", "value": "bogus", "domain": "bright.uvic.ca",
                              "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"}],
                 "origins": []}
        auth.save_state(bogus)
        check("bogus session -> whoami None", auth._open_session(p) is None)

        auth.save_state(real_state)
        user = auth._open_session(p).user
        check("real session via new key -> whoami ok", user is not None and user["UniqueName"] == "dryd3n")
finally:
    try:
        keyring.delete_password(auth.KEYRING_SERVICE, auth.KEYRING_USER)
    except keyring.errors.PasswordDeleteError:
        pass

sys.exit(1 if failed else 0)

