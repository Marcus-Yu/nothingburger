#!/usr/bin/env python3
"""Lanes: keep two agents that share one checkout (and one branch) out of each other's files.

Each agent runs with AGENT_LANE=<lane>; lanes.json says which paths each lane owns.
With AGENT_LANE unset every command here is a no-op, so teammates are unaffected.

Commands:
  hook              Claude Code PreToolUse hook: denies edits into another lane and
                    git commands that act on the whole tree or the shared index
  session-start     Claude Code SessionStart hook: the lane briefing
  pre-commit        git pre-commit hook: rejects commits holding another lane's files
  status            show the lanes and whose uncommitted files are whose
  install-git-hook  install the pre-commit hook into .git/hooks (no git config change)
  check-lane NAME   exit 1 unless NAME is a lane (used by the `agent` launcher)
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LANES_FILE = Path(__file__).with_name("lanes.json")
HOOK_MARKER = "# lanes pre-commit (tools/lanes/lanes.py install-git-hook)"

# macOS file systems are case-insensitive: Projects/Robots and Projects/robots are one folder.
_fold = str.casefold if sys.platform == "darwin" else (lambda s: s)


def load_lanes(path: Path = LANES_FILE) -> dict:
    return json.loads(path.read_text())


# ---- paths -------------------------------------------------------------------------------

def rel_path(path: str, cwd: str, root: Path = ROOT) -> str | None:
    """Repo-relative path ("" for the root itself), or None when it lies outside the repo."""
    p = Path(path) if os.path.isabs(path) else Path(cwd) / path
    p, r = os.path.realpath(p), os.path.realpath(root)
    if _fold(p) == _fold(r):
        return ""
    if _fold(p).startswith(_fold(r) + os.sep):
        return p[len(r) + 1:]
    return None


def owner(rel: str, lanes: dict) -> str | None:
    """The lane that owns this repo-relative path, or None if no lane lists it.
    Lanes may nest (frontend/ and frontend/robot-design/): the most specific path wins."""
    f = _fold(rel.rstrip("/"))
    best, best_len = None, -1
    for name, lane in lanes["lanes"].items():
        for p in lane["paths"]:
            q = _fold(p.rstrip("/"))
            if (f == q or (p.endswith("/") and f.startswith(q + "/"))) and len(q) > best_len:
                best, best_len = name, len(q)
    return best


def touched_lane(rel: str, me: str, lanes: dict) -> str | None:
    """Another lane this path reaches: it sits inside that lane, or contains part of it (".")."""
    o = owner(rel, lanes)
    if o and o != me:
        return o
    f = _fold(rel.rstrip("/"))
    for name, lane in lanes["lanes"].items():
        if name != me and any(f == "" or _fold(p).startswith(f + "/") for p in lane["paths"]):
            return name
    return None


def pathspec_rel(arg: str, cwd: str, root: Path = ROOT) -> str | None:
    """Repo-relative path a git pathspec reaches; globs count as their folder, magic as the root."""
    if arg.startswith(":"):
        return ""
    cut = min((i for i, c in enumerate(arg) if c in "*?["), default=None)
    if cut is not None:
        head = arg[:cut]
        arg = head.rsplit("/", 1)[0] if "/" in head else ""
    return rel_path(arg or ".", cwd, root)


def lane_error(me: str, lanes: dict) -> str | None:
    if me in lanes["lanes"]:
        return None
    return f"AGENT_LANE={me!r} is not a lane in tools/lanes/lanes.json (lanes: {', '.join(lanes['lanes'])})."


# ---- edits -------------------------------------------------------------------------------

def check_edit(file_path: str, cwd: str, me: str, lanes: dict, root: Path = ROOT) -> str | None:
    """Why this edit is refused, or None to allow it."""
    err = lane_error(me, lanes)
    if err:
        return err + " Relaunch with a valid lane."
    rel = rel_path(file_path, cwd, root)
    other = rel is not None and owner(rel, lanes)
    if other and other != me:
        return (f"{rel} belongs to the `{other}` lane; you are `{me}`. Another agent is working there "
                f"right now. Don't change it: tell the user what you need changed instead.")
    return None


# ---- git commands ------------------------------------------------------------------------

CONTROL = {";", "&&", "||", "|", "&", "(", ")", ";;", "|&"}
GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
SHARED_STATE = ("they act on the whole working tree or the shared index, so they would change or "
                "lose the other agent's uncommitted work. Ask the user to run it.")
DENIED = {
    "stash": "git stash",
    "switch": "git switch",
    "checkout": "git checkout (use `git restore <your paths>` to undo your own changes)",
    "reset": "git reset (use `git restore --staged <your paths>` to unstage your own files)",
    "clean": "git clean",
    "pull": "git pull", "merge": "git merge", "rebase": "git rebase",
    "cherry-pick": "git cherry-pick", "revert": "git revert", "am": "git am",
}
# Options whose value is the next argument, so it is not mistaken for a path.
VALUE_OPTS = {
    "commit": {"-m", "--message", "-F", "--file", "-c", "-C", "--reuse-message", "--reedit-message",
               "-t", "--template", "--author", "--date", "--fixup", "--squash", "--cleanup", "--trailer"},
    "restore": {"-s", "--source"},
}
COMMIT_VALUE_SHORT = set("mFcCt")  # in a cluster like -am, the rest after one of these is its value


def git_invocations(command: str) -> list[list[str]] | None:
    """Argument lists that follow each `git` word, split at shell control operators; None if unparsable."""
    lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        return None
    calls, current = [], None
    for tok in tokens:
        if tok in CONTROL:
            current = None
        elif tok == "git" or tok.endswith("/git"):
            current = []
            calls.append(current)
        elif current is not None:
            current.append(tok)
    return calls


def split_git_args(args: list[str]) -> tuple[str, list[str]]:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in GIT_GLOBAL_WITH_VALUE else 1
    return (args[i], args[i + 1:]) if i < len(args) else ("", [])


def paths_and_flags(sub: str, rest: list[str]) -> tuple[list[str], list[str]]:
    paths, flags, takes_value = [], [], VALUE_OPTS.get(sub, set())
    it = iter(rest)
    for tok in it:
        if tok == "--":
            paths.extend(it)
        elif tok.startswith("--"):
            flags.append(tok)
            if tok in takes_value:
                next(it, None)
        elif tok.startswith("-") and len(tok) > 1:
            if sub == "commit":
                cluster = ""
                for c in tok[1:]:
                    cluster += c
                    if c in COMMIT_VALUE_SHORT:
                        break
                flags.extend("-" + c for c in cluster)
                if cluster[-1] in COMMIT_VALUE_SHORT and tok.endswith(cluster):
                    next(it, None)
            else:
                flags.append(tok)
                if tok in takes_value:
                    next(it, None)
        else:
            paths.append(tok)
    return paths, flags


def check_git(args: list[str], cwd: str, me: str, lanes: dict, root: Path) -> str | None:
    sub, rest = split_git_args(args)
    if sub == "stash" and rest[:1] in (["list"], ["show"]):
        return None
    if sub in DENIED:
        return f"{DENIED[sub]} is off while two agents share this checkout: {SHARED_STATE}"
    if sub not in ("add", "commit", "restore", "rm", "mv"):
        return None
    paths, flags = paths_and_flags(sub, rest)
    if sub == "add" and set(flags) & {"-A", "--all", "-u", "--update", "--no-ignore-removal"}:
        return "git add -A / -u stages the other agent's files too. Add only your own paths: git add <path> ..."
    if sub == "commit" and set(flags) & {"-n", "--no-verify"}:
        return "git commit --no-verify skips the pre-commit lane check. Commit without it."
    if sub == "commit" and set(flags) & {"-a", "--all", "--amend"}:
        return ("git commit -a / --amend can take in the other agent's changes or rewrite its commit. "
                "Commit only your paths: git add <paths> && git commit -m \"...\" -- <paths>")
    for p in paths:
        rel = pathspec_rel(p, cwd, root)
        other = rel is not None and touched_lane(rel, me, lanes)
        if other:
            return (f"`git {sub} {p}` reaches the `{other}` lane's files; you are `{me}`. "
                    f"Name only paths in your lane.")
    return None


FALLBACK = re.compile(
    r"\bgit\b[^\n;&|]*?\s(stash|switch|checkout|reset|clean|pull|merge|rebase|cherry-pick|revert)\b"
    r"|\bgit\s+add\s[^\n;&|]*(\s-A\b|--all|\s-u\b|--update|\s\.(\s|$))"
    r"|\bgit\s+commit\s[^\n;&|]*(\s-a\w*\b|--all|--amend)")


def check_bash(command: str, cwd: str, me: str, lanes: dict, root: Path = ROOT) -> str | None:
    """Why this shell command is refused, or None to allow it. Only git commands are checked."""
    calls = git_invocations(command)
    if calls is None:  # the shell quoting defeated shlex: fall back to a coarse scan
        if FALLBACK.search(command):
            return ("This command looks like a git command that touches shared state (stash, checkout, "
                    "reset, add -A, commit -a ...) and could not be parsed precisely. "
                    "Run git on its own line with only your lane's paths.")
        return None
    if calls and lane_error(me, lanes):
        return lane_error(me, lanes) + " Relaunch with a valid lane before running git."
    for args in calls:
        reason = check_git(args, cwd, me, lanes, root)
        if reason:
            return reason
    return None


# ---- commits -----------------------------------------------------------------------------

def commit_violations(staged: list[str], me: str, lanes: dict) -> list[str]:
    return [p for p in staged if owner(p, lanes) not in (None, me)]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def uncommitted() -> list[str]:
    """Paths with uncommitted changes (untracked folders collapsed), from git status -z."""
    entries = git("status", "--porcelain=v1", "-z").split("\0")
    paths, skip = [], False
    for e in entries:
        if skip or not e:
            skip = False
            continue
        paths.append(e[3:])
        skip = e[0] in "RC"  # renames and copies are followed by their old path
    return paths


# ---- text --------------------------------------------------------------------------------

def briefing(me: str, lanes: dict, changed: list[str]) -> str:
    err = lane_error(me, lanes)
    if err:
        return f"[lanes] {err} Edits and git commands are blocked until the agent is relaunched with a valid lane."
    mine = lanes["lanes"][me]
    others = {n: l for n, l in lanes["lanes"].items() if n != me}
    deps = owner("pyproject.toml", lanes)
    lines = [
        f"[lanes] You are the `{me}` agent: {mine['about']}.",
        "Another agent works in this same checkout and branch at the same time. Hooks enforce the rules below.",
        f"Yours: {', '.join(mine['paths'])}",
    ]
    for n, l in others.items():
        lines.append(f"The `{n}` agent's (read freely, never change): {', '.join(l['paths'])}")
    lines += [
        "Paths no lane lists are open to both; check `git status` first and leave alone any file the other agent has changed.",
        "Rules:",
        "- Change files with Edit/Write. Never write into another lane from the shell (sed -i, >, tee, rm, mv, cp).",
        '- Commit only your own files: git add <your paths> && git commit -m "..." -- <your paths>. '
        "No git add -A / add . / commit -a / --amend. With per-file commits, commit only your lane's files.",
        "- Never run git stash, checkout, switch, reset, clean, restore ., pull, merge, rebase or cherry-pick: "
        "they change the other agent's files too. Ask the user instead.",
        "- If git says index.lock exists, the other agent is mid-command: wait a few seconds and retry. Never delete the lock.",
    ]
    if mine.get("port"):
        lines.append(f"- Port {mine['port']} is yours for servers. If something already listens there, reuse it. "
                     "Never kill a process you did not start.")
    if deps and deps != me:
        lines.append(f"- Dependencies (pyproject.toml, uv.lock, uv add/sync) belong to the `{deps}` agent.")
    if lanes.get("interfaces"):
        lines.append(f"- Both lanes depend on {', '.join(lanes['interfaces'])}. If you change one's shape, "
                     "say so in your reply so the user can tell the other agent.")
    if changed:
        lines.append("Uncommitted right now: " + changed_by_lane(changed, lanes))
    return "\n".join(lines)


def changed_by_lane(changed: list[str], lanes: dict) -> str:
    by_lane: dict[str, list[str]] = {}
    for p in changed:
        by_lane.setdefault(owner(p, lanes) or "unowned", []).append(p)
    return "; ".join(f"{n}: {len(ps)} ({', '.join(ps[:6])}{', ...' if len(ps) > 6 else ''})"
                     for n, ps in sorted(by_lane.items()))


def status(lanes: dict, changed: list[str]) -> str:
    lines = [f"{n} (port {l.get('port', '-')}): {', '.join(l['paths'])}" for n, l in lanes["lanes"].items()]
    lines.append("Uncommitted: " + (changed_by_lane(changed, lanes) or "nothing"))
    return "\n".join(lines)


# ---- entry points ------------------------------------------------------------------------

def cmd_hook() -> int:
    me = os.environ.get("AGENT_LANE")
    if not me:
        return 0
    data = json.load(sys.stdin)
    tool, inp = data.get("tool_name", ""), data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    lanes = load_lanes()
    if tool == "Bash":
        reason = check_bash(inp.get("command", ""), cwd, me, lanes)
    else:
        path = inp.get("file_path") or inp.get("notebook_path")
        reason = check_edit(path, cwd, me, lanes) if path else None
    if reason:
        print(f"[lanes] {reason}", file=sys.stderr)
        return 2  # Claude Code: block the tool call and show the reason to the model
    return 0


def cmd_pre_commit() -> int:
    me = os.environ.get("AGENT_LANE")
    if not me:
        return 0
    lanes = load_lanes()
    err = lane_error(me, lanes)
    if err:
        print(f"lanes: {err}", file=sys.stderr)
        return 1
    staged = [p for p in git("diff", "--cached", "--name-only", "--no-renames", "-z").split("\0") if p]
    bad = commit_violations(staged, me, lanes)
    if not bad:
        return 0
    print(f"lanes: this commit holds files from another lane (you are `{me}`):", file=sys.stderr)
    for p in bad:
        print(f"  {p}  ({owner(p, lanes)})", file=sys.stderr)
    print('Commit only your paths: git commit -m "..." -- <your paths>', file=sys.stderr)
    return 1


def cmd_install_git_hook() -> int:
    hooks = Path(git("rev-parse", "--git-path", "hooks").strip())
    hooks = hooks if hooks.is_absolute() else ROOT / hooks
    target = hooks / "pre-commit"
    if target.exists() and HOOK_MARKER not in target.read_text():
        print(f"lanes: {target} already exists and is not ours; add `python3 tools/lanes/lanes.py pre-commit` to it by hand.",
              file=sys.stderr)
        return 1
    hooks.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "#!/bin/sh\n"
        f"{HOOK_MARKER}\n"
        '[ -z "$AGENT_LANE" ] && exit 0\n'
        'f="$(git rev-parse --show-toplevel)/tools/lanes/lanes.py"\n'
        '[ -f "$f" ] || exit 0\n'
        'exec python3 "$f" pre-commit\n')
    target.chmod(0o755)
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "hook":
        return cmd_hook()
    if cmd == "pre-commit":
        return cmd_pre_commit()
    if cmd == "session-start":
        me = os.environ.get("AGENT_LANE")
        if me:
            print(briefing(me, load_lanes(), uncommitted()))
        return 0
    if cmd == "status":
        print(status(load_lanes(), uncommitted()))
        return 0
    if cmd == "install-git-hook":
        return cmd_install_git_hook()
    if cmd == "check-lane":
        err = lane_error(argv[2] if len(argv) > 2 else "", load_lanes())
        if err:
            print(f"lanes: {err}", file=sys.stderr)
        return 1 if err else 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
