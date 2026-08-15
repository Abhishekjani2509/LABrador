"""Sandbox capability probe. Prints raw facts, one per line."""
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

print("=== PROBE START ===")
print(f"PYTHON_VERSION: {sys.version.split()[0]}")
print(f"PYTHON_EXECUTABLE: {sys.executable}")
print(f"CWD: {os.getcwd()}")
print(f"SCRIPT_PATH: {os.path.abspath(__file__)}")

# --- memory mount ---
mem = "/mnt/memory"
print(f"MEMORY_MOUNT_EXISTS: {os.path.isdir(mem)}")
if os.path.isdir(mem):
    print(f"MEMORY_CONTENTS: {sorted(os.listdir(mem))}")
    for store in sorted(os.listdir(mem)):
        target = os.path.join(mem, store, "spike_probe.txt")
        try:
            with open(target, "w") as fh:
                fh.write("written by probe.py")
            with open(target) as fh:
                back = fh.read()
            print(f"MEMORY_WRITE[{store}]: OK roundtrip={back!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"MEMORY_WRITE[{store}]: FAIL {type(exc).__name__}: {exc}")

# --- outputs dir ---
print(f"OUTPUTS_DIR_EXISTS: {os.path.isdir('/mnt/session/outputs')}")

# --- network egress ---
# paperclip = the wheel host; pypi = where the wheel's DEPENDENCIES resolve from.
# These are separate gates: the wheel can be reachable while the install still
# fails for want of an index.
for name, url in [
    ("europepmc", "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=kras&format=json&pageSize=1"),
    ("paperclip", "https://paperclip.gxl.ai/paperclip.whl"),
    ("pypi", "https://pypi.org/simple/click/"),
]:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            body = resp.read(200).decode("utf8", "replace")
            length = resp.headers.get("Content-Length", "unknown")
        print(f"NET[{name}]: {resp.status} content_length={length} first200={body[:200]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"NET[{name}]: FAIL {type(exc).__name__}: {exc}")

# --- sibling files in this skill dir ---
here = os.path.dirname(os.path.abspath(__file__))
print(f"SKILL_DIR_CONTENTS: {sorted(os.listdir(here))}")

# --- tooling ---
for tool in ("sqlite3", "curl", "jq", "pip3", "pip", "uv"):
    which = subprocess.run(["which", tool], capture_output=True, text=True)
    print(f"TOOL[{tool}]: {which.stdout.strip() or 'ABSENT'}")

# --- paperclip ---
# Paperclip is a Python CLI over a REST API at paperclip.gxl.ai, NOT an MCP
# server. The question this section answers: can this sandbox install and run it
# on its own, so the deployed agent needs no host-side relay?
#
# Two install paths, because either can be blocked independently:
#   A. pip install gxl-paperclip          (PyPI index)
#   B. the wheel at paperclip.gxl.ai      (direct, no index)
# Path B needs the file renamed on the way down: the server serves it as
# "paperclip.whl", which pip rejects as not a valid wheel filename (PEP 427)
# before it ever looks inside. Confirmed locally, pip 21.2.4 and 26.x alike.
print(f"PAPERCLIP_PYTHON: {sys.version_info.major}.{sys.version_info.minor}")
print(f"PAPERCLIP_API_KEY_PRESENT: {bool(os.environ.get('PAPERCLIP_API_KEY'))}")

already = shutil.which("paperclip")
print(f"PAPERCLIP_PREINSTALLED: {already or 'ABSENT'}")

pip_exe = shutil.which("pip3") or shutil.which("pip")
target = tempfile.mkdtemp(prefix="pc-")
installed = False


def run_pip(label, spec):
    """pip install --target <target> <spec>. Returns True on success."""
    cmd = [pip_exe, "install", "--target", target, "--no-input", spec]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
    except Exception as exc:  # noqa: BLE001
        print(f"PAPERCLIP_INSTALL[{label}]: FAIL {type(exc).__name__}: {exc}")
        return False
    print(f"PAPERCLIP_INSTALL[{label}]_RC: {res.returncode}")
    for line in (res.stdout + res.stderr).strip().splitlines()[-10:]:
        print(f"PAPERCLIP_INSTALL[{label}]: {line}")
    return res.returncode == 0


def fetch_wheel():
    """Download the wheel under a PEP 427-legal name derived from its own
    dist-info, so the version is never hardcoded here."""
    raw = os.path.join(target, "download.zip")
    try:
        urllib.request.urlretrieve("https://paperclip.gxl.ai/paperclip.whl", raw)
        with zipfile.ZipFile(raw) as zf:
            di = next(n.split("/")[0] for n in zf.namelist() if ".dist-info/" in n)
        stem = di[: -len(".dist-info")]
        dest = os.path.join(target, f"{stem}-py3-none-any.whl")
        os.rename(raw, dest)
        print(f"PAPERCLIP_WHEEL_NAME: {os.path.basename(dest)}")
        return dest
    except Exception as exc:  # noqa: BLE001
        print(f"PAPERCLIP_WHEEL_FETCH: FAIL {type(exc).__name__}: {exc}")
        return None


if not pip_exe:
    print("PAPERCLIP_INSTALL: SKIPPED no pip on PATH")
else:
    installed = run_pip("pypi", "gxl-paperclip")
    if not installed:
        wheel = fetch_wheel()
        if wheel:
            installed = run_pip("wheel", wheel)

print(f"PAPERCLIP_INSTALLED: {installed}")

if installed:
    print(f"PAPERCLIP_TARGET_CONTENTS: {sorted(os.listdir(target))[:30]}")
    # Running the CLI proves two things at once: the entry point imports, and
    # every dependency resolved (click and rookiepy are the ones that bite).
    env = dict(os.environ, PYTHONPATH=target)
    runner = "from gxl_paperclip.cli import main; main()"
    for label, extra in [
        ("help", ["--help"]),
        ("search", ["search", "-s", "pmc", "KRAS G12C resistance"]),
    ]:
        try:
            res = subprocess.run([sys.executable, "-c", runner, *extra],
                                 capture_output=True, text=True,
                                 timeout=180, env=env)
            print(f"PAPERCLIP_RUN[{label}]_RC: {res.returncode}")
            for line in (res.stdout + res.stderr).strip().splitlines()[:15]:
                print(f"PAPERCLIP_RUN[{label}]: {line}")
        except Exception as exc:  # noqa: BLE001
            print(f"PAPERCLIP_RUN[{label}]: FAIL {type(exc).__name__}: {exc}")

shutil.rmtree(target, ignore_errors=True)

print("=== PROBE END ===")
