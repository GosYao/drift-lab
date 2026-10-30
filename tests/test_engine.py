from copy import deepcopy
import unittest

from drift_lab.engine import compare, replay, validate
from drift_lab.scenarios import baseline, scenario, SCENARIOS


class ComparisonTests(unittest.TestCase):
    def test_all_fixtures_validate(self):
        for item in SCENARIOS:
            expected, observed = scenario(item["id"])
            validate(expected)
            validate(observed)

    def test_iam_drift_is_potential_not_proven_exploit(self):
        report = compare(*scenario("iam"))
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(len(report["findings"]), 1)
        self.assertEqual(report["findings"][0]["status"], "potential")
        added = [e for e in report["graph"]["edges"] if e["state"] == "added"]
        self.assertEqual(added[0]["target"], "table:archive")
        self.assertFalse(report["analysis"]["model_invoked"])

    def test_identity_drift_adds_and_removes_relationships(self):
        report = compare(*scenario("identity"))
        edges = report["graph"]["edges"]
        self.assertTrue(any(e["target"] == "sa:reporting" and e["state"] == "added" for e in edges))
        self.assertTrue(any(e["target"] == "sa:support" and e["state"] == "removed" for e in edges))

    def test_scaling_is_expected(self):
        report = compare(*scenario("scaling"))
        self.assertEqual(report["findings"][0]["status"], "expected")
        self.assertEqual(report["status"], "no_security_drift_observed")

    def test_clean_does_not_claim_security(self):
        report = compare(*scenario("clean"))
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["status"], "no_security_drift_observed")
        self.assertTrue(report["coverage"]["limitations"])

    def test_incomplete_collection_never_clears(self):
        report = compare(*scenario("incomplete"))
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["findings"][0]["status"], "inconclusive")
        self.assertEqual(replay(*scenario("incomplete"))["status"], "inconclusive")

    def test_incomplete_scope_with_all_resources_still_inconclusive(self):
        expected, observed = scenario("clean")
        observed["collection"] = {"status": "incomplete", "errors": ["collector failed"]}
        report = compare(expected, observed)
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["findings"][0]["id"], "COLLECTION-INCOMPLETE")

    def test_missing_resource_is_not_deletion_when_collection_failed(self):
        report = compare(*scenario("incomplete"))
        self.assertNotIn("deleted", report["findings"][0]["title"].lower())
        missing = next(n for n in report["graph"]["nodes"] if n["id"] == "role:support")
        self.assertEqual(missing["state"], "unobserved")

    def test_fixture_replay_fails_before_and_blocks_after(self):
        expected, observed = scenario("iam")
        before = replay(expected, observed)
        after = replay(expected, expected)
        self.assertEqual(before["status"], "fixture_violation")
        self.assertTrue(before["simulation_only"])
        self.assertEqual(after["status"], "fixture_blocked")
        self.assertNotEqual(expected, observed)  # Reconciliation preview must not mutate.

    def test_identity_replay(self):
        self.assertEqual(replay(*scenario("identity"))["status"], "fixture_violation")

    def test_fingerprints_are_stable(self):
        self.assertEqual(compare(*scenario("iam")), compare(*scenario("iam")))

    def test_order_of_grants_is_not_drift(self):
        expected = baseline()
        observed = deepcopy(expected)
        next(r for r in observed["resources"] if r["id"] == "role:reporting")["attributes"]["read_tables"].reverse()
        self.assertFalse(compare(expected, observed)["findings"])

    def test_wrong_environment_rejected(self):
        expected, observed = scenario("clean")
        observed["environment"] = "production"
        with self.assertRaises(ValueError):
            compare(expected, observed)

    def test_unknown_fields_fail_closed(self):
        data = baseline()
        data["resources"][0]["attributes"]["secret"] = "do-not-export"
        with self.assertRaises(ValueError):
            validate(data)

    def test_duplicate_ids_rejected(self):
        data = baseline()
        data["resources"].append(deepcopy(data["resources"][0]))
        with self.assertRaises(ValueError):
            validate(data)

    def test_unsupported_resource_kind_rejected(self):
        data = baseline()
        data["resources"][0]["kind"] = "unknown"
        with self.assertRaises(ValueError):
            validate(data)

    def test_collection_errors_cannot_be_complete(self):
        data = baseline()
        data["collection"]["errors"] = ["failure"]
        with self.assertRaises(ValueError):
            validate(data)

    def test_unresolved_edge_is_inconclusive(self):
        expected, observed = scenario("clean")
        observed["resources"][1]["attributes"]["service_account"] = "sa:unknown"
        self.assertEqual(compare(expected, observed)["status"], "inconclusive")

    def test_live_evidence_cannot_be_replayed_as_fixture(self):
        expected, observed = scenario("clean")
        expected["mode"] = observed["mode"] = "sanitized-observation"
        with self.assertRaises(ValueError):
            replay(expected, observed)

    def test_mixed_evidence_modes_rejected(self):
        expected, observed = scenario("clean")
        observed["mode"] = "sanitized-observation"
        with self.assertRaises(ValueError):
            compare(expected, observed)

    def test_invalid_replica_type_rejected(self):
        data = baseline()
        data["resources"][1]["attributes"]["replicas"] = True
        with self.assertRaises(ValueError):
            validate(data)


if __name__ == "__main__":
    unittest.main()
