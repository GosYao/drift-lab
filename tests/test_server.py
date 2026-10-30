from http.client import HTTPConnection
import json
import threading
import unittest

from drift_lab.server import Handler, ThreadingHTTPServer


class QuietHandler(Handler):
    def log_message(self, *_):
        pass


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_health_is_explicit(self):
        status, _, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["cloud_connected"])

    def test_static_files_and_csp(self):
        for path in ("/", "/styles.css", "/app.js"):
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertGreater(len(body), 100)

    def test_unknown_scenario_fails(self):
        status, _, _ = self.request("GET", "/api/report?scenario=production")
        self.assertEqual(status, 400)

    def test_no_arbitrary_file_serving(self):
        for path in ("/../AGENTS.md", "/docs/STATUS.md", "/%2e%2e/AGENTS.md"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_replay(self):
        status, _, body = self.request("POST", "/api/replay", json.dumps({"scenario": "iam"}))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "fixture_violation")

    def test_baseline_preview(self):
        _, _, body = self.request("POST", "/api/replay",
                                  json.dumps({"scenario": "identity", "baseline": True}))
        self.assertEqual(json.loads(body)["status"], "fixture_blocked")

    def test_bad_json_fails(self):
        self.assertEqual(self.request("POST", "/api/replay", "{bad")[0], 400)

    def test_non_object_payload_fails(self):
        self.assertEqual(self.request("POST", "/api/replay", "[]")[0], 400)

    def test_oversized_payload_fails(self):
        self.assertEqual(self.request("POST", "/api/replay", "a" * 5000)[0], 413)

    def test_cross_origin_rejected(self):
        self.assertEqual(self.request("POST", "/api/replay", "{}",
                                       {"Origin": "https://untrusted.example"})[0], 403)

    def test_github_trigger_registry(self):
        status, _, body = self.request("GET", "/api/triggers")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in json.loads(body)],
                         ["pr", "push", "scheduled"])

    def test_github_preview_renders_each_trigger(self):
        for trigger, kind in (("pr", "pull_request"), ("push", "push"),
                              ("scheduled", "issue")):
            status, _, body = self.request("GET", f"/api/github?trigger={trigger}")
            self.assertEqual(status, 200)
            payload = json.loads(body)
            self.assertEqual(payload["kind"], kind)
            self.assertTrue(payload["preview"]["fixture"])
            self.assertFalse(payload["analysis"]["model_invoked"])

    def test_github_preview_defaults_to_pull_request(self):
        status, _, body = self.request("GET", "/api/github")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["kind"], "pull_request")

    def test_github_preview_unknown_trigger(self):
        self.assertEqual(self.request("GET", "/api/github?trigger=bogus")[0], 400)
