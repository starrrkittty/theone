import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from app.workflow import run_workflow
from app.history import recent, delete
from app.group_adapters import from_group_a, group_e_contract
from app.engine import validate_movement
from app.movement_evidence import measurement_review

from app.agents import service
from app.model_client import ConfigurationError, ModelError
from app.engine import InputError, experts_catalog


ROOT = Path(__file__).parent


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "BGroupDemo/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            try:
                self._json(200, service.client.status())
            except ConfigurationError as exc:
                self._json(503, {"error": str(exc)})
            return
        if path == "/" or path == "/index.html":
            self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/experts":
            self._json(200, experts_catalog())
            return
        if path == "/api/integration/contract":
            self._json(200, group_e_contract())
            return
        if path == "/api/history":
            try:
                user = parse_qs(urlparse(self.path).query).get("user_id", [""])[0]
                self._json(200, {"reports": recent(user)})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self):
        routes = {
            "/api/movement/analyze": "movement",
            "/api/plans/phase": "plan",
            "/api/nutrition/advice": "nutrition",
            "/api/workouts/summary": "report",
        }
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Request body is empty or too large")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            path = urlparse(self.path).path
            if path == "/api/movement/evidence":
                data = from_group_a(data)
                validate_movement(data)
                result = {"measurement_review":measurement_review(data), "agent":{"mode":"measurement_tool", "model_called":False}}
            elif path == "/api/workflow":
                result = run_workflow(data)
            elif path == "/api/history/delete":
                delete(data["user_id"])
                result = {"deleted": True}
            elif path in routes:
                result = service.run(routes[path], from_group_a(data) if routes[path] == "movement" else data)
            else:
                self._json(404, {"error": "Not found"})
                return
            self._json(200, result)
        except ConfigurationError as exc:
            self._json(503, {"error": str(exc)})
        except ModelError as exc:
            self._json(502, {"error": str(exc)})
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError, InputError) as exc:
            self._json(400, {"error": str(exc)})

    def _json(self, status, value):
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _send(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        print("%s - %s" % (self.log_date_time_string(), format % args))


if __name__ == "__main__":
    address = ("127.0.0.1", 8765)
    server = ThreadingHTTPServer(address, DemoHandler)
    print(f"B-group demo ready at http://{address[0]}:{address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
