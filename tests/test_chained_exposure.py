import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import chained_exposure  # noqa: E402
from chained_exposure import Unknown, assess, image_sources, in_image, parse_stack  # noqa: E402

PER_ROLE = '''      Resource = each.key == "support-agent" ? [
        aws_dynamodb_table.synthetic["customer-orders"].arn
        ] : [
        aws_dynamodb_table.synthetic["customer-orders"].arn,
        aws_dynamodb_table.synthetic["customer-archive"].arn
      ]
'''
BROADENED = '''      Resource = [
        aws_dynamodb_table.synthetic["customer-orders"].arn,
        aws_dynamodb_table.synthetic["customer-archive"].arn
      ]
'''
STACK = '''resource "aws_dynamodb_table" "synthetic" { # nosemgrep: accepted elsewhere
  for_each = toset(["customer-orders", "customer-archive"])
}

resource "aws_iam_role" "agent" {
  for_each = toset(["support-agent", "reporting-agent"])
  name     = "${var.cluster_name}-${each.key}"
}

resource "aws_iam_role_policy" "agent" {
  for_each = aws_iam_role.agent
  role     = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["dynamodb:GetItem", "dynamodb:Query"]
%s    }]
  })
}

resource "aws_eks_pod_identity_association" "agent" {
  for_each        = aws_iam_role.agent
  service_account = kubernetes_service_account_v1.agent[each.key].metadata[0].name
  role_arn        = each.value.arn
}

resource "kubernetes_deployment_v1" "preview" {
  metadata {
    name = "support-agent"
  }
  spec {
    template {
      spec {
        service_account_name = kubernetes_service_account_v1.agent["support-agent"].metadata[0].name
        container {
          image = var.application_image
        }
      }
    }
  }
}
'''
APPROVED, SEEDED = STACK % PER_ROLE, STACK % BROADENED
SOURCES = ["Dockerfile", "drift_lab"]
READS = {"support-agent": ["customer-orders"],
         "reporting-agent": ["customer-archive", "customer-orders"]}
BOTH = {"support-agent": ["customer-archive", "customer-orders"],
        "reporting-agent": ["customer-archive", "customer-orders"]}


def branch(name, number, reads=READS, fork_reads=READS, code=()):
    return {"name": name, "head": "f8f50cf", "pull_request": number, "reads": reads,
            "fork_reads": fork_reads, "code": list(code)}


class StackTests(unittest.TestCase):
    def test_the_repository_stack_is_modelled(self):
        stack = parse_stack((ROOT / chained_exposure.STACK).read_text())
        self.assertIn("customer-orders", stack["reads"]["support-agent"])
        self.assertEqual(stack["reads"]["reporting-agent"],
                         ["customer-archive", "customer-orders"])
        self.assertEqual(stack["actions"], ["dynamodb:GetItem", "dynamodb:Query"])
        deployment, = stack["deployments"]
        self.assertEqual((deployment["name"], deployment["identity"]),
                         ("support-agent", "support-agent"))
        self.assertTrue(deployment["repository_image"])

    def test_per_role_choice_and_plain_list(self):
        self.assertEqual(parse_stack(APPROVED)["reads"], READS)
        self.assertEqual(parse_stack(SEEDED)["reads"], BOTH)
        stack = parse_stack(APPROVED)
        self.assertEqual(APPROVED.splitlines()[stack["policy_line"] - 1].split()[0], "Resource")
        self.assertIn("service_account_name",
                      APPROVED.splitlines()[stack["deployments"][0]["identity_line"] - 1])

    def test_a_policy_this_script_does_not_model_is_unknown_not_guessed(self):
        wildcard = BROADENED.replace('aws_dynamodb_table.synthetic["customer-archive"].arn',
                                     '"*"')
        second_statement = STACK.replace(
            "%s    }]", '%s    }, { Effect = "Allow", Action = "s3:*", Resource = "*" }]')
        cases = {
            "wildcard resource": STACK % wildcard,
            "second statement": second_statement % PER_ROLE,
            "indirect resource": STACK % "      Resource = local.tables\n",
            "deny statement": APPROVED.replace('"Allow"', '"Deny"'),
            "roles from a variable": APPROVED.replace(
                'toset(["support-agent", "reporting-agent"])', "var.agents"),
            "role bound elsewhere": APPROVED.replace("each.value.arn", "var.shared_role_arn"),
            "unknown service account": APPROVED.replace(
                'kubernetes_service_account_v1.agent["support-agent"].metadata[0].name',
                '"default"'),
            "no policy": APPROVED.replace('"aws_iam_role_policy" "agent"',
                                          '"aws_iam_policy" "agent"'),
        }
        for name, text in cases.items():
            with self.subTest(name):
                with self.assertRaises(Unknown):
                    parse_stack(text)

    def test_image_sources_come_from_the_dockerfile(self):
        dockerfile = ("FROM python:3.12-slim AS build\n"
                      "COPY requirements.txt /app/requirements.txt\n"
                      "COPY --chown=10001:10001 drift_lab/ /app/drift_lab\n"
                      "COPY --from=build /wheels /wheels\n")
        sources = image_sources(dockerfile)
        self.assertEqual(sources, ["Dockerfile", "requirements.txt", "drift_lab"])
        self.assertTrue(in_image("drift_lab/server.py", sources))
        self.assertTrue(in_image("requirements.txt", sources))
        self.assertTrue(in_image("Dockerfile", sources))
        self.assertFalse(in_image("drift_labs/server.py", sources))
        self.assertFalse(in_image("docs/DEMO.md", sources))
        self.assertTrue(in_image("docs/DEMO.md", image_sources("COPY . /app\n")))
        self.assertIn("drift_lab", image_sources((ROOT / "Dockerfile").read_text()))


class AssessTests(unittest.TestCase):
    def setUp(self):
        self.approved, self.seeded = parse_stack(APPROVED), parse_stack(SEEDED)

    def test_code_change_meets_a_branch_that_broadens_the_role(self):
        facts = assess(self.approved, self.approved,
                       ["drift_lab/server.py", "requirements.txt", "docs/DEMO.md"],
                       SOURCES + ["requirements.txt"],
                       [branch("verify/policy-gate-broadening", 1, reads=BOTH),
                        branch("docs/tidy", None)])
        text = "\n".join(facts)
        self.assertIn("touches code that runs in Deployment `support-agent`: "
                      "`drift_lab/server.py`, `requirements.txt`.", text)
        self.assertIn("runs as service account `support-agent`", text)
        self.assertIn("allows `dynamodb:GetItem`, `dynamodb:Query` on: `customer-orders`", text)
        self.assertIn("Branch `verify/policy-gate-broadening` (pull request #1, head "
                      "`f8f50cf`) changes that policy: it adds `customer-archive`. If both "
                      "merge, the code in this change runs with `dynamodb:GetItem`, "
                      "`dynamodb:Query` on: `customer-archive`, `customer-orders`.", text)
        self.assertNotIn("docs/tidy", text)
        self.assertNotIn("No other branch", text)

    def test_code_change_with_no_branch_touching_the_role(self):
        facts = assess(self.approved, self.approved, ["drift_lab/engine.py"], SOURCES,
                       [branch("docs/tidy", None)])
        self.assertEqual(facts[-1], "No other branch on the remote changes that role's policy.")

    def test_policy_change_meets_a_branch_that_changes_the_workload(self):
        facts = assess(self.seeded, self.approved, ["infra/workloads/main.tf"], SOURCES,
                       [branch("feature/scenarios-from-yaml", 2,
                               code=["drift_lab/scenario_import.py", "requirements.txt"]),
                        branch("docs/tidy", None)])
        text = "\n".join(facts)
        self.assertNotIn("touches code", text)
        self.assertIn("on: `customer-archive`, `customer-orders`", text)
        self.assertIn("This change alters that policy: it adds `customer-archive`.", text)
        self.assertIn("Branch `feature/scenarios-from-yaml` (pull request #2, head `f8f50cf`) "
                      "changes code that runs in Deployment `support-agent`: "
                      "`drift_lab/scenario_import.py`, `requirements.txt`. If both merge, "
                      "that code runs with the access this change adds.", text)
        self.assertNotIn("docs/tidy", text)

    def test_narrowing_and_no_matching_branch(self):
        facts = assess(self.approved, self.seeded, ["infra/workloads/main.tf"], SOURCES, [])
        self.assertIn("This change alters that policy: it removes `customer-archive`.", facts)
        self.assertFalse(any("No other branch" in fact for fact in facts))
        broadened = assess(self.seeded, self.approved, ["infra/workloads/main.tf"], SOURCES, [])
        self.assertEqual(broadened[-1],
                         "No other branch on the remote changes that workload's code.")

    def test_a_branch_that_cannot_be_modelled_is_sent_to_a_person(self):
        facts = assess(self.approved, self.approved, ["drift_lab/server.py"], SOURCES,
                       [branch("infra/rework", 7, reads=None, fork_reads=None)])
        self.assertIn("Branch `infra/rework` (pull request #7, head `f8f50cf`) changes "
                      "`infra/workloads/main.tf` in a way this script does not model. "
                      "A person must check it.", facts)

    def test_unrelated_changes_have_no_exposure(self):
        self.assertEqual(assess(self.approved, self.approved, ["docs/DEMO.md", "tests/x.py"],
                                SOURCES, [branch("verify/broaden", 1, reads=BOTH)]), [])

    def test_outside_a_repository_the_answer_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            result = chained_exposure.compute(directory)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("could not be computed", result["facts"][0])
        self.assertIn("a person must check", result["facts"][0])


if __name__ == "__main__":
    unittest.main()
