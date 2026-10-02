import http.server
import json
import os
import ssl
from urllib.parse import urlparse, parse_qs


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if self.headers.get("TOKEN") != os.environ["FIXTURE_CLOUDATLAS_TOKEN"]:
            self.send_error(403)
            return
        if url.path not in ("/openapi/v1/asset/ip", "/openapi/v1/attack/port"):
            self.send_error(404)
            return
        page = int(q["page"][0])
        size = int(q["size"][0])
        domain = "ip" if url.path.endswith("/ip") else "port"
        rows = [
            {
                "id": 1000 - n,
                "ip": f"192.0.2.{n}",
                "status": "valid",
                **(
                    {"version": 4, "live_port": 1}
                    if domain == "ip"
                    else {"port": 443, "protocol": "tcp", "service": "https"}
                ),
            }
            for n in range(1, 39)
        ]
        if domain == "port":
            rows += [
                {
                    "id": 2000 + n,
                    "ip": "192.0.2.1",
                    "port": 443,
                    "protocol": "tcp",
                    "service": "synthetic",
                }
                for n in range(30)
            ]
        rows.sort(key=lambda r: r["id"], reverse=True)
        body = json.dumps(
            {
                "code": 200,
                "data": {
                    "items": rows[(page - 1) * size : page * size],
                    "total": len(rows),
                    "current": page,
                    "size": size,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("0.0.0.0", 8443), Handler)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain("/tls/cert.pem", "/tls/key.pem")
server.socket = ctx.wrap_socket(server.socket, server_side=True)
server.serve_forever()
