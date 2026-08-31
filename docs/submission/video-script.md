# Video script — Baraza: memory with due process

**Hard cap: 4:00. This script is budgeted to 3:50** — narration ends at 3:50,
leaving 0:10 of slack for breath and cuts. Verify the final duration in the
editor's timeline, not by estimate.

**Recording rules, non-negotiable:**

- The centrepiece (Shot 3) is **one unedited take** — no cuts, no speed ramps.
  If the model misbehaves mid-take, keep rolling: the fallback beats are scripted
  below and each of them still scores.
- Every visible string in every frame is synthetic or the builder's own. Freeze
  and read each frame before locking the cut.
- No unmeasured number is spoken or captioned. Appendix B is the checklist.
- Narration is verbatim as written. The phrases in it were chosen against a
  hostile-judge review; improvising around them is how banned sentences get
  spoken on camera.

**How to read a shot block:** ON SCREEN is what the recording shows. NARRATION
is spoken verbatim. PRECONDITIONS are what must already be true before the take;
each is flagged **[agent-verified]** (verified mechanically in the tree or
against the live project as of 2026-08-31, evidence named) or **[user-must-do]**
(requires your credentials, your browser, or a sibling work-stream landing —
confirm it yourself on recording day).

---

## Global preconditions (check once, before any take)

- **[user-must-do]** The dossier web face (claim panel, agenda rail, divergence
  card, dossier list, doctrine view, approval queue) is deployed and reachable.
  This is the WS2 surface; every shot below renders in it. Confirm by loading
  the public URL logged out, in a private window.
- **[user-must-do]** The hosted `.run.app` URL you will read aloud in Shot 5 is
  the same URL entered on the Devpost form. The last URL verified live (HTTP 200
  logged out, 2026-08-15) was `https://baraza-successor-tlaymplktq-uc.a.run.app`;
  if the rename redeployed the public service under the dossier name, use the
  new URL everywhere and retire the old one.
- **[user-must-do]** Application Default Credentials present; live Vertex calls
  work from this machine. The centrepiece is shot against **live Vertex**, never
  against cassettes.
- **[user-must-do]** At least several days of real dogfooding sessions exist in
  the Firestore event log, so the timestamps in Shots 3–6 predate recording day.
  Elapsed time cannot be faked and cannot be compressed.
- **[agent-verified]** Model pins resolve against live Vertex:
  `gemini-3.7-flash` (reasoning), `gemini-3.5-flash` (fast), location `global`
  — live-verified 2026-08-31 against project `baraza-2026`, recorded in
  `src/baraza/schema/models.py`.
- **[agent-verified]** Firestore append-only rules are deployed and were
  verified live: `scripts/verify_append_only.sh` → passed 3, skipped 2,
  failed 0 (2026-08-15, `STOPPED-DEPLOY.md`). Re-run it on recording day anyway — Shot 2
  depends on the refusal happening on camera.

---

## Shot 1 — The friction (0:00–0:20)

**ON SCREEN:** A generic chat application's memory pane — a flat list of
paraphrased "memories" with no sources, no dates, no way to see why any of them
exists. (Use a mock or the builder's own account with only synthetic content
visible; no product logo needs to be legible and no vendor is named.) At 0:12,
hard cut to the Baraza dossier view: a list of beliefs, each with a verbatim
quote, a turn anchor, and a timestamp.

**NARRATION (verbatim):**

> "Every AI product is bolting on memory, and every one of them is an opaque
> blob. It paraphrases you, it can't say where a belief came from, and you can't
> correct it. This is Baraza's answer: a dossier. Every belief about me is a
> claim, with my exact words, and the moment I said them."

**PRECONDITIONS:**

- **[user-must-do]** A memory pane to film that contains no real third-party
  data — a mock is fine and safer.
- **[user-must-do]** The dossier view holds real beliefs from prior dogfooding
  sessions (WS2 + WS3 landed; sessions run).

---

## Shot 2 — Pitch, architecture, and the log that refuses (0:20–0:45)

**ON SCREEN:** 0:20–0:32 the architecture diagram (`docs/architecture.svg`):
ingest → claims → append-only Firestore log → fold → doctrine, with the
approval gate marked as the only writer of `committed`. 0:32–0:45 the Firestore
console, live: open an event document in the `events` collection, attempt to
edit a field, click save — **the rules refuse the write on camera**. Hold on
the error.

**NARRATION (verbatim):**

> "Under it: every belief is appended to a log whose deployed rules reject
> update and delete — watch me try to edit one in the console. Refused. A log
> that cannot be quietly rewritten. Beliefs only act after I ratify them, and
> the doctrine the agent runs under cites, for every rule, the claim that put
> it there."

**PRECONDITIONS:**

- **[agent-verified]** `docs/architecture.svg` exists in the tree, self-contained,
  legible in light and dark. **[user-must-do]** Confirm it reflects the dossier
  framing (WS7 rewrite) before filming it.
- **[agent-verified]** Append-only rules deployed (see global preconditions).
- **[user-must-do]** Firestore console open, logged in, on the `events`
  collection of `baraza-2026`, with an event doc selected before the take
  starts. Rehearse the edit-refusal click path once off camera.

---

## Shot 3 — THE CENTREPIECE: one unedited take (0:45–2:10)

**ON SCREEN:** The working-session view, live against Vertex. The builder is
drafting a real document (this submission's own materials — dogfooding on
camera). The claim panel is visible at all times. The sequence, in one take:

1. (~0:45) The builder types a rule into the session: *"Never state a number in
   a submission doc unless it traces to a metrics entry."*
2. (~0:55) The belief appears in the claim panel: verbatim quote, anchor
   `turn:t-N`, status `proposed`.
3. (~1:10) Drafting continues; a second, colliding instruction is typed:
   *"Just put a rough number in for now, we'll fix it later."*
4. (~1:20) **The divergence card fires**, both quotes on screen with their turn
   anchors: the earlier rule and the sentence just typed. The agent asks which
   governs and refuses to silently overwrite the old rule.
5. (~1:35) The builder adjudicates by splitting it into a conditional: numbers
   must trace to metrics in submitted artifacts; drafts may carry a marked
   placeholder. A new, judgment-shaped belief is proposed.
6. (~1:50) The approval queue: the builder ratifies the split. The doctrine
   view updates — the new rule visible **with the claim ID and quote that put
   it there**.
7. (~2:00) The next draft paragraph visibly follows the new rule.

**NARRATION (verbatim, paced over the take):**

> "This is live and unedited. I'm drafting this submission with Baraza. I state
> a rule — and it lands in the claim panel as my exact words with a turn anchor,
> not a paraphrase. Later I contradict myself — and it catches me. Both quotes,
> both moments, on screen. It won't silently keep the newer one; I have to
> decide. I split it into a conditional — that's a judgment, not a preference.
> I ratify it in the approval queue, because no belief acts on my behalf until
> I've signed it. And there it is in the doctrine: the new rule, citing the
> exact claim — my exact sentence — that created it. The next draft follows it."

**FALLBACK (keep rolling, still scores):** if extraction misses the rule or the
divergence card does not fire, the agent asks a clarifying question about the
under-specified rule instead. Narrate honestly: *"It didn't catch that one —
so it asks. A question here only exists because two of my own statements
collide, or a rule is too vague to compile."* Do not re-take dishonestly; a
visible ask is the same machinery.

**PRECONDITIONS:**

- **[user-must-do]** WS2 session view + WS3 extraction and doctrine compiler +
  WS4 divergence retarget all landed and smoke-tested end to end at least once
  before the take.
- **[user-must-do]** Live Vertex from this machine; a second window with the
  Cloud Console log stream visible if the frame allows — live proof beats
  assertion.
- **[user-must-do]** The earlier rule in step 1 is genuinely new in this take,
  or already committed from a prior session — either is honest; do not pre-seed
  and pretend it is new.

---

## Shot 4 — The dossier: reject and rerun (2:10–2:40)

**ON SCREEN:** The dossier view — the full file the agent keeps on the builder:
every belief, quote, anchor, timestamp, status. The builder clicks **Reject**
on one committed belief; the retraction appends as its own event. Rerun the
same fixed drafting task. The output differs. Open the **doctrine diff**: the
changed rule, with the retracted claim named as its source.

**NARRATION (verbatim):**

> "This is the file it keeps on me, and I can open it. Every belief, my quote,
> the moment it was learned. I reject one — the retraction is itself an
> append-only event, not an edit. I rerun the same task. The output changes,
> and the doctrine diff names exactly which rule changed and which claim of
> mine it came from. Same doctrine, every rule cited. Compiling my beliefs into
> policy is replayable byte for byte; what the model does with that policy is
> honest work, and we measure it instead of promising it."

**PRECONDITIONS:**

- **[user-must-do]** WS5 doctrine diff (`src/baraza/doctrine/diff.py`) landed;
  reject-and-rerun path smoke-tested.
- **[user-must-do]** A committed belief exists whose rejection visibly changes
  the fixed task's output — rehearse the pair off camera to pick a belief where
  the difference is legible in one glance.

---

## Shot 5 — Google Cloud proof (2:40–3:15)

**ON SCREEN, in order:**

1. (2:40) Cloud Run dashboard for `baraza-2026`: the deployed services and the
   two jobs (`baraza-reconcile`, `baraza-ingest`), all green.
2. (2:52) Vertex AI request logs showing live calls to `gemini-3.7-flash` and
   `gemini-3.5-flash`.
3. (3:02) Cloud Scheduler execution history, plus the most recent
   agent-initiated session invitation in the log — the `session.proposed` event
   with its honest `scheduled` label visible in the payload.
4. (3:10) The browser address bar on the public URL. Cursor rests on it.

**NARRATION (verbatim):**

> "All of it runs on Google Cloud: Cloud Run services and jobs, Firestore with
> those append-only rules, Vertex AI serving Gemini 3.7 Flash and 3.5 Flash,
> and Cloud Scheduler starting the loop — every scheduled run labelled
> 'scheduled' in the log, never passed off as organic. It's live at
> `<READ THE VERIFIED PUBLIC URL ALOUD, e.g. baraza-successor-tlaymplktq-uc.a.run.app>`."

**PRECONDITIONS:**

- **[user-must-do]** The Scheduler trigger fix (WS1, OIDC-via-service per
  `STOPPED-DEPLOY.md`'s 2026-08-31 update) is deployed and the execution
  history shows real successful runs. **As of 2026-08-31 the direct trigger
  403s and history shows failures — do not film the history until it is
  green.** If it is not fixed by recording day, film the Cloud Run *job*
  execution list (real, successful, timestamped) instead and say "scheduled
  initiation is deployed behind a trigger fix documented in the repo" — honest
  and verifiable.
- **[user-must-do]** The `.run.app` URL filmed, spoken, and submitted are the
  same string.
- **[agent-verified]** The `scheduled` honesty flag exists in the code path
  (`reconcile/differential.py`, commit `0fca155`). **[user-must-do]** The
  deployed job image postdates that commit — rebuild before filming any run
  history (`BARAZA_PROJECT_ID=baraza-2026 make bootstrap`).

---

## Shot 6 — Leads the way: the closed loop (3:15–3:45)

**ON SCREEN:** The morning invitation — the outbound notification (email or
log entry) generated by the scheduled reconcile job: a numbered agenda, each
item citing the ledger entry that spawned it. Then the session-length evidence:
the agenda rail of session N beside session N+1, N+1 visibly shorter, with the
retirement events linking resolved items in the log.

**NARRATION (verbatim):**

> "And it leads. Every morning the scheduled job reads the log, finds the open
> contradictions and stale beliefs, and invites me to a session with a numbered
> agenda — each item citing the ledger entry that raised it. When an item is
> resolved, it retires itself, on the record. So the next session is visibly
> shorter than the last. That's the loop closing: it asks, I answer, it stops
> asking."

**PRECONDITIONS:**

- **[user-must-do]** WS1 initiation (`reconcile/initiate.py`, the
  `session.proposed` event, one outbound channel) landed and has produced at
  least two consecutive real sessions, so N and N+1 both exist with genuine
  timestamps.
- **[user-must-do]** The two agenda rails to film actually differ in length
  because items were genuinely resolved — pick the pair from the real log, do
  not stage it.

---

## Shot 7 — Close (3:45–3:50)

**ON SCREEN:** The dossier view, held. One line of caption: *Baraza — memory
with due process.*

**NARRATION (verbatim):**

> "Adaptation with due process. Open the file it keeps on you."

*(Narration ends at 3:50. Hold the frame to 3:55 max; total ≤ 4:00.)*

**PRECONDITIONS:** none beyond Shot 4's.

---

## Timecode budget check

| Shot | Start | End | Duration |
|---|---|---|---|
| 1 Friction | 0:00 | 0:20 | 0:20 |
| 2 Pitch + refusal | 0:20 | 0:45 | 0:25 |
| 3 Centrepiece | 0:45 | 2:10 | 1:25 |
| 4 Dossier reject/rerun | 2:10 | 2:40 | 0:30 |
| 5 Google Cloud proof | 2:40 | 3:15 | 0:35 |
| 6 Leads the way | 3:15 | 3:45 | 0:30 |
| 7 Close | 3:45 | 3:50 | 0:05 |
| **Total** | | | **3:50** |

---

## Appendix A — judge-participation variant (live judging only)

If judging is live and a judge can be handed the keyboard, replace Shot 3's
step 3 with the judge-fired beat. Nothing else in the script changes; the
timing holds because the beat replaces, not extends, the self-contradiction.

**Setup (before the session, honestly):** the belief "never pad estimates" was
committed in a genuinely prior logged session — its timestamp predates demo
day in a log that rejects edits. Do not commit it the morning of and imply
otherwise; the whole point is that the console can be checked.

**The beat:** the judge types an instruction of their choosing; if it collides
with any committed belief — e.g. "pad the estimates to be safe" — the
divergence card fires with both quotes: the judge's sentence and the builder's
committed rule with its turn anchor and date. Invite the judge to open the
Firestore console and read the old belief's timestamp. Adjudicate on stage:
split into a conditional ("never internally; pad client-facing"), ratify,
watch the doctrine update and the next draft change.

**Spoken framing (verbatim):**

> "You typed that; I didn't. The machinery that caught it is the same
> contradiction detector that catches me — and you can check the console: that
> belief predates today, in a log that refuses edits."

**Fallback:** if the judge's instruction collides with nothing, the agent
either extracts it as a new proposed belief (show the quote + anchor landing in
the panel) or asks a clarifying question because the rule is under-specified.
Both are scripted product behavior; narrate them as such.

---

## Appendix B — what must NOT be claimed (freeze-frame checklist)

Read this against the locked cut, frame by frame and word by word.

**Numbers.** Every one of these is currently `not yet measured` and must not be
spoken, captioned, or shown until it carries a run ID in `docs/metrics.json`:

- the doctrine determinism replay count and hash result
- the rule-compliance delta (before/after battery)
- any belief count, session count, or nightly-run count presented as a total
- any latency, cost, or extraction-accuracy figure
- any acceptance-rate or improvement-curve percentage — this number was
  explicitly killed in review and does not exist

If a number has been measured by recording day, it may be used only as
measured — including if it is unflattering. An imperfect real number on screen
is the project's culture; a smooth invented one is disqualifying.

**Banned sentences and framings, with prejudice:**

- "deterministic" predicating *behavior*, in any wording. What is replayable
  byte-for-byte is the fold → doctrine compilation. Model compliance with the
  doctrine is probabilistic. The approved phrasing is **"same doctrine, every
  rule cited"** — never "same behavior", never "replay the fold and get the
  same behavior."
- Any claim of line-level output causality — never say or show that a specific
  output line was caused by a specific claim. The honest artifact is the
  **doctrine diff** (rule ← claim provenance) plus before/after outputs on a
  fixed task, presented side by side without causal annotation of lines.
- Any mention or defense of the previous adaptation mechanism. It is gone.
- Scheduled runs presented as organic activity — the `scheduled` label stays
  visible whenever run history is on screen.
- Any model version claim not matching the live-verified pins in
  `src/baraza/schema/models.py`.
- Any real person, company, or organization named as an example or bad actor.
  The only human in this story is the builder.
