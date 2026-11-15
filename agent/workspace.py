"""The workspace: a small file system held in memory that a model step plans through.

A model step with a long job cannot keep the whole run in its head. Here it gets files instead: the run so
far under `run/` (read-only, written by code), and its own files anywhere else, by convention `plan.md`
(the steps it means to take, ticked off as it goes) and `notes/` (what it found out). It reads only what
it needs, writes down what it decided, and the next model step, the next attempt or the next run of the
same job starts from those files.

Nothing here touches the disk except `save` and `load`, which the runner calls to keep the model's own
files in `<run folder>/workspace/` between runs. The read-only files are rebuilt from the state each time.
In the state the workspace is a plain dict, `state["workspace"] = {"key", "files"}`.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
from pathlib import Path

READ_ONLY = "run/"  # everything under here is written by code, never by the model
MAX_FILE_CHARS = 60_000
MAX_FILES = 64  # the model's own files
READ_LINES = 400  # lines returned by one read unless a limit is given
KEY_FILE = ".key"


class WorkspaceError(ValueError):
    """A request the workspace turns down; the message goes back to the model as the tool's error."""


def norm(path) -> str:
    """A path as the workspace stores it: relative, forward slashes, no `..`, no hidden parts."""
    if not isinstance(path, str) or not path.strip():
        raise WorkspaceError("a path is needed")
    raw = path.strip().replace("\\", "/")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise WorkspaceError(f"{path}: paths are relative to the workspace, for instance notes/order.md")
    parts = raw.split("/")
    if ".." in parts:
        raise WorkspaceError(f"{path}: '..' is not allowed")
    p = posixpath.normpath(raw)
    if p == "." or any(part.startswith(".") for part in p.split("/")):
        raise WorkspaceError(f"{path}: not a file name the workspace accepts")
    return p


def key_for(state: dict) -> str:
    """What the notes belong to: this building and this job. Notes saved under another key are not loaded."""
    job = state.get("job") or f"tasks:{state.get('tasks_file')}"
    raw = json.dumps([(state.get("world") or {}).get("id"), job], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Workspace:
    def __init__(self, files: dict | None = None, key: str | None = None):
        self.files = dict(files or {})  # path -> text
        self.key = key
        self.log = []  # one {"tool", "path", "ok"} per tool call, for the trace

    # --- code's side -------------------------------------------------------------------------------

    def mount(self, path: str, content) -> None:
        """Put a read-only file under run/. `content` is text, or anything JSON can hold."""
        p = norm(path)
        if not p.startswith(READ_ONLY):
            p = READ_ONLY + p
        self.files[p] = content if isinstance(content, str) else json.dumps(content, indent=1, default=str)

    def put(self, path: str, content: str) -> None:
        """Code writing one of the model's own files (the harness's notes for the model)."""
        self.files[norm(path)] = content[:MAX_FILE_CHARS]

    def own(self) -> dict:
        """The model's own files: everything outside run/."""
        return {p: t for p, t in sorted(self.files.items()) if not p.startswith(READ_ONLY)}

    def dump(self) -> dict:
        return {"key": self.key, "files": self.own()}

    @classmethod
    def from_state(cls, state: dict) -> "Workspace":
        doc = state.get("workspace") or {}
        return cls(doc.get("files"), doc.get("key") or key_for(state))

    # --- the model's side --------------------------------------------------------------------------

    def ls(self, prefix: str = "") -> str:
        pre = prefix.strip().replace("\\", "/").lstrip("/") if isinstance(prefix, str) else ""
        if pre in (".", "./"):
            pre = ""
        rows = [(p, t) for p, t in sorted(self.files.items()) if p.startswith(pre)]
        if not rows:
            return f"no files under {pre!r}" if pre else "the workspace is empty"
        return "\n".join(f"{p}  {len(t.splitlines())} lines, {len(t)} characters" + ("  read-only" if p.startswith(READ_ONLY) else "")
                         for p, t in rows)

    def read(self, path: str, offset: int = 0, limit: int | None = None) -> str:
        p = norm(path)
        if p not in self.files:
            near = [q for q in self.files if q.startswith(p.rstrip("/") + "/")]
            raise WorkspaceError(f"{p}: no such file" + (f"; it is a folder holding {', '.join(near[:8])}" if near else "; call ls to see what exists"))
        lines = self.files[p].splitlines()
        offset = max(0, int(offset or 0))
        limit = READ_LINES if not limit or int(limit) <= 0 else int(limit)
        part = lines[offset:offset + limit]
        if not part:
            return f"{p} has {len(lines)} lines; nothing at line {offset + 1}"
        out = "\n".join(f"{offset + i + 1}\t{line}" for i, line in enumerate(part))
        rest = len(lines) - offset - len(part)
        return out + (f"\n[{rest} more lines; read again with offset {offset + len(part)}]" if rest > 0 else "")

    def _writable(self, path: str) -> str:
        p = norm(path)
        if p.startswith(READ_ONLY) or p == READ_ONLY.rstrip("/"):
            raise WorkspaceError(f"{p}: files under {READ_ONLY} are the run's record and are read-only; write under notes/ instead")
        return p

    def write(self, path: str, content: str) -> str:
        p = self._writable(path)
        if not isinstance(content, str):
            raise WorkspaceError("content must be text")
        if len(content) > MAX_FILE_CHARS:
            raise WorkspaceError(f"{p}: {len(content)} characters is over the {MAX_FILE_CHARS} a file may hold; split it")
        if p not in self.files and len(self.own()) >= MAX_FILES:
            raise WorkspaceError(f"the workspace already holds {MAX_FILES} of your files; reuse one")
        new = p not in self.files
        self.files[p] = content
        return f"{'wrote' if new else 'replaced'} {p} ({len(content.splitlines())} lines)"

    def edit(self, path: str, old: str, new: str) -> str:
        p = self._writable(path)
        if p not in self.files:
            raise WorkspaceError(f"{p}: no such file; write it first")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise WorkspaceError("old and new must be text, and old must not be empty")
        n = self.files[p].count(old)
        if n != 1:
            raise WorkspaceError(f"{p}: the text to replace occurs {n} times; it must occur exactly once, so quote more of it"
                                 if n else f"{p}: the text to replace is not in the file; read it again")
        text = self.files[p].replace(old, new)
        if len(text) > MAX_FILE_CHARS:
            raise WorkspaceError(f"{p}: the edit takes the file over {MAX_FILE_CHARS} characters")
        self.files[p] = text
        return f"edited {p}"

    # --- as tools ----------------------------------------------------------------------------------

    def call(self, name: str, args) -> tuple:
        """Run one tool call from the model. Returns (text, is_error); never raises."""
        args = args if isinstance(args, dict) else {}
        try:
            if name == "ls":
                out = self.ls(args.get("prefix") or "")
            elif name == "read_file":
                out = self.read(args.get("path"), args.get("offset") or 0, args.get("limit"))
            elif name == "write_file":
                out = self.write(args.get("path"), args.get("content"))
            elif name == "edit_file":
                out = self.edit(args.get("path"), args.get("old"), args.get("new"))
            else:
                raise WorkspaceError(f"{name}: no such tool")
            ok = True
        except (WorkspaceError, TypeError, ValueError) as e:
            out, ok = str(e), False
        self.log.append({"tool": name, "path": args.get("path") or args.get("prefix") or "", "ok": ok})
        return out, not ok


TOOLS = [
    {"name": "ls",
     "description": "List the files in the workspace with their sizes. Files under run/ are the run so far, written by code and "
                    "read-only. Everything else is yours and is kept for later steps and later runs of this job.",
     "input_schema": {"type": "object", "additionalProperties": False,
                      "properties": {"prefix": {"type": "string", "description": "Only list paths starting with this, e.g. 'run/' or 'notes/'."}}}},
    {"name": "read_file",
     "description": f"Read a file, with line numbers. Returns up to {READ_LINES} lines; for a longer file, read on with `offset`.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["path"],
                      "properties": {"path": {"type": "string"},
                                     "offset": {"type": "integer", "description": "Lines to skip from the top (default 0)."},
                                     "limit": {"type": "integer", "description": "Most lines to return."}}}},
    {"name": "write_file",
     "description": "Create a file or replace all of it. Use plan.md for your plan and notes/ for what you work out. "
                    "Not allowed under run/.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["path", "content"],
                      "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}},
    {"name": "edit_file",
     "description": "Replace one piece of text in one of your files, for instance to tick a line in plan.md. "
                    "`old` must occur exactly once in the file.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["path", "old", "new"],
                      "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}}},
]

GUIDE = """You have a workspace: a small file system, reached with the tools `ls`, `read_file`, `write_file` and `edit_file`.
- `run/` holds the run so far, written by code. It is read-only and is the only source of truth about the run: \
read what you need from it instead of working from memory, and read a number again before you rely on it.
- Everything else is yours. Files you wrote in an earlier step or an earlier run of this same job are still \
there, so begin with `ls` and read `plan.md` and anything under `notes/` before you start.
- Work in the open. First write `plan.md`: the things you will do, one line each, as `- [ ]` items. Tick each \
(`- [x]`) when it is done and add lines when you find more to do. Put what you work out under `notes/` \
(an ordering you settled, a number and where it came from, something that looked wrong), in a few lines a \
later step can act on.
- Your final answer is still the JSON you are asked for, not a file. Give it only when every line of the plan \
is ticked or struck out with a reason."""


# --- between runs ------------------------------------------------------------------------------------

def save(ws: Workspace, folder: Path) -> list:
    """Write the model's own files to `folder` (a real directory), dropping files that are gone. Returns
    the paths written. An empty workspace leaves no folder."""
    folder = Path(folder)
    own = ws.own()
    if folder.exists() and any(folder.iterdir()) and not (folder / KEY_FILE).exists():
        raise WorkspaceError(f"{folder} holds files but is not a saved workspace; not touching it")
    if folder.exists():
        for old in sorted(folder.rglob("*"), reverse=True):
            if old.is_file():
                old.unlink()
            elif not any(old.iterdir()):
                old.rmdir()
    if not own:
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
        return []
    folder.mkdir(parents=True, exist_ok=True)
    (folder / KEY_FILE).write_text(ws.key or "")
    for p, text in own.items():
        dest = folder / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return list(own)


def load(folder: Path, key: str) -> dict:
    """The saved files as a state dict, or an empty workspace when there is none or it belongs to another
    job or building. Files the workspace would not accept (hidden, too long) are skipped."""
    folder = Path(folder)
    files = {}
    if folder.is_dir() and (folder / KEY_FILE).exists() and (folder / KEY_FILE).read_text().strip() == key:
        for f in sorted(folder.rglob("*")):
            if not f.is_file():
                continue
            try:
                p = norm(f.relative_to(folder).as_posix())
                text = f.read_text()
            except (WorkspaceError, UnicodeDecodeError):
                continue
            if not p.startswith(READ_ONLY) and len(text) <= MAX_FILE_CHARS and len(files) < MAX_FILES:
                files[p] = text
    return {"key": key, "files": files}
