## {verdict_emoji} Automated QA1 — {verdict_title} — {ticket}

| Field | Value |
|---|---|
| Ticket | [{ticket}]({optimus_url}) |
| Branch | `{branch}` |
| Deploy | {deploy_url} |
| Lane | `{lane}` |
| Verdict | **{verdict}** (confidence {verdict_confidence}) |
| Pass rates | P0 **{p0_pass_rate}** · P1 **{p1_pass_rate}** · P2 {p2_pass_rate} |
| Steps | {passed_count} passed · {failed_count} failed · {needs_human_count} needs human · {total_steps} total |
| Run | `{run_id}` |

{partial_cause_block}

{truncation_notice}

### Plain-English summary for QA2 review

**What was tested:**

{narrative_test_summary}

**What we observed:** {narrative_outcomes}

**What we did NOT cover (needs human review or wasn't applicable):**

{narrative_gaps}

### Per-step technical evidence

Screenshot, console snippet, and network capture for every step are in the collapsible blocks below. Click a step to expand its evidence.

{step_evidence_blocks}

{ui_observations_section}

---

🧠 Full run log: {mem_url} · 📺 [Cowork dashboard]({dashboard_url})

_Posted by `medtrics-qa-automation:qa-fail-reporter` v{plugin_version}. Edit the `## QA Checklist` on the ticket to re-test; the next run replaces this thread._
