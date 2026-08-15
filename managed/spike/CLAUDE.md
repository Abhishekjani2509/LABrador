# Environment probe

You verify what this sandbox can do. You do not interpret or summarize — you run
the probe and report its raw output.

## Task

1. Locate the bundled probe script. It ships with the `env-probe` skill. Search
   for it: `find / -name probe.py -not -path '*/proc/*' 2>/dev/null | head`.
   Report every path you find, or say plainly that you found none.
2. If you found it, run it: `python3 <path>`. It takes several minutes — the
   Paperclip section downloads and installs a wheel. Wait for `=== PROBE END ===`.
3. If you found none, say so, then run the equivalent checks by hand with bash so
   we still learn what the sandbox supports.

If the task message gives you a Paperclip API key, export it as
`PAPERCLIP_API_KEY` in the same shell before running the probe. If it does not,
run the probe without one — an authentication failure is a result we want, not a
problem to route around.

## Output

Paste the probe's stdout **verbatim**, inside a fenced block. Then three lines:

```
SCRIPT_FOUND: yes|no
PAPERCLIP_INSTALLED: yes|no
PAPERCLIP_SEARCH: ok|auth-failed|other-failure|not-attempted
```

Take each of those from the probe's own output, not from your impression of it.
`PAPERCLIP_SEARCH: ok` requires actual paper titles in `PAPERCLIP_RUN[search]`;
an error mentioning credentials, login, 401 or 403 is `auth-failed`.

Do not explain, advise, or tidy the output. Raw text only.
