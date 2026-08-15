---
name: env-probe
description: Runs the bundled probe.py to report sandbox capabilities — python version, memory mount writability, network egress, filesystem layout, and whether the Paperclip CLI can be installed and run here. Reports raw facts; does not interpret them or decide anything based on them.
---

# env-probe

The probe script `probe.py` sits in this skill's directory.

## Procedure

1. Find it: `find / -name probe.py -not -path '*/proc/*' 2>/dev/null | head`
2. Run it: `python3 <path>`
3. Paste stdout verbatim.

It takes a few minutes — the Paperclip section downloads a wheel and installs it.
Let it finish; do not interrupt it and report a partial run as a result.

## Failure modes

- **The script may not be on disk at all.** Skills are uploaded as bundles, but
  whether non-SKILL.md files land on the container filesystem is exactly what this
  probe exists to determine. Finding nothing is a valid, informative result — report
  it plainly rather than substituting your own script.
- **`python3` may be absent.** Try `python`, then report the failure verbatim.
  Do not work around it silently.
- **`/mnt/memory` may not exist** if no memory store is attached to this session.
  That is a different failure from "exists but is read-only" — the probe
  distinguishes them; preserve that distinction in what you report.
- **Reachability and installability are different gates, and the probe reports
  them separately.** `NET[paperclip]` can be 200 while `PAPERCLIP_INSTALLED` is
  False, because the wheel's dependencies resolve from `pypi.org` — a second host,
  separately blockable. `NET[pypi]` is what tells the two apart. Never collapse
  them into "Paperclip works" or "Paperclip doesn't".
- **The wheel is served under a name pip refuses.** `paperclip.whl` is not a legal
  PEP 427 filename, so `pip install https://paperclip.gxl.ai/paperclip.whl` fails
  with "not a valid wheel filename" *without ever downloading the file* — a
  network-shaped error message for a naming problem. The probe downloads first and
  renames from the archive's own `.dist-info`. If you see that error in the output,
  it means the probe's rename path itself broke; do not conclude the host is
  unreachable.
- **`pip install gxl-paperclip` from PyPI is expected to fail.** The simple index
  returns 200 for that name but carries no distributions. The probe tries it first
  anyway, because a silent future publish would be worth knowing about. `RC: 1`
  there is the normal result, not the headline.
- **A successful `search` does not prove the sandbox is authenticated.** The CLI
  falls back to OAuth credentials in `~/.paperclip/credentials.json` when no
  `PAPERCLIP_API_KEY` is set. On a developer laptop that file exists and search
  quietly succeeds; in a fresh sandbox it does not. Read `PAPERCLIP_API_KEY_PRESENT`
  before reading the search result, and report an auth failure as an auth failure —
  it is a different finding from the CLI being broken or the host being unreachable.
- **`rookiepy` is a compiled dependency.** It installs from a prebuilt wheel where
  one matches the platform, and tries to build from Rust source where none does.
  If the install fails, report which package failed rather than the last line of
  pip's output, which is usually a generic summary.
