# expected → assertion mapping (qa-ui-executor)

The deterministic bridge from a checklist step's free-text `expected` field to a
structured UI assertion. This is what keeps the agentic lane honest: if a step's
expectation maps to nothing here, the step is `needs_human`, never auto-pass.

The mapping is applied case-insensitively. The **first** matching pattern wins.
Each row yields one `Assertion(kind, args)` evaluated by
`scenario_dispatcher.run_ui_assertions`.

| If `expected` matches… | Assertion produced | Notes |
|---|---|---|
| `no (console )?error(s)?`, `without errors`, `no JS errors` | `console_clean` | optional `ignore` from config |
| `shows? "<X>"`, `displays? "<X>"`, `see(s)? "<X>"`, `contains "<X>"` | `text_present {patterns:[X]}` | quoted literal preferred; else the trailing noun phrase |
| `does not show "<X>"`, `no "<X>"`, `"<X>" is gone`, `absent` | `text_absent {patterns:[X]}` | |
| a bare date/number literal, e.g. `date shows 2026-05-12`, `displays 42` | `text_present {patterns:[<literal>]}` | exact substring; covers off-by-one date bugs like M1-1190 |
| `downloads? <name>.<ext>`, `file <name>.<ext> downloads` | `download_filename_eq {pattern:"<name>\\.<ext>$"}` | |
| `button/field/element "<X>" (is )?visible/present/enabled` | `element_visible {selector:<resolved>}` | selector from selectors.json or `find` by text X |
| `"<X>" (is )?hidden/disabled/removed/not (shown\|present)` | `element_absent {selector:<resolved>}` | |
| `field "<X>" (shows\|equals\|= ) "<V>"`, `value is "<V>"` | `value_eq {selector:<X>, value:V}` | |
| `redirect(s)? to <path>`, `lands on <path>`, `url is <path>` | `url_matches {pattern:"<path>"}` | path regex-escaped except `*` |
| `success`/`saved`/`published`/`created` toast/message | `text_present {patterns:[<toast text>]}` + `console_clean` | two assertions; both must pass |
| `validation error`, `rejected`, `4xx`, `non_field_errors` (UI form) | `text_present {patterns:[<error copy>]}` | the *visible* error, not an HTTP code (use the API lane for status codes) |

## Rules

1. **Quoted literals win.** If the `expected` text quotes a string, assert on
   that exact string. Don't paraphrase.
2. **Prefer two cheap assertions over one fuzzy one.** A "save succeeded" step
   is `text_present[success copy]` AND `console_clean` — both must pass.
3. **No structured mapping → `needs_human`.** Vague expectations ("works as
   intended", "looks correct", "behaves normally") are not auto-passable.
   Screenshot and hand to the reviewer.
4. **Never synthesize HTTP-status assertions in the UI lane.** If a step is
   really about a status code, it belongs in the API lane's scenario-matrix.
5. **Selectors are resolved, not guessed.** A produced `element_*` / `value_eq`
   assertion must carry a selector that came from `selectors.json` or a
   successful Chrome MCP `find`; if the element can't be located, the step is
   `fail` (`element_not_found`), not `needs_human`.
