# Phase 1 — v0.10.0 · Quick wins + Mem bootstrap

## Goal

Close six low-risk gaps in one day so Phase 2 starts on a clean foundation: Mem `QA Run Logs` collection is real (not a placeholder), the four hardcoded UUID refs are gone, caching is on by default, the two empty matrix rules don't fire false matches, and `gitlab_open_thread` returns a working URL.

## Gaps closed

### GAP-19 · Fix `gitlab_open_thread.py` thread_url construction · LOW

**Why now:** It's a one-line bug we caught during the MR 6865 live exercise. The thread posted successfully, but the returned `thread_url` 404s because it uses the numeric project ID instead of the namespace path.

**Files**
- `skills/qa-gitlab-bridge/scripts/gitlab_open_thread.py`
- `skills/qa-gitlab-bridge/tests/test_open_thread.py` (create if absent)

**Change shape**
- Today: `thread_url = f"{gitlab_url}/{project_id}/-/merge_requests/{mr_iid}#note_{note_id}"`
- Want: read `mr.web_url` from the prior `get_mr` payload (already cached) and append `#note_{note_id}`. If `web_url` is absent, fall back to a `get_mr` call inside the script (no extra API hop in the common case).

**Tests**
- New: `test_thread_url_uses_namespace_path` — given a stub `MRFetch` with `web_url = "https://gitlab.com/medtrics/medtrics/-/merge_requests/6865"` and `note_id = 3426507991`, the returned URL contains `medtrics/medtrics`, not the numeric project ID.

**Acceptance**
- Run against MR !6865 again; click the returned URL; lands on the comment.

**Risk:** None.

---

### GAP-11 · Default `--cache-ttl` to a non-zero value · LOW

**Why now:** Caching exists but is opt-in. Each `/manual-qa-execute` call re-fetches the MR + checklist attachment. Default-on is the right policy; `--no-cache` already exists as the bypass.

**Files**
- `skills/qa-gitlab-bridge/scripts/gitlab_get_mr.py` — default `--cache-ttl 300`.
- `skills/qa-gitlab-bridge/scripts/gitlab_get_pipeline_status.py` — default `--cache-ttl 120`.
- `skills/qa-checklist-reader/scripts/gitlab_download_upload.py` — default `--cache-ttl 600` (attachments are immutable per upload secret).

**Change shape**
- Replace `parser.add_argument("--cache-ttl", type=int, default=0, ...)` with the per-script default above. Keep `--no-cache` as the disable.

**Tests**
- Add `test_cache_default_on_for_get_mr` — call `gitlab_get_mr.py` twice without args; second call serves from cache (assert via `cache.py` hit counter or by patching `gitlab_client.get`).

**Acceptance**
- A second `/manual-qa-execute` invocation on the same MR within 5 minutes does no GitLab GET against the MR endpoint.

**Risk:** A caller that depended on always-fresh reads could miss an updated MR description. Mitigation: documented in README + commands tell the user to pass `--no-cache` when they've just edited the ticket.

---

### GAP-3 · Disable the two empty scenario-matrix rules · MEDIUM

**Why now:** `missing_required_field` and `role_permission_regression` are stub entries with no assertions. They pattern-match the matrix but score as `pass` because there are zero assertions to fail. False reassurance.

**Files**
- `qa/scenario-matrix.yaml` — add `disabled: true` to both rules.
- `skills/qa-chrome-executor/scripts/scenario_dispatcher.py` — in `match_rule()`, skip when `rule.get("disabled", False)`.
- `skills/qa-chrome-executor/tests/test_scenario_dispatcher.py` — add test.

**Change shape**
```
# scenario_dispatcher.py — match_rule()
for rule in matrix["rules"]:
    if rule.get("disabled", False):
        continue   # NEW
    if all_pattern_keys_match(rule, scenario):
        return rule
```

**Tests**
- `test_disabled_rule_skipped` — load a matrix with a disabled rule whose patterns would match; assert `match_rule` returns the next non-disabled rule (or None).

**Acceptance**
- `/manual-qa-execute` against M1-1190 no longer emits a phantom `missing_required_field` or `role_permission_regression` pass row.

**Risk:** None. The two rules were dormant.

---

### GAP-13 · Login-URL discovery (procedure update only) · MEDIUM

**Why now:** Hardcoded `/login` and `/users/login/` both exist in different places. Wrong on Medtrics deploys whose tenant routes login through a different path.

**Files**
- `skills/qa-ui-executor/SKILL.md` — Step 1 (login).

**Change shape (SKILL.md, not code)**
- Procedure becomes:
  1. `navigate(mr_resolution.deploy_url)` — bare root.
  2. Wait for load (`settle(2000)` — see GAP-17, but provide a fixed-wait fallback in v0.10).
  3. Read final URL via `tabs_context_mcp`.
  4. **Detection rule:** call `find("password input")`. If a match returns, the current page IS the auth surface; proceed to fill credentials. If no match, treat as session-inherited (see GAP-14).
  5. No URL string-matching. No `/login` literal anywhere.

**Tests**
- None at the code level — this is SKILL.md prose. Acceptance test below covers it.

**Acceptance**
- Pilot run against a deploy whose login is at a non-default path lands at the right form without hardcoded path knowledge.

**Risk:** A deploy that loads login on a page WITHOUT a password input (e.g., behind a "Sign in with SSO" button only) breaks this. Mitigation: SKILL.md notes the fallback — if no password input AND no inherited session, raise `blocked_reason: login_form_not_found`.

---

### GAP-14 · Replace text-based "session inherited" detection · MEDIUM

**Why now:** Today the check is "if page contains 'Sign in' text → unauthenticated." Multiple Medtrics screens contain "Sign in" as a button or link elsewhere on the page. Brittle.

**Files**
- `skills/qa-ui-executor/SKILL.md` — Step 1 detection.

**Change shape (SKILL.md, not code)**
- Replaces the prior text-match with the structural rule from GAP-13: `find("password input")`. Match → unauthenticated. No match → inherited session, proceed.

**Tests**
- Same as GAP-13. The two gaps share a procedure rewrite.

**Acceptance**
- Pilot run on a tenant where the user is already authenticated via Chrome's session cookie does NOT attempt a fill on a non-existent password field.

**Risk:** Same as GAP-13.

---

### GAP-2 · Provision the Mem `QA Run Logs` collection (the unblocker) · HIGH

**Why now:** Three docs + one script reference a placeholder UUID. Without a real collection, every Mem write either (a) is a no-op or (b) hits an error path. Phase 3 (first live Optimus write) depends on round-tripping the run-log entry, so this has to land first.

**Files**
- One-time setup run: `/setup-medtrics-qa-automation` → step 4 (already calls `create_collection("QA Run Logs")`).
- `skills/qa-memory/SKILL.md` line ~58 — replace hardcoded UUID with `{{ config.mem.run_logs_collection_id }}` reference.
- `skills/qa-queue/SKILL.md` line ~47 — same.
- `skills/qa-queue/scripts/build_dashboard_widget.py` line ~27 — replace hardcoded UUID in the CLI example.
- One additional check: grep the entire plugin for the placeholder UUID; replace any straggler.

**Change shape**
- The collection ID lives in `~/.medtrics-qa-automation/config.json` under `mem.run_logs_collection_id`.
- Scripts that need it read via `qa-config` skill helpers (already exposed).
- SKILL.md prose tells the executor: "Look up `config.mem.run_logs_collection_id` to find the collection. Setup created it; if missing, run `/setup-medtrics-qa-automation` first."

**Tests**
- `test_dashboard_widget_uses_config_collection_id` — patch `qa-config.read()` to return a known UUID; assert the rendered widget HTML references that UUID, not the placeholder.

**Acceptance**
- Setup completes; `config.json` contains a non-placeholder UUID.
- A `/manual-qa-execute` run writes one note to the collection; `find_related_notes(query=...)` finds it.

**Risk:** The setup step needs a network connection to Mem and a working MCP. If Mem is down, setup hangs — already handled in setup with retry + skip option; document that the placeholder will stay until setup completes.

---

## Phase-wide acceptance test

Run `/manual-qa-execute --ticket M1-1190` once. Verify:
- A real Mem note is written under the `QA Run Logs` collection (not the placeholder UUID).
- The second-pass invocation in <5 minutes serves the MR fetch from cache.
- `scenario-matrix.yaml`'s two disabled rules don't appear in the verdict report.
- The fail-thread URL (if any) lands on the comment.
- The audit log contains zero references to a hardcoded UUID after the run.

## Risks

- **Setup blocks on a broken Mem MCP.** Mitigation: setup already has a "skip Mem setup" path; document it.
- **Replacing the placeholder UUID in multiple files in one pass risks a typo.** Mitigation: grep audit pre-merge.

## Out of scope (Phase 1 explicitly does NOT do)

- Refactor the per-step executor loop — that's Phase 2.
- Add new assertion kinds — that's Phase 2.
- Live Optimus writes — that's Phase 3.
- Schedule the polling task — that's Phase 4.

## Effort

- **Code:** ~30 LOC across 5 files.
- **Docs:** SKILL.md edits in qa-ui-executor, qa-memory, qa-queue.
- **Tests:** ~5 new test cases.
- **One-time:** the setup run that creates the Mem collection.
- **Time:** 1 day, assuming setup connectivity works on the first try.
