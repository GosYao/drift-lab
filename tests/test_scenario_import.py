import json
import unittest

from drift_lab.scenario_import import load_scenario
from tests.test_server import QuietHandler, ThreadingHTTPServer
import threading


class ScenarioImportTests(unittest.TestCase):
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

    def request(self, path, payload):
        from http.client import HTTPConnection
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", path, json.dumps(payload))
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_load_scenario_accepts_a_mapping(self):
        self.assertEqual(load_scenario("scenario: iam\nnote: from yaml\n"),
                         {"scenario": "iam", "note": "from yaml"})

    def test_load_scenario_rejects_a_list(self):
        with self.assertRaises(ValueError):
            load_scenario("- just\n- a\n- list\n")

    def test_load_scenario_rejects_invalid_yaml(self):
        with self.assertRaises(ValueError):
            load_scenario("scenario: [unclosed\n")

    def test_import_endpoint_returns_the_definition(self):
        status, body = self.request("/api/scenarios/import",
                                    {"document": "scenario: identity\n"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["scenario"], {"scenario": "identity"})

    def test_import_endpoint_rejects_a_non_document(self):
        status, _ = self.request("/api/scenarios/import", {"document": 42})
        self.assertEqual(status, 400)

    def test_import_endpoint_rejects_invalid_yaml(self):
        status, _ = self.request("/api/scenarios/import", {"document": "x: [unclosed\n"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
