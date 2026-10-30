"use strict";

const state = { scenario: "iam", report: null, baseline: null, selected: null, view: "observed", request: 0 };
const $ = id => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";
const labels = { high: "HIGH", medium: "MEDIUM", info: "EXPECTED", unknown: "UNKNOWN" };
const names = { agent_tool: "AGENT TOOL", deployment: "DEPLOYMENT", service_account: "SERVICE ACCOUNT", iam_role: "IAM ROLE", dataset: "DYNAMODB TABLE" };
const positions = {
  "tool:lookup": [20, 166], "deployment:support": [232, 166],
  "sa:support": [444, 70], "sa:reporting": [444, 270],
  "role:support": [656, 70], "role:reporting": [656, 270],
  "table:orders": [868, 70], "table:archive": [868, 270]
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svgElement(tag, attrs, text) {
  const node = document.createElementNS(svgNS, tag);
  Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function showError(error) {
  $("error").textContent = `Preview error: ${error.message}. No cloud action was performed.`;
  $("error").classList.remove("hidden");
}

async function loadScenario(identifier) {
  const request = ++state.request;
  state.scenario = identifier;
  state.view = "observed";
  state.selected = null;
  $("error").classList.add("hidden");
  $("replay-result").classList.add("hidden");
  $("replay").disabled = true;
  $("reconcile").disabled = true;
  document.querySelectorAll(".scenario-button").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.scenario === identifier));
  });
  try {
    const report = await api(`/api/report?scenario=${encodeURIComponent(identifier)}`);
    if (request !== state.request) return;
    state.report = report;
    state.selected = report.findings[0]?.id || null;
    render();
  } catch (error) { if (request === state.request) showError(error); }
}

function render() {
  const report = state.report;
  const security = report.findings.filter(f => f.status === "potential").length;
  $("security-count").textContent = security;
  $("security-note").textContent = report.status === "inconclusive" ? "Incomplete evidence · cannot clear findings" :
    security ? "Potential impact · validation required" : "No security drift in collected scope";
  $("resource-count").textContent = report.coverage.tracked_resources;
  $("coverage-count").textContent = report.status === "inconclusive" ? "Incomplete" : `${report.coverage.observed_resources} / ${report.coverage.tracked_resources}`;
  $("coverage-count").classList.toggle("text-metric", report.status === "inconclusive");
  $("coverage-note").textContent = report.status === "inconclusive" ? "Collector gap · no safe verdict" : "Tracked synthetic resources observed";
  $("finding-count").textContent = report.findings.length;
  $("revision").textContent = report.deployment.revision;
  $("state-version").textContent = report.deployment.state_version;
  renderFindings();
  renderBrief();
  renderGraph();
  $("replay").disabled = false;
  $("reconcile").disabled = false;
}

function renderFindings() {
  const container = $("findings");
  container.replaceChildren();
  if (!state.report.findings.length) {
    container.append(element("div", "empty-state", "No drift observed in the collected fixture scope."));
    return;
  }
  state.report.findings.forEach(finding => {
    const button = element("button", `finding ${finding.severity}${finding.id === state.selected ? " active" : ""}`);
    button.setAttribute("aria-pressed", String(finding.id === state.selected));
    button.append(element("span", "finding-indicator"));
    const body = element("div");
    body.append(element("div", "finding-title", finding.title),
      element("div", "finding-subtitle", `${finding.resource_name} · ${finding.field}`));
    button.append(body, element("span", `badge ${finding.severity}`, labels[finding.severity]));
    button.addEventListener("click", () => {
      state.selected = finding.id;
      renderFindings();
      renderBrief();
    });
    container.append(button);
  });
}

function renderBrief() {
  const finding = state.report.findings.find(f => f.id === state.selected);
  const box = element("div", "brief-body");
  if (!finding) {
    box.append(element("h3", "", "The approved baseline matches"),
      element("p", "", "No differences were found in the allowlisted synthetic attributes. This is not a claim of complete security coverage."));
    $("investigation").replaceChildren(box);
    return;
  }
  const badges = element("div", "brief-label");
  badges.append(element("span", `badge ${finding.severity}`, labels[finding.severity]),
    element("span", "section-label", finding.status.toUpperCase()));
  box.append(badges, element("h3", "", finding.title), element("p", "", finding.explanation));
  const diff = element("div", "diff-box");
  [["APPROVED", finding.before, ""], ["OBSERVED", finding.after, "after"]].forEach(([label, value, cls]) => {
    const row = element("div", `diff-row ${cls}`);
    row.append(element("span", "", label), element("code", "", typeof value === "string" ? value : JSON.stringify(value)));
    diff.append(row);
  });
  box.append(diff);
  const recommendation = element("div", "recommendation");
  recommendation.append(element("span", "", "↳"), element("span", "", finding.recommendation));
  box.append(recommendation);
  $("investigation").replaceChildren(box);
}

function renderGraph() {
  const report = state.view === "baseline" ? state.baseline : state.report;
  if (!report) return;
  $("observed-view").classList.toggle("active", state.view === "observed");
  $("baseline-view").classList.toggle("active", state.view === "baseline");
  $("observed-view").setAttribute("aria-pressed", String(state.view === "observed"));
  $("baseline-view").setAttribute("aria-pressed", String(state.view === "baseline"));
  $("graph-description").textContent = state.view === "baseline" ?
    "Approved fixture baseline only. No live configuration has been changed." :
    "Following declared relationships from an agent tool to synthetic data. Unused identities are also shown.";
  const svg = $("graph");
  svg.replaceChildren(svgElement("title", {}, "Capability graph: agent, Kubernetes identity, AWS role, and synthetic datasets"));
  const defs = svgElement("defs");
  [["normal", "#b6c7c0"], ["added", "#c74d43"], ["removed", "#b8c3bf"]].forEach(([id, color]) => {
    const marker = svgElement("marker", { id: `arrow-${id}`, viewBox: "0 0 10 10", refX: 8, refY: 5, markerWidth: 5, markerHeight: 5, orient: "auto-start-reverse" });
    marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: color }));
    defs.append(marker);
  });
  svg.append(defs);
  report.graph.edges.forEach(edge => {
    const source = positions[edge.source], target = positions[edge.target];
    if (!source || !target) return;
    const x1 = source[0] + 176, y1 = source[1] + 42, x2 = target[0], y2 = target[1] + 42;
    const type = edge.state === "unchanged" ? "normal" : edge.state;
    const path = svgElement("path", {
      d: `M${x1},${y1} C${x1 + 20},${y1} ${x2 - 20},${y2} ${x2 - 4},${y2}`,
      class: `graph-edge ${edge.state}`, "marker-end": `url(#arrow-${type})`
    });
    path.append(svgElement("title", {}, `${edge.source} → ${edge.target}: ${edge.label} (${edge.state})`));
    svg.append(path);
  });
  report.graph.nodes.forEach(node => {
    const position = positions[node.id];
    if (!position) return;
    const [x, y] = position;
    const group = svgElement("g", { transform: `translate(${x},${y})`, class: `graph-node ${node.state}`, tabindex: 0, role: "button", "aria-label": `${node.name}, ${names[node.kind]}, ${node.state}` });
    group.append(svgElement("rect", { width: 176, height: 86, rx: 8 }));
    group.append(svgElement("text", { x: 13, y: 24, class: "node-type" }, names[node.kind]));
    group.append(svgElement("circle", { cx: 159, cy: 20, r: 3, class: "node-dot" }));
    group.append(svgElement("text", { x: 13, y: 48, class: "node-name" }, node.name));
    group.append(svgElement("text", { x: 13, y: 69, class: "node-description" },
      node.state === "unobserved" ? "Observation unavailable" :
      node.state === "changed" ? "Configuration changed" :
      node.kind === "dataset" ? "Synthetic customer data" : "Source evidence attached"));
    const inspect = () => {
      $("node-detail").textContent = `${node.name} · ${node.evidence.source} · ${node.evidence.reference} · ${node.evidence.observed_at}`;
    };
    group.addEventListener("click", inspect);
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inspect(); }
    });
    svg.append(group);
  });
}

async function runReplay(baseline) {
  const request = state.request;
  const scenario = state.scenario;
  $("replay").disabled = true;
  $("reconcile").disabled = true;
  try {
    const result = await api("/api/replay", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario, baseline })
    });
    if (request !== state.request) return;
    const resultBox = $("replay-result");
    resultBox.className = `replay-result ${result.status === "fixture_blocked" ? "blocked" : result.status === "inconclusive" ? "inconclusive" : ""}`;
    const heading = baseline ? "BASELINE PREVIEW ONLY" : result.status.replaceAll("_", " ").toUpperCase();
    resultBox.replaceChildren(element("strong", "", heading), element("br"),
      document.createTextNode(result.message), element("br"),
      document.createTextNode("Synthetic grant replay only. No AWS calls, model attack, email, or infrastructure changes."));
    if (baseline) { state.view = "baseline"; renderGraph(); }
  } catch (error) { if (request === state.request) showError(error); }
  finally {
    if (request === state.request) { $("replay").disabled = false; $("reconcile").disabled = false; }
  }
}

const github = { trigger: "pr", payload: null, request: 0 };

function mark(state) {
  return state === "success" ? "✓" : state === "failure" ? "✗" : "●";
}

function renderStatus(overall) {
  const row = element("div", `gh-status ${overall.conclusion}`);
  row.append(element("span", "gh-check-icon", mark(overall.conclusion)),
    element("span", "", overall.summary));
  return row;
}

function renderCheckRun(run) {
  const state = run.status === "completed" ? run.conclusion : "pending";
  const row = element("div", `gh-check ${state}`);
  const body = element("div");
  body.append(element("div", "gh-check-name", run.name),
    element("div", "gh-check-summary", run.summary));
  row.append(element("span", "gh-check-icon", mark(state)), body);
  return row;
}

function renderBlocks(container, blocks) {
  blocks.forEach(block => {
    if (block.kind === "list") {
      const list = element("ul", "gh-list");
      block.items.forEach(item => list.append(element("li", "", item)));
      container.append(list);
    } else if (block.kind === "code") container.append(element("code", "gh-codeblock", block.text));
    else container.append(element("p", "", block.text));
  });
}

function renderComment(comment) {
  const card = element("div", "gh-comment");
  const head = element("div", "gh-comment-head");
  head.append(element("span", "gh-avatar", comment.initials),
    element("strong", "", comment.author),
    element("span", "gh-comment-meta", `${comment.relationship} · ${comment.posted_at}`),
    element("span", "badge neutral", "PREVIEW"));
  const body = element("div", "gh-comment-body");
  renderBlocks(body, comment.body);
  card.append(head, body);
  return card;
}

function renderPullRequest(view, payload) {
  const pr = payload.pull_request;
  const card = element("div", "gh-card");
  const head = element("div", "gh-pr-head");
  const title = element("div", "gh-pr-title");
  title.append(element("strong", "", pr.title),
    element("span", "gh-pr-number", `#${pr.number}`),
    element("span", "gh-chip", pr.state));
  head.append(title, element("div", "gh-pr-meta",
    `${pr.author} wants to merge ${pr.commits} commit into ${pr.base} from ${pr.branch} · ` +
    `${pr.files_changed} file changed · +${pr.additions} −${pr.deletions}`));
  head.append(renderStatus(payload.checks.overall));
  const checks = element("div", "gh-checks");
  payload.checks.runs.forEach(run => checks.append(renderCheckRun(run)));
  head.append(checks);
  card.append(head);
  payload.diff.files.forEach(file => {
    const header = element("div", "gh-file-header");
    const stats = element("div", "gh-file-stats");
    stats.append(element("span", "add", `+${file.additions}`),
      element("span", "del", `−${file.deletions}`));
    header.append(element("span", "gh-file-path", file.path), stats);
    card.append(header);
    file.hunks.forEach(hunk => {
      card.append(element("div", "gh-hunk-header", hunk.header));
      hunk.lines.forEach(line => {
        const row = element("div", `gh-line ${line.origin === "+" ? "add" : line.origin === "-" ? "del" : "ctx"}`);
        row.append(element("span", "gh-ln", line.old_line === null ? "" : String(line.old_line)),
          element("span", "gh-ln", line.new_line === null ? "" : String(line.new_line)),
          element("code", "", line.text));
        card.append(row);
        if (line.origin !== "-" && line.new_line !== null) {
          payload.review.inline
            .filter(comment => comment.path === file.path && comment.line === line.new_line)
            .forEach(comment => card.append(renderComment(comment)));
        }
      });
    });
  });
  card.append(renderComment(payload.review.summary_comment));
  view.append(card);
}

function renderPush(view, payload) {
  const push = payload.push;
  const card = element("div", "gh-card");
  card.append(element("div", "gh-push-head",
    `${push.pusher} pushed ${push.commits.length} commits to ${push.branch}`));
  push.commits.forEach(commit => {
    const row = element("div", "gh-commit");
    const who = element("div", "gh-commit-who");
    who.append(element("span", "gh-commit-sha", commit.sha),
      element("span", "", `${commit.author} committed`));
    row.append(element("span", "gh-avatar", commit.initials), who,
      element("div", "gh-commit-message", commit.message));
    card.append(row);
    const detail = element("div", "gh-commit-detail");
    detail.append(renderStatus(commit.checks.overall));
    commit.checks.runs.forEach(run => detail.append(renderCheckRun(run)));
    commit.comments.forEach(comment => detail.append(renderComment(comment)));
    card.append(detail);
  });
  view.append(card);
}

function renderIssue(view, payload) {
  const issue = payload.issue;
  const card = element("div", "gh-card");
  const head = element("div", "gh-issue-head");
  head.append(element("div", "gh-issue-title", issue.title));
  const labels = element("div", "gh-labels");
  issue.labels.forEach(label => labels.append(element("span", `gh-label ${label.id}`, label.name)));
  head.append(labels, element("div", "gh-issue-meta",
    `${issue.author} opened this issue · ${issue.opened_at} · ${issue.meta}`));
  card.append(head);
  card.append(renderComment({
    author: issue.author, initials: issue.initials,
    relationship: "filed by the scheduled run", posted_at: issue.opened_at,
    body: issue.body
  }));
  payload.comments.forEach(comment => card.append(renderComment(comment)));
  view.append(card);
}

function renderGithub() {
  const payload = github.payload;
  $("github-description").textContent = payload.frame.description;
  const view = $("github-view");
  view.replaceChildren();
  if (payload.kind === "pull_request") renderPullRequest(view, payload);
  else if (payload.kind === "push") renderPush(view, payload);
  else if (payload.kind === "issue") renderIssue(view, payload);
}

async function loadTrigger(identifier) {
  const request = ++github.request;
  github.trigger = identifier;
  $("error").classList.add("hidden");
  document.querySelectorAll(".trigger-button").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.trigger === identifier));
  });
  try {
    const payload = await api(`/api/github?trigger=${encodeURIComponent(identifier)}`);
    if (request !== github.request) return;
    github.payload = payload;
    renderGithub();
  } catch (error) { if (request === github.request) showError(error); }
}

$("observed-view").addEventListener("click", () => { state.view = "observed"; renderGraph(); });
$("baseline-view").addEventListener("click", () => { state.view = "baseline"; renderGraph(); });
$("replay").addEventListener("click", () => runReplay(false));
$("reconcile").addEventListener("click", () => runReplay(true));
$("export").addEventListener("click", () => {
  if (!state.report) return;
  const blob = new Blob([JSON.stringify(state.report, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = element("a");
  link.href = url;
  link.download = `drift-evidence-${state.scenario}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

async function boot() {
  try {
    const [scenarios, baseline, triggers] = await Promise.all([
      api("/api/scenarios"), api("/api/report?scenario=clean"), api("/api/triggers")
    ]);
    state.baseline = baseline;
    scenarios.forEach(scenario => {
      const button = element("button", "scenario-button", scenario.name);
      button.dataset.scenario = scenario.id;
      button.title = scenario.description;
      button.setAttribute("aria-pressed", String(scenario.id === state.scenario));
      button.addEventListener("click", () => loadScenario(scenario.id));
      $("scenarios").append(button);
    });
    triggers.forEach(trigger => {
      const button = element("button", "trigger-button", trigger.name);
      button.dataset.trigger = trigger.id;
      button.title = trigger.description;
      button.setAttribute("aria-pressed", String(trigger.id === github.trigger));
      button.addEventListener("click", () => loadTrigger(trigger.id));
      $("github-triggers").append(button);
    });
    await Promise.all([loadScenario("iam"), loadTrigger("pr")]);
  } catch (error) { showError(error); }
}
boot();
