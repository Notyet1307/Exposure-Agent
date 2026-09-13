"""Test-only control-plane relay: bounded faults, no request bodies or credentials logged."""
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

mode = "none"
calls = []
lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def respond(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        self.respond(200, {"mode": mode, "calls": calls})
    def do_POST(self):
        global mode
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/fault":
            value = json.loads(raw)["mode"]
            assert value in {"none", "offline", "drop_start_response"}
            mode = value
            return self.respond(200, {})
        rpc = self.path.rsplit("/", 1)[-1]
        with lock:
            chosen = mode
            if chosen == "drop_start_response" and rpc == "StartAgentRun": mode = "none"
            calls.append({"rpc": rpc, "forwarded": chosen != "offline"})
        if chosen == "offline": return self.respond(503, {"code": "unavailable", "message": "isolated test fault"})
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "content-length", "accept-encoding"}}
        headers["Accept-Encoding"] = "identity"
        req = urllib.request.Request("http://daemon:7410" + self.path, data=raw, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=150) as response: code=response.status; body=response.read()
        except urllib.error.HTTPError as error: code=error.code; body=error.read()
        if chosen == "drop_start_response" and rpc == "StartAgentRun" and code == 200:
            self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

ThreadingHTTPServer(("0.0.0.0", 7411), Handler).serve_forever()
