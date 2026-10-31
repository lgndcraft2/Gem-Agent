"""Gemma Agent web server. Standard library only."""
import base64
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agent
import tools

HOST = "127.0.0.1"
PORT = 8000
PAGE = tools.ROOT / "index.html"
LOG_FILE = tools.ROOT / "runs.jsonl"
MAX_IMAGE = 3 * 1024 * 1024
MAX_BODY = MAX_IMAGE * 4 // 3 + 64 * 1024
APPROVAL_TIMEOUT = 60
KEEPALIVE = 10
KEEP_RUNS = 20
IMAGE_ENABLED = os.environ.get("IMAGE_ENABLED", "1") == "1"
IMAGE_RE = re.compile(r"data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+\Z")

runs = {}
runs_lock = threading.Lock()
log_lock = threading.Lock()
active_run = None
conversation = []  # earlier tasks and answers, for follow-up questions


class Run:
    """One task's events. Each stream gets a queue that starts with the full history."""

    def __init__(self):
        self.id = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.history = []
        self.listeners = []
        self.approval = threading.Event()
        self.approved = False
        self.awaiting = False

    def emit(self, kind, data=None):
        with self.lock:
            event = (kind, data or {})
            self.history.append(event)
            for listener in self.listeners:
                listener.put(event)

    def subscribe(self):
        listener = queue.Queue()
        with self.lock:
            for event in self.history:
                listener.put(event)
            self.listeners.append(listener)
        return listener

    def unsubscribe(self, listener):
        with self.lock:
            self.listeners.remove(listener)

    def wait_approval(self):
        self.approved = False
        self.approval.clear()
        self.awaiting = True
        answered = self.approval.wait(APPROVAL_TIMEOUT)
        self.awaiting = False
        return answered and self.approved

    def answer(self, approve):
        if not self.awaiting:
            return False
        self.approved = approve
        self.approval.set()
        return True


def worker(run, task, image):
    global active_run
    try:
        summary = agent.run_agent(task, run.emit, run.wait_approval, image, conversation)
        with log_lock, LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary) + "\n")
        run.emit("done", {"success": summary["success"], "seconds": summary["seconds"]})
    except Exception as exc:
        run.emit("error", {"message": "Unexpected server error: %s" % exc})
        run.emit("done", {"success": False, "seconds": 0})
    finally:
        with runs_lock:
            active_run = None


def start_run(task, image):
    """Returns the new Run, or None if one is already going."""
    global active_run
    with runs_lock:
        if active_run:
            return None
        run = Run()
        active_run = run
        runs[run.id] = run
        for old in list(runs)[:-KEEP_RUNS]:
            del runs[old]
    threading.Thread(target=worker, args=(run, task, image), daemon=True).start()
    return run


def read_stats():
    records = []
    if LOG_FILE.exists():
        for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    total = len(records)
    wins = sum(1 for r in records if r.get("success"))
    seconds = sum(r.get("seconds", 0) for r in records)
    return {
        "total_runs": total,
        "success_rate": round(100 * wins / total, 1) if total else 0,
        "average_seconds": round(seconds / total, 1) if total else 0,
    }


def page_html():
    config = {
        "model": agent.primary_model(),
        "keySet": bool(os.environ.get("OPENROUTER_API_KEY")),
        "imageEnabled": IMAGE_ENABLED,
    }
    return PAGE.read_text(encoding="utf-8").replace("/*CONFIG*/null", json.dumps(config))


class Handler(BaseHTTPRequestHandler):
    server_version = "GemmaAgent"

    def log_message(self, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        # Blocks DNS rebinding: other sites must not be able to drive this server.
        return self.headers.get("Host", "").split(":")[0] in (HOST, "localhost")

    def do_GET(self):
        if not self.host_ok():
            return self.send_json({"error": "Bad host."}, 403)
        path = self.path.split("?")[0]
        stream = re.fullmatch(r"/api/stream/([0-9a-f]{32})", path)
        if path == "/":
            body = page_html().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/files":
            self.send_json(tools.file_tree())
        elif path == "/api/stats":
            self.send_json(read_stats())
        elif stream:
            self.stream_events(stream.group(1))
        else:
            self.send_json({"error": "Not found."}, 404)

    def stream_events(self, run_id):
        run = runs.get(run_id)
        if run is None:
            return self.send_json({"error": "Unknown run."}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        listener = run.subscribe()
        try:
            while True:
                try:
                    kind, data = listener.get(timeout=KEEPALIVE)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                message = "event: %s\ndata: %s\n\n" % (kind, json.dumps(data))
                self.wfile.write(message.encode())
                self.wfile.flush()
                if kind == "done":
                    break
        except (BrokenPipeError, ConnectionError):
            pass
        finally:
            run.unsubscribe(listener)

    def read_body(self):
        """Parse a JSON body, or send the error and return None."""
        # Requiring this type forces a CORS preflight, which this server never grants.
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self.send_json({"error": "Send application/json."}, 415)
            return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.send_json({"error": "Request too large. Images must be under 3MB."}, 413)
            return None
        try:
            data = json.loads(self.rfile.read(length).decode() or "{}")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            self.send_json({"error": "Invalid JSON."}, 400)
            return None
        return data

    def do_POST(self):
        if not self.host_ok():
            return self.send_json({"error": "Bad host."}, 403)
        data = self.read_body()
        if data is None:
            return
        path = self.path.split("?")[0]
        approve = re.fullmatch(r"/api/approve/([0-9a-f]{32})", path)
        if path == "/api/run":
            self.handle_run(data)
        elif approve:
            run = runs.get(approve.group(1))
            if run is None or not run.answer(data.get("approve") is True):
                return self.send_json({"error": "Nothing is waiting for approval."}, 409)
            self.send_json({"ok": True})
        elif path == "/api/reset":
            with runs_lock:
                if active_run:
                    return self.send_json({"error": "A task is still running."}, 409)
                tools.seed_sandbox()
                conversation.clear()
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "Not found."}, 404)

    def handle_run(self, data):
        task = data.get("task")
        image = data.get("image") or None
        if not isinstance(task, str) or not task.strip():
            return self.send_json({"error": "Type a task first."}, 400)
        if not os.environ.get("OPENROUTER_API_KEY"):
            return self.send_json({"error": "OPENROUTER_API_KEY is not set."}, 400)
        if image:
            if not IMAGE_ENABLED:
                return self.send_json({"error": "Image input is turned off."}, 400)
            if not isinstance(image, str) or not IMAGE_RE.match(image):
                return self.send_json({"error": "That image format is not supported."}, 400)
            try:
                size = len(base64.b64decode(image.split(",", 1)[1], validate=True))
            except ValueError:
                return self.send_json({"error": "That image could not be read."}, 400)
            if size > MAX_IMAGE:
                return self.send_json({"error": "Images must be under 3MB."}, 413)
        with runs_lock:
            if data.get("fresh") is True and not active_run:
                conversation.clear()
        run = start_run(task.strip(), image)
        if run is None:
            return self.send_json({"error": "A task is already running."}, 409)
        self.send_json({"run_id": run.id})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, SO_REUSEADDR would let us bind a port that is already in use.
    allow_reuse_address = os.name != "nt"


def serve(port=PORT):
    tools.seed_sandbox()
    try:
        server = Server((HOST, port), Handler)
    except OSError:
        print("Port %d is in use. Stop the other program and try again." % port)
        return 1
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("Warning: OPENROUTER_API_KEY is not set. The page will show setup steps.")
    else:
        threading.Thread(target=agent.check_models, daemon=True).start()
    print("Gemma Agent is running at http://%s:%d" % (HOST, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(serve())
