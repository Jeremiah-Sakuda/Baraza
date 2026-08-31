# Video script: Baraza, memory with due process

**Hard cap 4:00. This script is budgeted to 3:45**, leaving slack for breath.
Verify the final duration in the editor timeline, not by estimate.

**The whole video happens inside the product.** Every frame is one of Baraza's
own web pages. There is no console hopping, no diagram tab, and no editor
window. The Google Cloud proof requirement is satisfied in-product: the
official rules list "URL of .run" among the accepted forms of proof, the
address bar stays visible on the public pages, and the record page's counters
are live queries against Firestore that name Cloud Scheduler on screen. If you
want a stronger proof beat anyway, Appendix C is a single optional ten-second
console insert, and it is the only out-of-product moment in this document.

**Recording rules:**

- Shot 3 is one unedited take. If the model misbehaves, keep rolling. The
  fallback lines below still score.
- Every visible string is synthetic or your own. Freeze and read each frame
  before locking the cut.
- No unmeasured number is spoken or captioned. Appendix B is the checklist.
- Narration is verbatim. Each line was written to be said out loud. If a line
  fights your voice, cut words from it rather than adding any.

---

## The two windows

Set these up before recording and leave them alone.

**Window 1, the owner console.** Run the proxy in a terminal, then close or
hide the terminal. Only the browser is ever on screen.

```bash
gcloud run services proxy baraza-interview --region=us-central1 --project=baraza-2026 --port=8080
```

Tabs, in order: `http://localhost:8080/` (session index, which takes you to
the session view when you open a session) and `http://localhost:8080/approvals`.

**Window 2, the public product.** Base URL
`https://baraza-successor-tlaymplktq-uc.a.run.app`, address bar visible.
Tabs, in order: `/dossier`, `/doctrine`, `/agenda`, `/` (the record page).

The demo moves left to right through those tabs and never anywhere else.

**The one rule that keeps Shot 4 honest:** the public dossier shows only
beliefs you chose to publish in the approval queue. Everything else appears as
a withheld count. So when you ratify the demo beliefs in Shot 3, set their
visibility to public. That is the visibility choice doing its job on camera.

---

## Preconditions

- **[verified]** The product is live. On 2026-08-31 the public page returned
  200 logged out, a session opened with a six-item agenda built from real
  detected contradictions, and a live turn produced a judgment-shaped belief
  with its condition intact, quote and turn anchor included.
- **[verified]** The centrepiece needs no local credentials. The deployed
  services carry their own, and the session view at localhost:8080 is already
  talking to live Gemini through Vertex.
- **[verified]** The nightly chain is green: Scheduler fires, the trigger
  service starts the job, the job writes honestly labelled events. Runs accrue
  nightly from 2026-08-31.
- **[you]** Run at least one real session before recording day, ideally a few
  across days. The dossier, the agenda, and the session-length beat all get
  heavier with every genuine session in the log.
- **[you]** Rehearse the full take once, including the contradiction beat.

---

## Shot 1: the file it keeps on you (0:00 to 0:30)

**ON SCREEN:** Window 2, the `/dossier` page. Scroll slowly through real
beliefs: rule text, verbatim quote, turn anchor, timestamp. Let the withheld
count be visible.

**NARRATION:**

> "Every AI product is adding memory right now, and almost every one of them is
> a black box. It paraphrases you. It cannot tell you where a belief came from,
> and you cannot correct it. This page is Baraza's answer. It is the file the
> agent keeps on me. Every belief is stored with my exact words and the moment
> I said them, and nothing on this page acted on my behalf until I approved it."

---

## Shot 2: the record that cannot be rewritten (0:30 to 0:50)

**ON SCREEN:** Window 2, the `/` record page. The live counters are the frame:
published records, events folded, scheduled reconcile runs. Hover the caption
text that says counts are live queries over the append-only log.

**NARRATION:**

> "Underneath it is an append-only record on Google Cloud. Firestore holds the
> log, and its deployed rules reject edits and deletes outright. Fixing a
> mistake means adding a new event, never rewriting an old one. These counters
> are live queries against that log, and you are looking at the app running at
> its cloud address right now."

*(Point the cursor at the address bar for a beat. The .run.app URL is the
Google Cloud proof, and you will read it aloud in Shot 6.)*

---

## Shot 3: the centrepiece, one unedited take (0:50 to 2:15)

**ON SCREEN:** Window 1. Start at the session index, open a session, land in
the session view. Chat on the left, claim panel and agenda rail on the right.
The sequence:

1. (0:50) Open the session. The agent speaks first: a numbered agenda, each
   item citing a real disagreement in the record.
2. (1:00) Work the first item, then state a rule in plain words: "Never state
   a number in a submission document unless it traces to a metrics entry."
3. (1:10) The belief lands in the claim panel: your exact sentence, a turn
   anchor, status proposed.
4. (1:20) Keep working, then type the colliding instruction: "Just put a rough
   number in for now and we will fix it later."
5. (1:30) The divergence card fires with both quotes and both anchors. The
   agent asks which one governs and will not silently keep the newer one.
6. (1:45) Resolve it by splitting into a conditional: submitted artifacts must
   trace to metrics, drafts may carry a marked placeholder.
7. (1:55) Switch to the approvals tab. Ratify the beliefs. Set the demo
   beliefs to public. Nothing acts until this click.
8. (2:05) Open the `/doctrine` tab in Window 2. The new rule is there, and it
   cites the claim and the quote that created it.

**NARRATION, paced over the take:**

> "This is live and unedited. The agent opens the session, not me, and every
> question on its agenda exists because two records genuinely disagree. I give
> it a rule, and it stores my sentence, not a summary of it. A minute later I
> contradict myself, and it catches me. Both of my statements are on screen
> with their timestamps, and it asks me which one governs. I resolve it by
> splitting the rule in two, one for drafts and one for submissions. Then I
> approve it, because no belief acts on my behalf until I sign it. And here it
> is in the doctrine, the working policy, where every rule cites the exact
> sentence that created it."

**FALLBACK, keep rolling:** if extraction misses the rule or the card does not
fire, the agent asks a clarifying question instead. Say this, honestly:

> "It did not catch that one, so it asks. A question here only exists when my
> own statements collide or a rule is too vague to compile."

---

## Shot 4: reject and rerun (2:15 to 2:45)

**ON SCREEN:** Window 2, the `/dossier` tab. Click reject on one of the
published demo beliefs. Return to the session view and rerun the same drafting
request. Open `/doctrine` and show the diff panel naming the retracted claim.

**NARRATION:**

> "The correction path is just as visible. I reject a belief on the dossier
> page, and the retraction is itself a new event in the log. I run the same
> request again, and the output changes. The doctrine diff names the rule that
> changed and the claim of mine it came from. Same doctrine, every rule cited.
> Compiling my beliefs into policy replays byte for byte. What the model does
> with that policy is honest work, and we measure it rather than promise it."

---

## Shot 5: it leads (2:45 to 3:15)

**ON SCREEN:** Window 2, the `/agenda` tab, then back to the record page
counters. If you have two sessions across days, show the earlier session's
agenda length next to today's shorter one in the session view.

**NARRATION:**

> "And it leads. Every night a scheduled job on Cloud Run reads the whole log,
> finds the open contradictions and the stale beliefs, and proposes the next
> session with a numbered agenda. Every scheduled run is labelled as scheduled
> in the record, so automation never gets counted as real activity. When an
> item is resolved it retires itself, which means the next session is shorter
> than the last. It asks, I answer, and it stops asking."

---

## Shot 6: where it lives (3:15 to 3:40)

**ON SCREEN:** Window 2, the record page. Click into the address bar so the
full URL is highlighted and legible.

**NARRATION:**

> "Everything you just watched is running on Google Cloud. Cloud Run serves
> the app and the nightly jobs, Firestore holds the append-only record, Cloud
> Scheduler starts the loop, and Vertex AI serves Gemini. You can open it
> yourself right now at baraza dash successor, and the address on screen is
> the one on the submission form."

---

## Shot 7: close (3:40 to 3:45)

**ON SCREEN:** The `/dossier` page, held. One caption line: *Baraza. Memory
with due process.*

**NARRATION:**

> "Adaptation with due process. Open the file it keeps on you."

---

## On-screen captions

One small lower-third caption per beat, in the category's own words, so a
judge with the rubric open can tick each phrase without inferring anything.

| Beat | Caption |
|---|---|
| Shot 3, claim panel | takes notes: your exact words, anchored |
| Shot 3, divergence card | asks clarifying questions when your statements collide |
| Shot 3, agenda rail | guides step by step, items retire themselves |
| Shot 3, approvals | captures feedback: nothing acts unratified |
| Shot 4, doctrine diff | adapts to your way of thinking, every rule cited |
| Shot 5 | leads the way: the agent opens the session |

---

## Timecode budget

| Shot | Start | End | Duration |
|---|---|---|---|
| 1 The file | 0:00 | 0:30 | 0:30 |
| 2 The record | 0:30 | 0:50 | 0:20 |
| 3 Centrepiece | 0:50 | 2:15 | 1:25 |
| 4 Reject and rerun | 2:15 | 2:45 | 0:30 |
| 5 It leads | 2:45 | 3:15 | 0:30 |
| 6 Where it lives | 3:15 | 3:40 | 0:25 |
| 7 Close | 3:40 | 3:45 | 0:05 |
| **Total** | | | **3:45** |

---

## Appendix A: judge participation variant (live judging only)

If a judge can take the keyboard, hand it over inside Shot 3 and invite an
instruction of their choosing. If it collides with a committed belief from a
prior day, the divergence card fires on an input nobody on the team controlled,
and the belief's timestamp predates the demo in a log that rejects edits. If
it does not collide, the belief lands in the claim panel as their exact words,
which still scores. Never seed this. The whole value of the beat is that it
cannot be staged.

## Appendix B: what must not be claimed

Freeze-frame checklist before locking the cut:

- No number that docs/metrics.json lists as not yet measured is spoken or
  shown as a measurement.
- The nightly run count is whatever the record page shows, never more. Runs
  accrue from 2026-08-31 and the earlier failed attempts are part of the
  honest history, with the postmortem in the repo.
- Never say that replaying produces the same behavior. Doctrine compilation
  replays byte for byte. Model behavior does not, and the script's wording,
  same doctrine every rule cited, is the ceiling of the claim.
- No line-level causality claims about outputs. The doctrine diff names the
  rule and its source claim. It does not attribute individual output lines.
- No third-party product, logo, or trademark appears in any frame.

## Appendix C: optional console insert

If you want proof stronger than the .run.app address and the live counters,
record one ten-second insert after the main take: the Cloud Run service list
for project baraza-2026, showing the services and the two jobs. Place it
inside Shot 6. This is the only out-of-product footage in the video, and the
video passes the rules without it.
