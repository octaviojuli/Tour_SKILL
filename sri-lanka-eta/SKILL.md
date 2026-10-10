---
name: sri-lanka-eta
description: Automate Sri Lanka ETA Tourist Individual form filling on eta.gov.lk using Playwright with human-in-the-loop. Use this skill when users ask to apply Sri Lanka ETA, auto-fill visa form fields, debug ETA form submission errors, compare manual vs automation behavior, or stabilize ETA automation flow. Handles dialog popups, readonly date fields, passport AJAX validation recovery, QN question toggling, pre-submit checks, and stops at Review/Confirm for manual control.
---

# Sri Lanka ETA Automation (OpenClaw-ready)

Automate `eta.gov.lk/etaslvisa/etaNavServ` Tourist ETA Individual flow for form filling and review handoff.

## Execution Boundaries (mandatory)

- Keep human-in-the-loop for final decision: stop at Review page (`Change` / `Confirm` visible).
- Do not automate payment/OTP/3DS or anti-bot bypass.
- Do not claim submission success unless Review page content is verified.

## Runtime Setup

```bash
npm install playwright
npx playwright install webkit
node scripts/fill-eta.mjs --payload payload.json
```

## Input Rules

- Update applicant data in `payload.json` (or provide a custom file with `--payload /path/to/file.json`).
- Select fields must use `CODE|NAME` format (for example `CHN|CHINA`, `03|MISS`, `V01|Sightseeing or Holidaying`).
- Date input can be provided as `DD/MM/YYYY`, but submit path must normalize to `MM-DD-YYYY`.

## Critical Flow Contract

1. Open ETA homepage and accept terms.
2. Select Tourist Individual form.
3. Fill all required fields with site-compatible interactions.
4. Trigger QN sequence as validated in production behavior (Yes -> No for each QN, final state No).
5. Click `Next`.
6. Verify Review page (not error page), screenshot evidence, then manual handoff.

## Required Technical Behaviors

- **Dialog handling**: accept ETA confirms/alerts that are expected in this flow.
- **Readonly dates**: remove readonly, set normalized date, fire `input/change/blur`, restore readonly.
- **Passport AJAX**: after blur/validation alert, recover passport values and ensure hidden pass state is valid.
- **Address fields**: use keyboard typing strategy where plain `fill()` is unreliable.
- **Departure country**: `#fromDeparture` must be selected before submit.
- **Child section**: if under-16 block appears and applicant has independent passport, keep child-enable unchecked unless explicitly required.

## Pre-submit Assertions (must pass)

- Date fields (`bdate`, `pidate`, `pedate`, `iadate`) are `MM-DD-YYYY`.
- `passportno === reenteredpassportno`.
- Hidden passport validation state indicates pass.
- `QN1/QN2/QN3` final values are all `0`.
- `fromDeparture` is non-empty.
- Declaration checkbox (`conf`) is checked.

## Success / Failure Signals

- **Success**: Review page contains applicant summary and shows both `Change` and `Confirm`.
- **Failure**: page contains `Error Notification` or `Operation aborted`; capture screenshot and stop.

## Diagnostics

- Capture screenshots for filled form and review/error page.
- Log pre-submit snapshot for key fields.
- Use HAR comparison (manual-success vs automation-run) when mismatch occurs.

## References

- Field map and selector notes: `references/form-fields.md`
