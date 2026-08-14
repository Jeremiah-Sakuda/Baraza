# Video script — Baraza (BAR-601–608)

**Hard cap 4:00.** This script is budgeted to land the final frame at **3:50**,
leaving **0:10 of slack**. Slack is not a place to add a shot. It is there
because narration runs long when you are tired and the cap is a disqualification
line, not a guideline.

**Read before recording:**

- Narration below is **verbatim**. Word counts and the resulting speaking rate
  are given per shot. Anything above ~2.6 words/second sounds rushed on a
  laptop mic; anything the script marks "leave dead air" is deliberate — the
  terminal doing visible work is more persuasive than a voice describing it.
- The centrepiece (section C) is **one continuous unedited take**. If the take
  does not fit the budget, shrink the corpus or the agenda size and record
  again. Do **not** cut, speed-ramp, or jump-cut inside C. The claim being made
  is "this actually ran", and an edit inside the take forfeits it.
- Every shot lists **PRECONDITION** — what must be true beforehand. A shot whose
  precondition is unmet is not recorded with a stand-in. It is cut, and the cut
  is noted in `docs/BUILD-LOG.md`.
- Shots marked **⏳ REAL ELAPSED TIME** cannot be produced on recording day.
  They depend on nights that have to actually pass.

---

## Timecode budget

| § | Beat | In | Out | Dur |
|---|---|---|---|---|
| A | The friction | 0:00 | 0:25 | 0:25 |
| B | What it is, and the architecture in one breath | 0:25 | 0:48 | 0:23 |
| C | **Centrepiece — unedited live terminal** | 0:48 | 2:08 | 1:20 |
| D | Approval, successor, and the refusal | 2:08 | 2:38 | 0:30 |
| E | Google Cloud proof frames | 2:38 | 3:12 | 0:34 |
| F | The differential ledger | 3:12 | 3:38 | 0:26 |
| G | Close | 3:38 | 3:50 | 0:12 |
| — | **Slack against the 4:00 cap** | 3:50 | 4:00 | **0:10** |

---

## A — The friction (0:00–0:25)

### A1 · 0:00–0:08 (8s)

**ON SCREEN.** Black. One line of white type, centred, no logo, no music sting:
`Every May, thousands of organizations forget everything.` Hold the type for a
beat after the line is spoken.

**NARRATION (15 words, 1.9 w/s).**
> "Every May, thousands of organizations forget everything. The officers
> graduate. The knowledge leaves with them."

**PRECONDITION.** None. Record this last — it is the only shot that cannot fail.

---

### A2 · 0:08–0:17 (9s)

**ON SCREEN.** Screen recording of a file browser over the synthetic corpus
directory: folders in a native mess — a PDF whose scan is visibly skewed, two
spreadsheets with no header row, a chat export, meeting minutes in `.docx`.
Scroll slowly. Do not open anything.

**NARRATION (21 words, 2.3 w/s).**
> "The handover is a shared drive: four folders named final, a constitution
> scanned crooked, three years of chat nobody will read."

**PRECONDITION.** `fixtures/corpus/` is generated from `fixtures/corpus/BIBLE.md`
per `fixtures/MANIFEST.md` and contains real files in the four native formats.
Every name visible on screen — org, people, filenames — is synthetic. Freeze the
frame and read every visible string before this take is kept. **Not yet
generated as of this writing.**

---

### A3 · 0:17–0:25 (8s)

**ON SCREEN.** Cut to a plain text prompt on dark background, typed live, one
line: `who can actually sign a cheque?` Cursor blinks. Nothing answers it.

**NARRATION (19 words, 2.4 w/s).**
> "So the incoming treasurer asks the only question that matters — who can
> actually sign a cheque — and nobody knows."

**PRECONDITION.** None. This is a typed prompt, not a running system. Do not
imply it is a product surface; it is a title card that happens to be a cursor.

---

## B — What it is (0:25–0:48)

### B1 · 0:25–0:35 (10s)

**ON SCREEN.** Static architecture diagram (BAR-505), full frame. Held still —
no build animation, no pans.

**NARRATION (20 words, 2.0 w/s).**
> "Baraza reads that mess unattended, asks the corpus what it disagrees with,
> and interviews the departing officer about the disagreements."

**PRECONDITION.** The diagram exists and **displays no unmeasured number**. Per
`docs/metrics.json`, every metric is currently the literal string
`not yet measured`; the diagram may show the pipeline and nothing numeric until
a measurement run has happened. **Diagram not yet created.**

---

### B2 · 0:35–0:48 (13s)

**ON SCREEN.** Same diagram, with the Google Cloud surfaces highlighted in
sequence as each is named: Cloud Run Jobs → Firestore → Cloud Scheduler →
Vertex AI. Highlight only; no motion graphics.

**NARRATION (30 words, 2.3 w/s).**
> "Cloud Run Jobs ingest and reconcile. Firestore holds an append-only
> claim-event log — every graph is a fold over it. Cloud Scheduler runs it
> nightly. Gemini on Vertex does the reasoning."

**PRECONDITION — and a live one.** The sentence deliberately does **not** name
an agent framework. `google-adk` is declared in `pyproject.toml` but **no module
under `src/` imports it**; the runtime path is `google.genai` via
`src/baraza/llm.py`. `docs/framework-decision.md` and AGENTS.md both state that
a framework is named only where the code imports it.
*If and only if* an ADK import exists on the shipped path by record time, append:
> "— four agents on ADK, separated by what each is allowed to write."

Otherwise say nothing about the framework here and let the Devpost text carry the
accurate version. Do not read the pinned model IDs aloud in any shot:
`make verify-models` has not been run green, and until it has, no artifact in
this repository may state which model version shipped.

---

## C — Centrepiece: unedited live terminal (0:48–2:08)

**One take. One terminal. No cuts inside this section.** Font large enough to
read at 720p. Clear scrollback immediately before rolling, on camera.

### C1 · 0:48–1:05 (17s) — cold ingest

**ON SCREEN.** Terminal. Visible in order: `ls fixtures/corpus/`, then the
event-log count showing zero, then `make demo-agenda`. Output scrolls: documents
read, chunks, pre-filter keep/drop, claims extracted, contradictions detected
on write.

**NARRATION (36 words, 2.1 w/s — leave dead air while the log scrolls).**
> "Nothing here is primed. Empty log, a corpus of native files — a skewed PDF
> scan, headerless spreadsheets, a chat export, minutes. One command."
>
> *(pause, let it scroll)*
>
> "Chunk, pre-filter, extract, detect on write. No sweep — one bounded call per
> claim."

**PRECONDITION.** (1) `make demo-agenda` exits 0 — it currently does not. The CLI
exists and the target reaches its model layer, then exits 2 because
`fixtures/cassettes/` holds no recordings. (2) The run uses the recorded-cassette
client so it is reproducible offline and needs no credentials mid-take. (3) The
pre-filter mode visible in the output matches what `docs/metrics.json` records.
(4) **The wall-clock runtime of a cold ingest is `not yet measured`.** Time it
before assuming it fits in 17 seconds. If it overruns, shrink the corpus for the
take — do not cut the take, and do not present a shrunken corpus as the full one.

---

### C2 · 1:05–1:18 (13s) — the disputed ledger

**ON SCREEN.** Same terminal, continuing. The ledger prints: ranked rows, each
with the two conflicting claim IDs and their anchors.

**NARRATION (20 words, 1.5 w/s).**
> "This is the disputed ledger. Not errors — disagreements. Ranked by how much
> they'd cost the next person to get wrong."

**PRECONDITION.** Ledger rendering routes through the audience predicate, and at
least one row on screen is a genuinely planted manifest landmine. Do **not** say
a row count out loud; `contradictions_detected_total` is `not yet measured`. If
a count is visible in the output, that is fine — it came from the run. Saying a
number the run did not print is not.

---

### C3 · 1:18–1:31 (13s) — the agenda no human wrote

**ON SCREEN.** Continuing. The generated interview agenda prints. Each item
shows the contradiction it descends from.

**NARRATION (18 words, 1.4 w/s).**
> "And this is the interview agenda. No human wrote it. Every question traces
> to two records that disagree."

**PRECONDITION.** The agenda is generated in this same run, from the ledger
produced seconds earlier on screen. Nothing is loaded from a file authored by
hand. If any agenda item is downgraded because its underlying claims are
unreadable to this audience, that item renders as an open-ended prompt with no
quotes — that is correct behaviour, not a bug to hide from frame.

---

### C4 · 1:31–1:45 (14s) — the replay interview opens

**ON SCREEN.** Continuing. `make demo-interview REPLAY=1 PERSONA=<persona-id>`.
The first question streams token by token, with its citation. The canned persona
answer arrives on a timer.

**NARRATION (16 words, 1.1 w/s — deliberately sparse; let the stream be visible).**
> "Replay mode feeds a canned persona so this is reproducible. First question,
> cited. The officer answers."

**PRECONDITION.** (1) The replay harness works and the persona is one of the two
committed fixture personas. (2) Do **not** say "under a second to first token" —
`interview_first_token_ms_replay` is `not yet measured`, and a replayed timing is
in any case not a deployed measurement. If the stream is visibly fast, the viewer
can see that for themselves.

---

### C5 · 1:45–2:08 (23s) — **THE DIVERGENCE MOMENT**

**ON SCREEN.** The persona's answer lands. The agent's next turn renders the
divergence: `That differs from what the records say. <anchor> reads: "<quote>".
<rationale>` — **both citations visible in frame at the same time**: the
testimony turn and the conflicting corpus claim with its anchor. Do not scroll
away from it. Hold until the narration ends. The turn ID is visible on screen
(e.g. `t-14`) and is quoted by ID in the README and the Devpost text so a judge
can locate this exact exchange in the committed transcript.

**NARRATION (45 words, 2.0 w/s).**
> "Watch this line. The officer says one thing. The record says another. And the
> agent says so — in the moment, with both citations on screen. It doesn't call
> anyone a liar. It surfaces the divergence and asks which one is right. That is
> the product."

**PRECONDITION.** (1) The divergence fires deterministically for this persona on
this corpus — verify across at least three consecutive dry runs before the take,
because a centrepiece that fires probabilistically will fail on camera. (2) Both
anchors on screen resolve under `make verify-anchors`. (3) The conflicting claim
is readable by this audience — if it were not, the correct render is the redacted
placeholder, which is a fine thing to show but is a *different* shot and needs
different narration. (4) The turn ID visible here matches the ID cited in every
other artifact. **`make verify-anchors` does not yet exist.**

---

## D — Approval, successor, and the refusal (2:08–2:38)

### D1 · 2:08–2:19 (11s) — approval with the visibility choice

**ON SCREEN.** The approval surface. The answer is promoted to committed, and
the visibility selector is used **on camera** — the pointer moves from the
default `private` to `successor`. The emitted events are visible: the approval
event and the separate visibility event.

**NARRATION (22 words, 2.0 w/s).**
> "Approval is the only path to committed memory — and it carries the visibility
> choice. Default is private. Declining to choose never publishes."

**PRECONDITION.** The default really is `private` in the running build (it is —
`schema/visibility.py`), and the visibility decision is emitted as its own event
so it is auditable separately from the approval. Show the default state before
changing it; changing it off-camera loses the whole point of the shot.

---

### D2 · 2:19–2:28 (9s) — the successor query

**ON SCREEN.** Successor mode. A question is typed; the answer streams with an
inline citation on every sentence.

**NARRATION (19 words, 2.1 w/s).**
> "Now the successor. New officer, new question. Answered only from committed
> claims they're allowed to read, every sentence cited."

**PRECONDITION.** The claim answered here is one committed during the interview
minutes earlier in the same recording, so the loop visibly closes. A private
claim must be in the retrieval pool and must **not** appear — worth choosing the
question so this is true, even though it is invisible.

---

### D3 · 2:28–2:38 (10s) — **THE REFUSAL**

**ON SCREEN.** A second question, on something the committed record genuinely
does not cover. The refusal renders in full. Hold on it — do not cut early, the
length of the hold is what signals this is intended.

**NARRATION (23 words, 2.3 w/s).**
> "Now ask something the record doesn't cover. It refuses. A confident wrong
> answer about who can sign a cheque is worse than silence."

**PRECONDITION.** The refusal is deterministic for this question — verify across
three dry runs. The refusal text on screen is the one in
`src/baraza/successor/librarian.py`, unedited. Sell it as a designed property
with its own acceptance criterion; do not apologise for it, and do not let the
edit imply the system "couldn't" answer.

---

## E — Google Cloud proof frames (2:38–3:12)

**Mandatory per the rules.** Three real console frames, not slides. Screen
recording of the actual console, project name visible, no mock-ups. Blur or
scrub nothing except the project ID if the entrant chooses to.

### E1 · 2:38–2:50 (12s) — Cloud Run

**ON SCREEN.** Cloud Run console, services and jobs list, showing the ingest
Job, the reconcile Job, the interview service, and the successor service. The
`.run.app` URL is visible in frame; the cursor rests on it.

**NARRATION (23 words plus the spoken URL, 1.9 w/s before the URL — budget ~2s
to read the URL slowly enough that a judge can write it down).**
> "This is running on Google Cloud. Cloud Run: the ingest and reconcile Jobs,
> the interview and successor services. The live URL is
> `<READ THE VERIFIED URL — e.g. baraza-interview-XXXXXXXX-uc.a.run.app>`."

**PRECONDITION — currently unmet and blocking.** (1) Nothing is deployed. The
manifests, both Dockerfiles, the Firestore rules and `scripts/bootstrap_gcp.sh`
all exist and are syntax-clean; none has been run against a project. (2) The URL
read aloud must be the URL that was verified **logged out**, in a private
window, on the day of recording. Never read a URL that has not been loaded
logged-out. Never read a placeholder aloud and fix it in post. (3) If the deploy
does not happen, this shot cannot be replaced with a diagram — the rules require
Google Cloud proof, so an undeployed project is a submission-level failure, not
an editing problem.

---

### E2 · 2:50–3:00 (10s) — Vertex AI

**ON SCREEN.** Cloud Logging filtered to Vertex AI requests from the reconcile
Job, showing real request entries with timestamps. Expand one entry so the model
field is visible **on screen** — visible, not spoken.

**NARRATION (14 words, 1.4 w/s).**
> "Vertex AI logs — every reasoning call, Gemini only, model IDs pinned in one
> module."

**PRECONDITION.** ⏳ **Requires real prior calls.** Logs only exist if the
deployed Jobs have actually run against Vertex. Do not read a model ID aloud
(see B2). Do not state a call count, a token count, or a cost — none is measured.

---

### E3 · 3:00–3:12 (12s) — Cloud Scheduler

**ON SCREEN.** Cloud Scheduler execution history for the nightly reconcile
trigger, scrolled so **multiple consecutive nightly runs** are visible with their
dates. If the stub-to-real replacement date is identifiable in the history, put
the cursor on that row.

**NARRATION (25 words, 2.1 w/s).**
> "And Cloud Scheduler. These are nightly reconcile runs — the agent working with
> nobody watching. Scheduled runs, labelled as scheduled; I don't count them as
> traffic."

**PRECONDITION.** ⏳ **REAL ELAPSED TIME — cannot be manufactured.** BAR-410
requires **≥10 nightly runs** in the execution history before recording, which
requires the stub Job + Scheduler (BAR-021) to have been live for at least ten
nights. Neither exists yet. Count the visible rows on the frame and say a number
only if you are reading it off the screen; otherwise say "nightly runs" and let
the history speak. `scheduler_nightly_runs_completed` is `not yet measured`.

---

## F — The differential ledger (3:12–3:38)

### F1 · 3:12–3:25 (13s)

**ON SCREEN.** Two ledger snapshot files side by side, their `taken_at` dates
visibly different and their `scheduled: true` flags visible. Then the document
that landed between them, highlighted in the corpus listing.

**NARRATION (17 words, 1.3 w/s).**
> "Two ledger snapshots, two different nights. Between them, a document landed
> that didn't exist on night one."

**PRECONDITION.** ⏳ **REAL ELAPSED TIME.** Per BAR-323 the choreography is
night 1 → artifact drop → night 2 → diff, and it cannot be compressed
retroactively. Both snapshots must carry `scheduled: true`; a snapshot taken by
hand during a demo is never presented as autonomy evidence. The dates on screen
must be different calendar days, and the viewer must be able to read them.

---

### F2 · 3:25–3:38 (13s)

**ON SCREEN.** The computed diff: contradictions added, contradictions retracted
because the new document settled them, rank movements. Colour-coded, held still.

**NARRATION (23 words, 1.8 w/s).**
> "The diff is what the agent found while nobody watched: contradictions added,
> contradictions retracted because the new document settled them, rankings that
> moved."

**PRECONDITION.** ⏳ **REAL ELAPSED TIME.** The diff is computed by
`baraza.reconcile.differential` from the two committed snapshots, on camera or
from committed files a judge can open. Say no totals aloud — read them off the
screen or omit them.

---

## G — Close (3:38–3:50)

### G1 · 3:38–3:50 (12s)

**ON SCREEN.** Back to black. The opening line returns, then is replaced:
`Every May, thousands of organizations forget everything.` → `This September,
mine won't.` Then a single card: repo URL and hosted URL, both readable, held
for the last three seconds in silence.

**NARRATION (11 words, 0.9 w/s — slow, with a beat before the second line).**
> "Every May, thousands of organizations forget everything."
>
> *(beat)*
>
> "This September, mine won't."

**PRECONDITION.** Both URLs on the end card have been loaded **logged out** on
the day of recording. The end card is the last thing a judge sees; a dead link
there is worse than no card.

---

## Shots that require real elapsed time

These cannot be produced on recording day and gate the recording date itself:

| Shot | What must have already happened | Earliest possible |
|---|---|---|
| E3 — Scheduler history | ≥10 nightly runs of the reconcile Job (BAR-021 → BAR-410) | 10 nights after the stub Job + Scheduler go live. **Not yet deployed.** |
| E2 — Vertex logs | Real deployed calls, retained in Cloud Logging | After first deployed run |
| F1 — two snapshots | Night 1 run → artifact drop → night 2 run (BAR-323) | 2 nights after the first scheduled run |
| F2 — the diff | Both snapshots committed and `scheduled: true` | Same |

Everything else in the script is recordable in one sitting **once** the offline
demo path exits 0.

---

## What must NOT be claimed

Every entry below is a number or assertion that is **not measured** as of this
writing. `docs/metrics.json` carries the literal string `not yet measured` for
all of them. None may be spoken, captioned, overlaid, or written into a frame.

**Counts and rates — all `not yet measured`:**

- number of documents, chunks, or claims ingested
- number of claims committed
- number of contradictions detected, or contradiction precision
- how many planted manifest landmines were found
- agenda items generated, or agenda items retired after an interview
- pre-filter survival rate, and which pre-filter mode ran
- entity resolution precision or recall (the ≥83% scorecard is a **gate
  threshold**, not a result — never state it as an achieved number)
- claim embedding count, or top-k scan time
- number of nightly Scheduler runs (read it off the console frame or say nothing)

**Timings — all `not yet measured`, and additionally governed by provenance:**

- first-token latency on the interview path. A replayed cassette timing is a
  *replayed* measurement and an in-process timing is never reported as a deployed
  one, so even once measured, the phrasing must carry its provenance.
- ingest wall-clock, reconcile wall-clock, any per-call latency

**Assertions that are not yet backed by the code:**

- **"Built on ADK" / "four agents on ADK."** `google-adk` is a declared
  dependency; nothing under `src/` imports it. Until an import exists on the
  shipped path, the framework may not be named — in the video, the Devpost text,
  or the diagram.
- **Any pinned model ID, spoken or captioned.** `make verify-models` has not run
  green. A pinned literal nobody checked is a plausible value where a verified
  one belongs.
- **Any claim about the deployed system.** Nothing is deployed. No uptime, no
  region, no scale, no cost.
- **Antigravity.** Not claimed, not mentioned. The supporting finding is a
  placeholder in `docs/antigravity/decision.md` and a remembered paraphrase of
  evidence is not evidence.
- **"Kill-survival" / "resumes at the same turn."** The rig is not built; the
  resumed turn index is `not yet measured`. Do not demonstrate or assert it.
- **Adaptation.** Mean follow-up depth per persona is `not yet measured` and the
  in-session change turn ID is unassigned. The video may show the interviewer
  asking a follow-up; it may not state that adaptation was measured, and it may
  not cite a turn ID that does not exist in a committed transcript.
- **Anything about real organizations or real people.** The corpus is synthetic.
  No real entity appears, and no real entity is characterised as having lost
  records or mishandled anything.
- **Scheduled runs as organic activity.** If any traffic or usage figure ever
  appears on screen, Scheduler runs are labelled as scheduled and excluded.

**The rule for record day:** if a number is not visible on screen because a
command just printed it, it does not get said. Reading a number off a live
terminal is evidence. Saying one from memory is the defect class this project
exists to avoid.

---

## Pre-record checklist

- [ ] `make gate` green *(agent-runnable once the scripts exist)*
- [ ] `make demo` green on a clean clone, offline *(agent-runnable)*
- [ ] Divergence shot fires 3/3 dry runs *(agent-runnable)*
- [ ] Refusal shot fires 3/3 dry runs *(agent-runnable)*
- [ ] Every visible string in the corpus frames is synthetic *(human review)*
- [ ] Hosted URL loaded in a logged-out private window, today *(human-only)*
- [ ] Console frames captured with the real project *(human-only)*
- [ ] Scheduler history shows ≥10 nightly runs *(human-only; time-gated)*
- [ ] Final cut duration ≤ 4:00, verified in the editor's timeline *(human-only)*
- [ ] Uploaded public, not unlisted-only if the rules require public *(human-only —
      confirm against the live rules page)*
