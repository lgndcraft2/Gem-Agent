"""Sandboxed agent tools and seed data. Every tool is pure Python."""
import base64
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SANDBOX = ROOT / "sandbox"
CHECK_FILE = ROOT / ".check.json"  # hidden answers, outside the sandbox
READ_LIMIT = 8000
OUTPUT_LIMIT = 4000
PYTHON_TIMEOUT = 20


class ToolError(Exception):
    """A tool failed in a way the model should be told about."""


def truncate(text, limit=OUTPUT_LIMIT):
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated]"


def safe_path(raw):
    """Resolve a sandbox-relative path, or raise ToolError if it could escape."""
    if not isinstance(raw, str) or not raw.strip() or "\0" in raw:
        raise ToolError("Invalid path.")
    text = raw.strip().replace("\\", "/")
    # A colon covers drive paths (C:/x) and NTFS streams (file.txt:hidden).
    if text.startswith("/") or ":" in text:
        raise ToolError("Rejected path %r: absolute paths are not allowed." % raw)
    if ".." in text.split("/"):
        raise ToolError("Rejected path %r: '..' is not allowed." % raw)
    root = SANDBOX.resolve()
    # resolve() follows symlinks and junctions, so a link out is caught here.
    resolved = (root / text).resolve()
    if resolved != root and root not in resolved.parents:
        raise ToolError("Rejected path %r: it leaves the sandbox." % raw)
    return resolved


def rel(path):
    return path.relative_to(SANDBOX.resolve()).as_posix() or "."


def list_files(path="."):
    target = safe_path(path)
    if not target.is_dir():
        raise ToolError("Not a folder: %s" % path)
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines = [p.name + "/" if p.is_dir() else p.name for p in entries]
    return "\n".join(lines) or "(empty folder)"


def read_file(path):
    target = safe_path(path)
    if not target.is_file():
        raise ToolError("File not found: %s" % path)
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(READ_LIMIT)


def write_file(path, content):
    target = safe_path(path)
    if target == SANDBOX.resolve() or target.is_dir():
        raise ToolError("Path is a folder: %s" % path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content), encoding="utf-8")
    return "Wrote %d characters to %s" % (len(str(content)), rel(target))


def make_dir(path):
    target = safe_path(path)
    target.mkdir(parents=True, exist_ok=True)
    return "Folder ready: %s" % rel(target)


def move_file(src, dst):
    source = safe_path(src)
    target = safe_path(dst)
    if source == SANDBOX.resolve() or not source.exists():
        raise ToolError("Source not found: %s" % src)
    if target.is_dir():
        target = target / source.name
    if target.exists():
        raise ToolError("Destination already exists: %s" % rel(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return "Moved %s to %s" % (rel(source), rel(target))


def run_python(file):
    target = safe_path(file)
    if target.suffix != ".py" or not target.is_file():
        raise ToolError("Not a .py file in the sandbox: %s" % file)
    # The model writes this code, so it must never see the API key.
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    try:
        done = subprocess.run(
            [sys.executable, str(target)],
            cwd=str(SANDBOX),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PYTHON_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise ToolError("Script stopped after %d seconds." % PYTHON_TIMEOUT)
    output = (done.stdout + done.stderr).strip() or "(no output)"
    return truncate("Exit code %d\n%s" % (done.returncode, output))


def delete_file(path):
    target = safe_path(path)
    if not target.is_file():
        raise ToolError("File not found: %s" % path)
    target.unlink()
    return "Deleted %s" % rel(target)


FIND_LIMIT = 20
FIND_SECONDS = 8
SKIP_DIRS = {"appdata", "node_modules", "__pycache__", "venv", "library"}
# Opening one of these would run it, and only run_python may run code.
NO_OPEN = {".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
           ".wsh", ".scr", ".lnk", ".url", ".hta", ".cpl", ".reg", ".py", ".pyw", ".sh", ".jar",
           ".app", ".command"}
APPS = {
    "win32": {"calculator": ["calc.exe"], "notepad": ["notepad.exe"], "paint": ["mspaint.exe"]},
    "darwin": {"calculator": ["open", "-a", "Calculator"], "notes": ["open", "-a", "Notes"],
               "textedit": ["open", "-a", "TextEdit"]},
    "linux": {},
}
SCREENSHOT_PS = (
    "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
    "$b=[Windows.Forms.Screen]::PrimaryScreen.Bounds;"
    "$i=New-Object Drawing.Bitmap $b.Width,$b.Height;"
    "$g=[Drawing.Graphics]::FromImage($i);"
    "$g.CopyFromScreen($b.Location,[Drawing.Point]::Empty,$b.Size);"
    "$w=[Math]::Min(1280,$b.Width);$h=[int]($b.Height*$w/$b.Width);"
    "$s=New-Object Drawing.Bitmap $i,$w,$h;"
    "$s.Save($env:SHOT_PATH,[Drawing.Imaging.ImageFormat]::Jpeg)"
)


def safe_env():
    return {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}


def find_file(name):
    """Search the user's folders by filename only. Never reads file contents."""
    needle = str(name).strip().lower()
    if not needle:
        raise ToolError("Give part of a filename to search for.")
    found = []
    stop_at = time.monotonic() + FIND_SECONDS
    for folder, dirs, files in os.walk(Path.home()):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in SKIP_DIRS
                   and Path(folder) / d != SANDBOX]
        for item in dirs + files:
            if needle in item.lower() and not item.startswith("."):
                found.append(str(Path(folder) / item))
                if len(found) >= FIND_LIMIT:
                    return "\n".join(found) + "\n(first %d matches)" % FIND_LIMIT
        if time.monotonic() > stop_at:
            note = "(search stopped after %d seconds)" % FIND_SECONDS
            return "\n".join(found + [note])
    return "\n".join(found) or "No files found matching %r." % name


def user_path(raw):
    """Resolve a path to open. Sandbox paths, or visible items in the user's folders."""
    text = str(raw).strip()
    if not Path(text).is_absolute():
        target = safe_path(text)
    else:
        target = Path(text).resolve()
        home = Path.home().resolve()
        if home not in target.parents:
            raise ToolError("Only files in your user folders can be opened.")
        parts = [p.lower() for p in target.relative_to(home).parts]
        if any(p.startswith(".") or p in SKIP_DIRS for p in parts):
            raise ToolError("Hidden and system folders can't be opened.")
    if not target.exists():
        raise ToolError("Not found: %s" % raw)
    if target.suffix.lower() in NO_OPEN:
        raise ToolError("%s files can't be opened because that would run them." % target.suffix)
    return target


def open_path(target):
    text = str(target).strip()
    if re.match(r"https?://\S+\Z", text, re.I):
        webbrowser.open(text)
        return "Opened %s in the browser." % text
    path = user_path(text)
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(path)], env=safe_env())
    return "Opened %s" % path


def open_app(name):
    apps = APPS.get(sys.platform, {})
    command = apps.get(str(name).strip().lower())
    if command is None:
        raise ToolError("Unknown app. Available: %s" % (", ".join(apps) or "none on this system"))
    subprocess.Popen(command, env=safe_env())
    return "Opened %s." % name


def see_screen():
    """Capture the main screen and return it as a JPEG data URI. Nothing stays on disk."""
    handle, name = tempfile.mkstemp(suffix=".jpg")
    os.close(handle)
    env = dict(safe_env(), SHOT_PATH=name)
    if sys.platform == "win32":
        command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", SCREENSHOT_PS]
    elif sys.platform == "darwin":
        command = ["screencapture", "-x", "-t", "jpg", name]
    else:
        os.unlink(name)
        raise ToolError("Screen capture is not available on this system.")
    try:
        subprocess.run(command, env=env, capture_output=True, timeout=15, check=True)
        data = Path(name).read_bytes()
        if not data:
            raise ToolError("The screenshot came back empty.")
    except (subprocess.SubprocessError, OSError) as exc:
        raise ToolError("Could not capture the screen: %s" % exc)
    finally:
        os.unlink(name)
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


# The single source of truth: adding a tool means adding one entry here.
TOOLS = {
    "list_files": {
        "handler": list_files,
        "description": "List a folder in the sandbox. Use '.' for the top level.",
        "params": {"path": "Folder path relative to the sandbox."},
    },
    "read_file": {
        "handler": read_file,
        "description": "Read the first 8000 characters of a file.",
        "params": {"path": "File path relative to the sandbox."},
    },
    "write_file": {
        "handler": write_file,
        "description": "Create or replace a text file. Parent folders are created for you. "
                       "A file named in the task with no folder, such as report.md, goes at "
                       "the top level of the sandbox, not inside a folder you are working on.",
        "params": {
            "path": "File path relative to the sandbox. Use 'report.md', not 'downloads/report.md'.",
            "content": "The full text of the file.",
        },
    },
    "make_dir": {
        "handler": make_dir,
        "description": "Create a folder. Each step counts, so for several folders make all the "
                       "calls in one reply, or let your script create them.",
        "params": {"path": "Folder path relative to the sandbox."},
    },
    "move_file": {
        "handler": move_file,
        "description": "Move or rename a file. To move many files, make many move_file "
                       "calls in the same reply.",
        "params": {
            "src": "Current path relative to the sandbox.",
            "dst": "New path, or an existing folder to move into.",
        },
    },
    "run_python": {
        "handler": run_python,
        "description": "Run a .py file from the sandbox and return its output. The file must "
                       "already exist, so call write_file first. Scripts start in the top level "
                       "of the sandbox. For any calculation on data or bulk file work, write one "
                       "script that does the whole job rather than working it out yourself.",
        "params": {"file": "Path of the .py file relative to the sandbox."},
    },
    "delete_file": {
        "handler": delete_file,
        "description": "Delete a file in the sandbox. Call this directly: the app asks the user "
                       "for approval itself, so never ask for permission in your reply.",
        "params": {"path": "File path relative to the sandbox."},
        "needs_approval": True,
    },
    "find_file": {
        "handler": find_file,
        "description": "Search the user's own folders outside the sandbox by filename. Returns "
                       "full paths. Use this only when the user asks where a file on their "
                       "computer is. For sandbox files, use list_files.",
        "params": {"name": "Part of the filename, such as 'budget' or '.pdf'."},
    },
    "open_path": {
        "handler": open_path,
        "description": "Open a website, a file, or a folder for the user in its normal app. Call "
                       "this directly: the app asks the user for approval itself.",
        "params": {"target": "An http(s) URL, a full path from find_file, or a sandbox path."},
        "needs_approval": True,
    },
    "open_app": {
        "handler": open_app,
        "description": "Open an app on the user's computer. Call this directly: the app asks the "
                       "user for approval itself.",
        "params": {"name": "One of: calculator, notepad, paint."},
        "needs_approval": True,
    },
    "see_screen": {
        "handler": see_screen,
        "description": "Take a screenshot of the user's screen and look at it. Use this only when "
                       "the user asks about their screen, never for an uploaded image. Call this "
                       "directly: the app shows the user the image and asks for approval itself.",
        "params": {},
        "needs_approval": True,
        "preview": True,
    },
}


def tool_schemas():
    schemas = []
    for name, spec in TOOLS.items():
        properties = {k: {"type": "string", "description": v} for k, v in spec["params"].items()}
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(spec["params"]),
                },
            },
        })
    return schemas


def file_tree(path=None):
    """Return the sandbox as nested JSON-ready dicts."""
    path = path or SANDBOX
    children = []
    if path.is_dir():
        for item in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if item.name == "__pycache__":
                continue
            if item.is_dir() and not item.is_symlink():
                children.append({"name": item.name, "type": "dir", "children": file_tree(item)})
            else:
                size = item.lstat().st_size
                children.append({"name": item.name, "type": "file", "size": size})
    return children


# Name, price, typical units. Spaced so the top 5 by revenue is a clear answer,
# and so the best sellers by units are not the best by revenue.
PRODUCTS = [
    ("Laptop", 900, 6), ("Monitor", 300, 13), ("Phone", 600, 5), ("Tablet", 400, 6),
    ("Headphones", 120, 15), ("Keyboard", 50, 24), ("Mouse", 25, 35), ("USB Hub", 30, 20),
    ("Webcam", 60, 8), ("Cable", 5, 70), ("Charger", 20, 15), ("Stand", 35, 6),
]

BUGGY = '''"""Add up a list of order values."""


def total(numbers):
    result = 0
    for i in range(len(numbers) - 1):
        result += numbers[i]
    return result


orders = [10, 20, 30, 40, 50]
print("Total:", total(orders))
'''


def seed_downloads(rng):
    folder = SANDBOX / "downloads"
    folder.mkdir(parents=True)
    letters = "abcdefghijklmnopqrstuvwxyz0123456789"
    kinds = ["txt"] * 5 + ["csv"] * 5 + ["md"] * 5 + ["py"] * 5 + ["invoice"] * 5
    rng.shuffle(kinds)
    for number, kind in enumerate(kinds):
        stem = "".join(rng.choice(letters) for _ in range(7))
        if kind == "invoice":
            name = "invoice_%s.txt" % stem
            body = "INVOICE #%d\nCustomer: Acme Ltd\nAmount due: $%d.00\n" % (
                1000 + number, rng.randint(40, 900))
        elif kind == "csv":
            name = stem + ".csv"
            body = "id,value\n" + "".join("%d,%d\n" % (i, rng.randint(1, 99)) for i in range(5))
        elif kind == "md":
            name = stem + ".md"
            body = "# Note %d\n\nRemember to follow up.\n" % number
        elif kind == "py":
            name = stem + ".py"
            body = "print('script %d')\n" % number
        else:
            name = stem + ".txt"
            body = "Plain text file number %d.\n" % number
        (folder / name).write_text(body, encoding="utf-8")


def seed_sales(rng):
    lines = ["date,product,units,price"]
    revenue = {name: 0 for name, _, _ in PRODUCTS}
    for row in range(200):
        name, price, units = PRODUCTS[row % len(PRODUCTS)]
        sold = max(1, round(units * rng.uniform(0.8, 1.2)))
        month, day = rng.randint(1, 12), rng.randint(1, 28)
        lines.append("2025-%02d-%02d,%s,%d,%d" % (month, day, name, sold, price))
        revenue[name] += sold * price
    (SANDBOX / "sales.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sorted(revenue, key=revenue.get, reverse=True), revenue


def seed_sandbox():
    """Empty the sandbox and rebuild it. Fixed seed, so the answers never change."""
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir()
    rng = random.Random(4)
    seed_downloads(rng)
    ranking, revenue = seed_sales(rng)
    (SANDBOX / "buggy.py").write_text(BUGGY, encoding="utf-8")
    CHECK_FILE.write_text(json.dumps({
        "top5": ranking[:5],
        "revenue": revenue,
        "buggy_output": "Total: 150",
    }, indent=2), encoding="utf-8")
