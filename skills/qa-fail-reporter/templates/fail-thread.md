## {verdict_emoji} Automated QA1 {verdict_title} — {ticket}

| Field | Value |
|---|---|
| Ticket | [{ticket}]({optimus_url}) |
| Branch | `{branch}` |
| Deploy | {deploy_url} |
| Lane | `{lane}` |
| Verdict | **{verdict}** (confidence {verdict_confidence}) |
| Pass rates | P0 **{p0_pass_rate}** · P1 **{p1_pass_rate}** · P2 {p2_pass_rate} |
| Failing steps | {failed_count} of {total_steps} |
| Run | `{run_id}` |

{truncation_notice}

### Failing steps

{failing_steps_blocks}

{ui_observations_section}

---

🧠 Full run log: {mem_url} · 📺 [Cowork dashboard]({dashboard_url})

_Posted by `medtrics-qa-automation:qa-fail-reporter` v{plugin_version}. Edit the `## QA Checklist` section on the ticket to re-test; the next run replaces this thread._
