#!/usr/bin/env python3
"""
Scrub an OPNsense config export before committing it.

Run inside Kali:
    python3 /media/sf_labrepo/tools/scrub_config.py lab01-firewall-rules

Grabs the newest config-*.xml in ~/Downloads (or pass a file as a second
argument), replaces passwords, hashes, private keys, PSKs, API keys and
secrets with REDACTED, and saves it as <repo>/<lab-folder>/config.xml.
"""
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# element names whose value gets replaced
SENSITIVE_TAG = re.compile(
    r"""^(
        .*password.* | passwd | .*bindpw |
        authorizedkeys | .*secret.* | key | apikey | api_key | .*token.* |
        prv | privkey | .*private_?key.* |
        psk | .*pre-?shared-?key.* | .*shared_?key.* |
        tls | tlskey | tls_key | otp_seed | rocommunity | .*hash
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

# <tag attrs>value</tag> where value is plain text or CDATA (no child elements)
LEAF = re.compile(
    r"<([A-Za-z_][\w.\-]*)(\s[^<>]*)?>((?:<!\[CDATA\[.*?\]\]>)|[^<]+)</\1>",
    re.DOTALL,
)

# safety net: catch these anywhere, whatever tag they're in
PATTERNS = {
    "bcrypt hash": re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"),
    "sha512 hash": re.compile(r"\$6\$[^\s<]+"),
    "PEM private key": re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
}


def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def pick_input(args):
    if len(args) > 2:
        p = Path(args[2]).expanduser()
        if not p.is_file():
            die(f"{p} doesn't exist")
        return p
    exports = sorted(
        (Path.home() / "Downloads").glob("config*.xml"),
        key=lambda f: f.stat().st_mtime,
    )
    if not exports:
        die("no config*.xml in ~/Downloads - download it from System > Configuration > Backups first")
    return exports[-1]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    lab = REPO / sys.argv[1].strip("/")
    if not lab.is_dir() or not lab.name.startswith(("lab", "semester")):
        labs = ", ".join(sorted(d.name for d in REPO.iterdir() if d.name.startswith("lab")))
        die(f"'{sys.argv[1]}' isn't a lab folder. Options: {labs}")

    src = pick_input(sys.argv)
    text = src.read_text(encoding="utf-8", errors="replace")

    if "BEGIN config.xml" in text or "<opnsense>" not in text:
        die(f"{src.name} is encrypted or not an OPNsense config - re-download with 'Encrypt' unchecked")

    hits = Counter()

    def redact(m):
        tag, attrs, value = m.group(1), m.group(2) or "", m.group(3)
        if SENSITIVE_TAG.match(tag) and value.strip():
            hits[f"<{tag}>"] += 1
            return f"<{tag}{attrs}>REDACTED</{tag}>"
        return m.group(0)

    text = LEAF.sub(redact, text)

    for name, pat in PATTERNS.items():
        text, n = pat.subn("REDACTED", text)
        if n:
            hits[name] += n

    # final check - nothing that looks like a secret should survive
    leftovers = [name for name, pat in PATTERNS.items() if pat.search(text)]
    if "PRIVATE KEY" in text:
        leftovers.append("'PRIVATE KEY' text")
    if leftovers:
        die(f"still found {', '.join(leftovers)} after scrubbing - do NOT commit, check the file manually")

    out = lab / "config.xml"
    out.write_text(text, encoding="utf-8")

    print(f"Source:   {src}")
    print(f"Saved:    {out.relative_to(REPO)}")
    if hits:
        print("Redacted: " + ", ".join(f"{k} x{v}" for k, v in sorted(hits.items())))
    else:
        print("Redacted: nothing found (double check that's right)")


if __name__ == "__main__":
    main()