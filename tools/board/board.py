#!/usr/bin/env python3
"""Message-board client: a thin wrapper around `gh` for the pinned "Message Board" issue.

Commands: post, read, unread, wait.

Config (env vars, or KEY=VALUE lines in a git-ignored `.board.local` at the repo root):
  BOARD_HANDLE  your GitHub username (so we can tell which comments tag you)
  BOARD_PREFIX  bracket prefix for posts, e.g. "P1's Claude Code" (brackets added for you)
  BOARD_ISSUE   issue number of the board (default 1)
  BOARD_REPO    owner/name (default: the repo `gh` infers from the git remote)
  BOARD_POLL    seconds between polls in `wait` (default 20)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_config():
    cfg = {}
    local = ROOT / ".board.local"
    if local.exists():
        for line in local.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("BOARD_HANDLE", "BOARD_PREFIX", "BOARD_ISSUE", "BOARD_REPO", "BOARD_POLL"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


CFG = load_config()
ISSUE = CFG.get("BOARD_ISSUE", "1")
HANDLE = CFG.get("BOARD_HANDLE", "").lstrip("@")
LANE = os.environ.get("AGENT_LANE", "")  # two agents in one checkout each keep their own cursor (tools/lanes/)


def gh(*args):
    cmd = ["gh", *args]
    if CFG.get("BOARD_REPO"):
        cmd += ["--repo", CFG["BOARD_REPO"]]
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=ROOT).stdout
    except FileNotFoundError:
        sys.exit("board: the GitHub CLI `gh` is not installed")
    except subprocess.CalledProcessError as e:
        sys.exit(f"board: gh failed: {e.stderr.strip()}")


def comments():
    out = gh("issue", "view", ISSUE, "--json", "comments")
    return json.loads(out)["comments"]


def cursor_file(lane=None):
    lane = LANE if lane is None else lane
    d = ROOT / ".git" / "board"
    d.mkdir(parents=True, exist_ok=True)
    return d / (f"cursor-{HANDLE or 'anon'}" + (f"-{lane}" if lane else ""))


def get_cursor():
    for f in (cursor_file(), cursor_file("")):  # a new lane starts from the owner's cursor
        if f.exists():
            return f.read_text().strip()
    return ""


def set_cursor(cs):
    if cs:
        cursor_file().write_text(cs[-1]["id"])


def tags_me(body):
    return bool(HANDLE) and re.search(rf"(?<![\w-])@{re.escape(HANDLE)}(?![\w-])", body, re.I) is not None


def fmt(c, mark=False):
    star = "*" if mark and tags_me(c["body"]) else " "
    when = c.get("createdAt", "")[:16].replace("T", " ")
    return f"{star} {c['author']['login']} {when}\n{c['body'].strip()}\n"


def unseen(cs):
    cur = get_cursor()
    ids = [c["id"] for c in cs]
    return cs[ids.index(cur) + 1:] if cur in ids else cs


def cmd_post(a):
    prefix = CFG.get("BOARD_PREFIX", "")
    if prefix and LANE:
        prefix = f"{prefix}, {LANE}"
    msg = " ".join(a.message).strip()
    if not msg:
        sys.exit("board: empty message")
    body = f"[{prefix}] {msg}" if prefix and not msg.startswith("[") else msg
    gh("issue", "comment", ISSUE, "--body", body)
    print("posted")


def cmd_read(a):
    cs = comments()[-a.n:]
    print("\n".join(fmt(c, mark=True) for c in cs) or "(no comments)")
    set_cursor(comments())


def cmd_unread(a):
    cs = comments()
    new = unseen(cs)
    mine = [c for c in new if tags_me(c["body"])]
    shown = mine if a.mine else new
    if shown:
        print(f"== board: {len(new)} new, {len(mine)} tag @{HANDLE or '?'} ==")
        print("\n".join(fmt(c, mark=True) for c in shown))
    elif not a.quiet:
        print("(nothing new)")
    if not a.peek:
        set_cursor(cs)


def cmd_wait(a):
    poll = int(CFG.get("BOARD_POLL", "20"))
    if not HANDLE:
        sys.exit("board: set BOARD_HANDLE so wait knows whose tag to wait for")
    deadline = time.time() + a.timeout if a.timeout else None
    while True:
        cs = comments()
        mine = [c for c in unseen(cs) if tags_me(c["body"])]
        if mine:
            print("\n".join(fmt(c, mark=True) for c in mine))
            set_cursor(cs)
            return
        if deadline and time.time() > deadline:
            sys.exit("board: timed out waiting for a tag")
        time.sleep(poll)


def main():
    p = argparse.ArgumentParser(prog="board", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("post"); s.add_argument("message", nargs="+"); s.set_defaults(f=cmd_post)
    s = sub.add_parser("read"); s.add_argument("-n", type=int, default=20); s.set_defaults(f=cmd_read)
    s = sub.add_parser("unread")
    s.add_argument("--mine", action="store_true", help="only comments that tag you")
    s.add_argument("--quiet", action="store_true", help="print nothing when empty")
    s.add_argument("--peek", action="store_true", help="do not advance the cursor")
    s.set_defaults(f=cmd_unread)
    s = sub.add_parser("wait"); s.add_argument("--timeout", type=int, default=0, help="seconds; 0 = forever"); s.set_defaults(f=cmd_wait)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
