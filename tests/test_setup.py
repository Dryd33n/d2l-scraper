"""Schools, the login browser, no-keychain fallback, logout, and plain-language errors. No network."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
os.environ["D2L_SCRAPER_HOME"] = tempfile.mkdtemp()  # never touch the real login or settings
import httpx
import keyring
from keyring.errors import NoKeyringError
from playwright.sync_api import Error as PlaywrightError
import auth, cli, config, courses, embed, exports

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

# typed or pasted addresses
for typed, want in [("bright.uvic.ca", "https://bright.uvic.ca"), (" https://bright.uvic.ca/d2l/home/123 ", "https://bright.uvic.ca"),
                    ("https://bright.uvic.ca/d2l/le/content/507204/viewContent/1/View?ou=507204#top", "https://bright.uvic.ca"), ('"https://bright.uvic.ca/d2l/home"', "https://bright.uvic.ca"), ("<https://bright.uvic.ca/d2l/home>", "https://bright.uvic.ca"),
                    ("http://School.Example.edu/x", "https://school.example.edu"), ("host.edu:8443", "https://host.edu:8443"),
                    ("", None), ("not a url", None), ("localhost", None), ("https://", None), ("host.edu:notaport", None)]:
    check(f"normalize {typed!r}", config.normalize(typed), want)

# recognising a Brightspace
real_get = httpx.get
def answering(status, body=None, text="", url="https://school.edu/d2l/api/versions/"):
    def get(_, **kw):
        request = httpx.Request("GET", url)
        return httpx.Response(status, json=body, request=request) if body is not None else httpx.Response(status, text=text, request=request)
    return get
versions = [{"ProductCode": "lp", "LatestVersion": "1.63"}]
httpx.get = answering(200, versions)
check("versions JSON is a Brightspace", config.find_brightspace("https://school.edu"), "https://school.edu")
httpx.get = answering(200, versions, url="https://real.school.edu/d2l/api/versions/")
check("a redirect gives the real address", config.find_brightspace("https://school.edu"), "https://real.school.edu")
httpx.get = answering(404, text="nope")
check("404 is not", config.find_brightspace("https://example.com"), None)
httpx.get = answering(200, text="<html>catch-all page</html>")
check("an HTML page is not", config.find_brightspace("https://example.com"), None)
httpx.get = answering(200, [])
check("other JSON is not", config.find_brightspace("https://example.com"), None)
def offline(_, **kw): raise httpx.ConnectError("offline")
httpx.get = offline
check("offline is not", config.find_brightspace("https://school.edu"), None)
httpx.get = real_get

# choosing a school
try:
    config.base_url()
    check("no school yet raises", False, True)
except RuntimeError:
    check("no school yet raises", True, True)
config.set_school("https://one.edu")
config._base_url = None
check("school is saved", config.base_url(), "https://one.edu")
check("embed follows the school", embed.absolute("/a.png", None), "https://one.edu/a.png")
config.STATE_FILE.write_bytes(b"session")
config.set_school("https://one.edu")
check("same school keeps the login", config.STATE_FILE.exists(), True)
config.set_school("https://two.edu")
check("different school drops the login", config.STATE_FILE.exists(), False)
check("base url follows", config.base_url(), "https://two.edu")
config.CONFIG_FILE.write_text("garbage")
check("corrupt settings ask again", config.saved_school(), None)

# other schools' courses have no readable term
def course(i, term): return courses.Course(i, "", f"Course {i}", True, term)
check("no terms: one plain group", [l for l, _ in courses.by_term([course(1, None), course(2, None)])], ["Courses"])
check("terms still grouped", [l for l, _ in courses.by_term([course(1, "202609"), course(2, None)])], ["Fall 2026", "Other"])
check("no courses", courses.by_term([]), [])

# which browser logs in
class Launcher:
    def __init__(self, works): self.works, self.calls = works, []
    def launch(self, channel=None, headless=True):
        self.calls.append(channel)
        if channel not in self.works: raise PlaywrightError("Executable doesn't exist")
        return f"browser:{channel}"
class P:
    def __init__(self, works): self.chromium = Launcher(works)
installs = []
auth.subprocess.run = lambda cmd, **kw: installs.append(cmd)
p = P({"chrome", "msedge"})
check("chrome first", auth._launch_browser(p), "browser:chrome")
check("edge when no chrome", auth._launch_browser(P({"msedge"})), "browser:msedge")
check("no download when one is installed", installs, [])
check("chromium already downloaded", auth._launch_browser(P({None})), "browser:None")
check("no download for that either", installs, [])
class Downloads(Launcher):
    def launch(self, channel=None, headless=True):
        if channel is None and installs: return "browser:downloaded"
        return super().launch(channel, headless)
pd = P(set()); pd.chromium = Downloads(set())
check("downloads only as a last resort", auth._launch_browser(pd), "browser:downloaded")
check("downloads chromium alone", installs[0][1:], ["-m", "playwright", "install", "--no-shell", "chromium"])

# no keychain: the session lives in memory, nothing on disk
state = {"cookies": []}
auth.STATE_FILE.unlink(missing_ok=True)
real_get_password = keyring.get_password
def no_keychain(*a): raise NoKeyringError("none")
keyring.get_password = no_keychain
auth.save_state(state)
check("no keychain: nothing on disk", auth.STATE_FILE.exists(), False)
check("no keychain: session lasts the run", auth.load_state(), state)
auth._unsaved_state = None
auth.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
auth.STATE_FILE.write_bytes(b"old")
check("no keychain: old file reads as logged out", auth.load_state(), None)
keyring.get_password = real_get_password

# logout
auth.KEYRING_SERVICE = "d2l-scraper-test"
auth.save_state(state)
check("logged in", auth.load_state(), state)
auth.logout()
check("logout removes the session", (auth.STATE_FILE.exists(), auth.load_state()), (False, None))
check("logout removes the key", keyring.get_password(auth.KEYRING_SERVICE, auth.KEYRING_USER), None)
auth.logout()
check("logout twice is fine", auth.load_state(), None)

# errors in plain words
def crash(args): raise ValueError("boom")
real_dispatch = cli._dispatch
cli._dispatch = crash
check("crash exits 1", cli.main([]), 1)
check("crash logged with traceback", "ValueError: boom" in config.ERROR_LOG.read_text(encoding="utf-8"), True)
def net(args): raise httpx.ConnectError("offline")
cli._dispatch = net
check("network error exits 1", cli.main([]), 1)
def stop(args): raise KeyboardInterrupt
cli._dispatch = stop
check("ctrl-c exits 130", cli.main([]), 130)
cli._dispatch = real_dispatch
parsed = cli._parser().parse_args(["school", "bright.uvic.ca"])
check("school takes an address", (parsed.command, parsed.address), ("school", "bright.uvic.ca"))
check("studypack folder optional", cli._parser().parse_args(["studypack"]).folder, None)
