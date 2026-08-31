# BY-HAND.md — everything only you can do

**Today: Sunday 2026-08-31. Deadline: today, 5:00 pm PT.**

Rewritten for the DOSSIER pivot (`docs/pivot/DECISION-dossier.md`). Everything
in this file requires your credentials, your accounts, your face, or real
elapsed time; nothing here can be done by an agent. Items are ordered by when
they stop being recoverable. The previous version of this file (17-day horizon,
items H1–H20) is in git history; done items are not restated except where their
residue still needs you.

Already done, verified on this tree: the repo has a public remote
(`github.com/jeremiah-Sakuda/baraza`); project `baraza-2026` is live with
Firestore append-only rules deployed and verified; the public surface returns
HTTP 200 logged out; the model pins were live-verified 2026-08-31; `make
compliance` and `make test` are green.

---

## 🔴 Before the deadline — non-recoverable if missed

### R1 · Submit to Devpost, and do it before the last hour

Select **The Collaborative Partner**. Before submitting, purge from
`docs/submission/devpost-description.md`: every `<…>` placeholder and every
`not yet measured` occurrence — that discipline earns credit in the README,
where a judge can see it is enforced by a script; in a Devpost field it reads
as unfinished. Add `google-adk` to Built With. Full checklist:
`docs/submission/CHECKLIST.md`.

If the project stayed private anywhere, both judge addresses need access —
granting only one is a common and fatal miss: `testing@devpost.com` and
`cloudhackathons@google.com`.

### R2 · Record and upload the video (≤ 4:00)

Script: `docs/submission/video-script.md`. Your voice, your screen. The three
beats the pivot cannot lose:

- **The judge-fired divergence card.** An uncontrolled instruction ("pad the
  estimates to be safe") collides with a belief committed on a *prior* day —
  then show the Firestore console refusing an edit, so the timestamp is
  credible. If extraction misses, the fallback is the agent asking a clarifying
  question, which itself scores.
- **The doctrine diff**, with the causal claim named per changed rule. Never
  narrate line-level output causality; the phrase is *same doctrine, every rule
  cited*.
- **The Google Cloud proof frames**: Cloud Run dashboard, Vertex logs,
  Scheduler execution history. Shoot the centrepiece against live Vertex with
  the log stream visible, not against cassettes; anything filmed from
  `make demo` is replay and must be labelled as replay.

One line on the name: baraza means council — the place where disputes are heard
and settled on the record. The dispute this one hears is you versus you.

### R3 · Publish the blog and the social post (bonus, your accounts)

`docs/submission/blog-post.md` must be public, not unlisted, and must keep the
"created for the purposes of entering this hackathon" language.
`docs/submission/social-posts.md` must carry `#AllThingsAgenticHackathon`
exactly.

### R4 · Do not tear anything down

The project must stay free and testable until judging ends. **No
`make teardown` before Oct 1.** Keep the billing budget alert; a judged URL
that 404s in September is a self-inflicted loss.

---

## 🟠 Same day, gated on your credentials

### R5 · Record the cassettes

The single command that flips `demo`, `demo-agenda`, `demo-interview`,
`verify-anchors` and the behaviour probes from red to green, then unlocks
`adaptation-metric`:

```bash
python3 scripts/record_cassettes.py --yes && make demo
```

Supervised because it spends live Vertex calls. Run `make demo` immediately
after — a prompt drift produces a loud `CassetteMiss` by design. Until this
runs, the honest sentence in the README stands: the offline demo does not run
on a clean clone.

### R6 · Measure, or leave `not yet measured` standing

Every entry in `docs/metrics.json` reads `not yet measured` and the `runs`
array is empty. The two numbers the pivot's pitch leans on:

1. **Doctrine determinism** — N replays, permuted offsets, identical hash.
2. **Rule-compliance delta** — the fixed scripted battery before/after a belief
   commits or is retracted, scored by objective predicates via
   `make adaptation-metric`.

If a number comes out imperfect, publish the imperfect number — the repo's own
culture demands it, and `scripts/compliance.py` rejects any entry without
provenance. Never type a plausible value; the fallback is always the literal
string `not yet measured`.

### R7 · Verify the trigger's execution history before quoting it

The Scheduler 403 was root-caused to Scheduler's OAuth path and the fix is the
`baraza-trigger` OIDC hop (`docs/deploy-postmortem.md`). Before the video or any doc
quotes a nightly-run count: check the execution history in the console, and
remember `scheduler_nightly_runs_completed` stays `not yet measured` until a
real scheduled run is counted. A manual run is never counted as a scheduled
one — that discipline is in the code (commit 0fca155); keep it in the
narration.

---

## 🟢 Ongoing — real elapsed time, cannot be compressed

### R8 · Keep the daily dogfooding sessions running

The initiation evidence is timestamps accruing in an append-only log. Every day
a session runs, the multi-day epoch record gets stronger; nothing retroactive
can substitute. The demo task is real: Baraza guiding the drafting of this
hackathon's own submission documents.

### R9 · Live with the approval loop, honestly

Approval fatigue is designed-for (batch ratification) but unlived. When someone
asks "would you still use this in October?", the honest answer is a projection,
not data — say so. The dossier's whole argument is that honest beats fluent.

---

## What an agent could not do, and why

| Item | Reason |
|---|---|
| Record cassettes / any measured number | Your credentials; supervised spend |
| Record the video | Your voice, your screen |
| Publish blog / social / Devpost | Your accounts |
| Multi-day initiation epochs | Real elapsed time |
| The judge-fired beat | By construction: the input must be uncontrolled |
