"""Chained exposure: what a changed workload can reach, and which branches change that.

Computed from Terraform source and git, never inferred by a model:

  changed path -> image (Dockerfile COPY) -> Deployment -> service account
               -> Pod Identity role -> tables the role's policy can read

and, for every other branch on the remote, whether it changes that role's policy
or that workload's code. A construct this script does not model makes the answer
"unknown", never a guess. This reads source, not live AWS permissions.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STACK = "infra/workloads/main.tf"
DOCKERFILE = "Dockerfile"
RESOURCE = re.compile(r'^resource "(\w+)" "(\w+)" \{')
TABLE = re.compile(r'aws_dynamodb_table\.\w+\["([^"]+)"\]\.arn')
LIMIT = "Read from Terraform source and git branches, not from live AWS permissions."
NOTHING = "This change touches neither a deployed workload's code nor its identity's policy."


class Unknown(Exception):
    """The source has a shape this script does not model."""


def resources(text):
    """Top-level resource blocks of a terraform-fmt file: {(type, name): (line, body)}."""
    found, name, start, body = {}, None, 0, []
    for number, line in enumerate(text.splitlines(), 1):
        match = RESOURCE.match(line)
        if name is None and match:
            name, start, body = match.groups(), number, []
        elif name is not None and line.startswith("}"):
            found[name] = (start, body)
            name = None
        elif name is not None:
            body.append((number, line))
    return found


def joined(body):
    return "\n".join(line for _, line in body)


def line_of(body, pattern):
    return next((number for number, line in body if re.search(pattern, line)), None)


def tables_in(listing):
    names = TABLE.findall(listing)
    if re.sub(r"[\s,]", "", TABLE.sub("", listing)):
        raise Unknown("the role policy names a resource other than the synthetic tables")
    return names


def evaluate(expression, role):
    """The tables a policy's Resource expression yields for one role."""
    conditional = re.fullmatch(
        r'\s*each\.key\s*==\s*"([^"]+)"\s*\?\s*\[(.*?)\]\s*:\s*\[(.*?)\]\s*', expression, re.S)
    if conditional:
        key, when_true, when_false = conditional.groups()
        return tables_in(when_true if role == key else when_false)
    plain = re.fullmatch(r"\s*\[(.*)\]\s*", expression, re.S)
    if plain:
        return tables_in(plain.group(1))
    raise Unknown("the role policy's Resource is not a list or a per-role choice of lists")


def parse_stack(text):
    """The identity facts of the workloads stack. Raises Unknown rather than guess."""
    found = resources(text)

    def block(kind):
        if (kind, "agent") not in found:
            raise Unknown('there is no {} "agent" resource'.format(kind))
        return found[(kind, "agent")]

    _, body = block("aws_iam_role")
    keys = re.search(r"for_each\s*=\s*toset\(\[([^\]]*)\]\)", joined(body))
    roles = re.findall(r'"([^"]+)"', keys.group(1)) if keys else []
    if not roles:
        raise Unknown("the IAM roles are not a literal for_each set")

    _, body = block("aws_iam_role_policy")
    policy = joined(body)
    one_statement = all(len(re.findall(r"\b{}\s*=".format(word), policy)) == 1
                        for word in ("Effect", "Action", "Resource"))
    if (not one_statement or not re.search(r'Effect\s*=\s*"Allow"', policy)
            or not re.search(r"for_each\s*=\s*aws_iam_role\.agent\s*$", policy, re.M)):
        raise Unknown("the role policy is not a single Allow statement per role")
    action = re.search(r"Action\s*=\s*\[([^\]]*)\]", policy)
    expression = re.search(r"Resource\s*=(.*?)^\s*\}", policy, re.S | re.M)
    if not action or not expression:
        raise Unknown("the role policy's Action or Resource could not be read")
    reads = {role: sorted(evaluate(expression.group(1), role)) for role in roles}
    policy_line = line_of(body, r"\bResource\s*=")

    association_line, body = block("aws_eks_pod_identity_association")
    association = joined(body)
    for pattern in (r"for_each\s*=\s*aws_iam_role\.agent\s*$",
                    r"service_account\s*=\s*kubernetes_service_account_v1\.agent\[each\.key\]",
                    r"role_arn\s*=\s*each\.value\.arn\s*$"):
        if not re.search(pattern, association, re.M):
            raise Unknown("Pod Identity does not bind each service account to the role "
                          "of the same name")

    deployments = []
    for (kind, _), (start, body) in sorted(found.items()):
        if kind != "kubernetes_deployment_v1":
            continue
        text = joined(body)
        account = re.search(r'service_account_name\s*=\s*(?:kubernetes_service_account_v1'
                            r'\.agent\["([^"]+)"\]|"([^"]+)")', text)
        label = re.search(r'\bname\s*=\s*"([^"]+)"', text)
        identity = (account.group(1) or account.group(2)) if account else None
        if not label or identity not in reads:
            raise Unknown("a Deployment's service account could not be tied to a role")
        deployments.append({
            "name": label.group(1), "line": start, "identity": identity,
            "identity_line": line_of(body, r"service_account_name\s*="),
            "repository_image": bool(re.search(r"\bimage\s*=\s*var\.application_image\s*$",
                                               text, re.M)),
        })
    return {"reads": reads, "actions": re.findall(r'"([^"]+)"', action.group(1)),
            "policy_line": policy_line, "association_line": association_line,
            "deployments": deployments}


def image_sources(dockerfile):
    """Paths the image is built from: every COPY source, plus the Dockerfile itself."""
    sources = [DOCKERFILE]
    for line in dockerfile.splitlines():
        parts = line.split()
        if not parts or parts[0].upper() != "COPY":
            continue
        if any(part.startswith("--from=") for part in parts):
            continue  # copied from another build stage, not from the repository
        paths = [part for part in parts[1:] if not part.startswith("--")]
        sources += [path.rstrip("/") or "/" for path in paths[:-1]]
    return sources


def in_image(path, sources):
    return any(source == "." or path == source or path.startswith(source + "/")
               for source in sources)


def ticked(names):
    return ", ".join("`{}`".format(name) for name in names) or "nothing"


def listed(paths, limit=4):
    more = " and {} more".format(len(paths) - limit) if len(paths) > limit else ""
    return ticked(paths[:limit]) + more


def delta(gained, lost):
    parts = (["adds " + ticked(gained)] if gained else []) + \
            (["removes " + ticked(lost)] if lost else [])
    return " and ".join(parts)


def named(branch):
    pull = "pull request #{}, ".format(branch["pull_request"]) if branch["pull_request"] else ""
    return "Branch `{}` ({}head `{}`)".format(branch["name"], pull, branch["head"])


def assess(head, base, changed, sources, branches):
    """The facts for one change. head and base are parsed stacks; base may be None.

    Each branch is {"name", "head", "pull_request", "reads", "fork_reads", "code"};
    reads is None when that branch's stack could not be modelled.
    """
    facts = []
    code = sorted(path for path in changed if in_image(path, sources))
    for deployment in head["deployments"]:
        if not deployment["repository_image"]:
            continue
        identity = deployment["identity"]
        now = head["reads"][identity]
        before = base["reads"].get(identity, []) if base else now
        gained, lost = sorted(set(now) - set(before)), sorted(set(before) - set(now))
        if not code and not gained and not lost:
            continue
        workload = "Deployment `{}`".format(deployment["name"])
        if code:
            facts.append("This change touches code that runs in {}: {}."
                         .format(workload, listed(code)))
        facts.append("{} runs as service account `{}` (`{}:{}`), which Pod Identity binds "
                     "to IAM role `aws_iam_role.agent[\"{}\"]` (`{}:{}`)."
                     .format(workload, identity, STACK, deployment["identity_line"],
                             identity, STACK, head["association_line"]))
        facts.append("With this change, that role's policy allows {} on: {} (`{}:{}`)."
                     .format(ticked(head["actions"]), ticked(now), STACK, head["policy_line"]))
        if gained or lost:
            facts.append("This change alters that policy: it {}.".format(delta(gained, lost)))
        policy_branches = code_branches = 0
        for branch in branches:
            if code and branch["reads"] is None:
                facts.append("{} changes `{}` in a way this script does not model. A person "
                             "must check it.".format(named(branch), STACK))
                policy_branches += 1
            elif code:
                theirs = branch["reads"].get(identity, [])
                forked = branch["fork_reads"].get(identity, [])
                adds, drops = sorted(set(theirs) - set(forked)), sorted(set(forked) - set(theirs))
                if adds or drops:
                    both = sorted((set(now) | set(adds)) - set(drops))
                    facts.append("{} changes that policy: it {}. If both merge, the code in "
                                 "this change runs with {} on: {}."
                                 .format(named(branch), delta(adds, drops),
                                         ticked(head["actions"]), ticked(both)))
                    policy_branches += 1
            if gained and branch["code"]:
                facts.append("{} changes code that runs in {}: {}. If both merge, that code "
                             "runs with the access this change adds."
                             .format(named(branch), workload, listed(branch["code"])))
                code_branches += 1
        if code and not policy_branches:
            facts.append("No other branch on the remote changes that role's policy.")
        if gained and not code_branches:
            facts.append("No other branch on the remote changes that workload's code.")
    return facts


def git(root, *args, check=True):
    done = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    if done.returncode != 0:
        if check:
            raise Unknown("git {} failed".format(args[0]))
        return None
    return done.stdout


def stack_at(root, ref):
    text = git(root, "show", "{}:{}".format(ref, STACK), check=False)
    return parse_stack(text) if text is not None else None


def default_branch(root):
    named_head = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    candidates = ([named_head.strip()] if named_head else []) + ["origin/main", "origin/master"]
    return next((ref for ref in candidates
                 if git(root, "rev-parse", "--verify", "--quiet", ref, check=False)), None)


def pull_request_heads(root):
    """{commit: number} for the pull-request heads the remote advertises. Best effort."""
    try:
        done = subprocess.run(["git", "ls-remote", "origin", "refs/pull/*/head"],
                              cwd=str(root), capture_output=True, text=True, timeout=15,
                              env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.TimeoutExpired):
        return {}
    heads = {}
    for line in done.stdout.splitlines() if done.returncode == 0 else []:
        commit, _, ref = line.partition("\t")
        number = re.fullmatch(r"refs/pull/(\d+)/head", ref)
        if number:
            heads[commit] = int(number.group(1))
    return heads


def other_branches(root, default_ref):
    """Remote branches that are not merged and not already part of this checkout."""
    listing = git(root, "for-each-ref", "--format=%(refname:short) %(objectname)",
                  "refs/remotes/origin")
    pulls, branches = None, []
    for line in listing.splitlines():
        name, tip = line.split()
        if name in ("origin", "origin/HEAD", default_ref):
            continue
        if git(root, "merge-base", "--is-ancestor", tip, "HEAD", check=False) is not None:
            continue  # this checkout already contains it
        fork = (git(root, "merge-base", default_ref, tip, check=False) or "").strip()
        if not fork or fork == tip:
            continue
        try:
            theirs, forked = stack_at(root, tip), stack_at(root, fork)
            reads = theirs["reads"] if theirs else {}
            fork_reads = forked["reads"] if forked else {}
        except Unknown:
            same = (git(root, "show", "{}:{}".format(tip, STACK), check=False)
                    == git(root, "show", "{}:{}".format(fork, STACK), check=False))
            reads, fork_reads = ({}, {}) if same else (None, None)
        sources = image_sources(git(root, "show", "{}:{}".format(tip, DOCKERFILE),
                                    check=False) or "")
        changed = git(root, "diff", "--name-only", fork, tip).splitlines()
        if pulls is None:
            pulls = pull_request_heads(root)
        branches.append({"name": name.split("/", 1)[1], "head": tip[:7],
                         "pull_request": pulls.get(tip), "reads": reads,
                         "fork_reads": fork_reads,
                         "code": sorted(path for path in changed if in_image(path, sources))})
    return branches


def compute(root, base=None):
    """{"status": "computed" | "none" | "unknown", "facts": [sentences]} for this checkout."""
    try:
        default_ref = default_branch(root)
        if base is None:
            base = (git(root, "merge-base", "HEAD", default_ref).strip() if default_ref
                    else "HEAD")
        try:
            head = parse_stack((Path(root) / STACK).read_text())
            sources = image_sources((Path(root) / DOCKERFILE).read_text())
        except OSError:
            raise Unknown("{} or {} is missing".format(STACK, DOCKERFILE))
        changed = git(root, "diff", "--name-only", base).splitlines()
        changed += git(root, "ls-files", "--others", "--exclude-standard").splitlines()
        branches = other_branches(root, default_ref) if default_ref else []
        facts = assess(head, stack_at(root, base), changed, sources, branches)
    except Unknown as error:
        return {"status": "unknown", "facts": [
            "Chained exposure could not be computed: {}. Treat it as unknown; a person "
            "must check.".format(error)]}
    if not facts:
        return {"status": "none", "facts": [NOTHING]}
    return {"status": "computed", "facts": facts + [LIMIT]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="commit this change is compared with (default: "
                                       "where HEAD left the default branch)")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    result = compute(ROOT, args.base)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("\n".join("- " + fact for fact in result["facts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
