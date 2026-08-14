# Devpost submission text — Baraza

> **How to use this file.** The headings below map to Devpost's fixed submission
> fields. Devpost phrases them in the plural ("How we built it"); this is an
> individual entry, so the prose inside is first person singular. Paste each
> section into its field.
>
> **Every bracketed `<…>` token is a placeholder that must be replaced with a
> real, verified value before submitting.** A placeholder that ships is worse
> than a blank field.
>
> **Numbers.** The literal string `not yet measured` appears wherever a number
> would go and none has been produced. That is deliberate and it is the honest
> state of the project as this text is written. Each one is replaced only by a
> value that came out of a run, carrying its run ID — never by an estimate.

---

## Category

**The Collaborative Partner.**

---

## Inspiration

Every May, thousands of student organizations forget everything they know. The
treasurer graduates. The person who knew which line item the conference fee
actually comes out of graduates. What gets handed over is a shared drive with
four folders named "final", a constitution that was scanned crooked years ago
and has not been read since, and three years of group chat.

The incoming officer asks the only question that matters — who can actually sign
a cheque — and there is no one left who knows. It is not that the information was
never written down. It is that the written record disagrees with itself, and the
only people who could have reconciled it have left.

Every existing answer to this points the wrong way. Knowledge bases assume
somebody will maintain them. Exit interviews assume somebody knows what to ask.
Both assume the outgoing officer has time and the incoming one has context, and
in May neither is true.

So the question I built toward was not "how do we store what they know" but
**"how do we find out what nobody realised was in dispute, before the person who
could settle it walks out?"**

## What it does

Baraza reads years of an organization's mess — chat exports, a skew-scanned
constitution, headerless budget spreadsheets, meeting minutes — and asks the
corpus what it disagrees with.

Overnight and unattended, it produces a ranked ledger of contradictions and an
interview agenda **no human wrote**. Then it conducts the exit interview:
citation-grounded questions, clarifying follow-ups that target what is missing
rather than restating what was said, and the moment that is the actual product —
**holding a departing officer's testimony against the documentary record and
surfacing the divergence in the moment, with both citations on screen.**

It does not call anyone a liar. A divergence between memory and record is a
question, not an accusation, and the interviewer is built to treat it that way.

Approved answers become committed memory carrying an explicit visibility choice.
The agent retires its own resolved questions — a resolved contradiction leaves
the ledger and every future agenda permanently — so the next interview is shorter
than the last. And the successor, months later, gets an answer from the committed
record with a citation attached, **or gets a refusal.** The refusal is a designed
property with its own acceptance criterion. A successor cannot tell a remembered
fact from a fluent guess, and a fluent guess about who can sign a cheque is worse
than silence. Silence is recoverable: they go and ask someone.

## How I built it

**An append-only claim-event log, and a graph that is only ever a fold over it.**
There is no mutable graph store. Every rendered graph state is computed by
folding the event log; Firestore rules reject update and delete. Fixing bad data
means appending a superseding event, never editing one. If a graph looks wrong,
the log is the truth and the fold is the bug.

**Contradiction detection is on-write and blocked, not a sweep.** A decade of an
organization's records is on the order of a few thousand claims, and an all-pairs
sweep is millions of comparisons — at one model call per comparison, that is not
a system, it is a bill. Instead: a claim is asserted; retrieve only claims
sharing its blocking key (subject entity ∪ object entities ∪ predicate hint,
with alias edges resolved at query time); temporally gate that block on epoch
interval overlap, which removes the single largest source of false positives —
two claims about consecutive fiscal years cannot contradict each other; cap the
survivors at 20; make **one** bounded call. One call per claim written, not per
pair. There is no vector database: claims are embedded, the corpus is not, and
brute-force top-k over a few thousand in-memory vectors at this cardinality does
not deserve infrastructure.

**The visibility boundary is structural, not conventional.** This is the
architectural decision I would defend hardest. The first design had the claim's
quote as an ordinary attribute with a `readable_by(claim, audience)` call
expected at each read site — a boundary held by discipline. The requirement says
it must hold under carelessness. So the text now lives behind
`quote_for(audience)`, and code that reaches for the raw attribute raises
`AttributeError` at the access site rather than returning private testimony to
the wrong reader. `readable_by` is defined exactly once. A compliance script
fails the build if the protected field is referenced anywhere outside the schema
package. The boundary is enforced by the type system and a lint, not by the
author remembering.

The reconciler is permitted to **count** a claim the current audience cannot read
toward a contradiction's existence, and never permitted to render its text into a
question for that audience. Those are two different operations on purpose. An
agenda item whose underlying claims are unreadable is *downgraded* to an
open-ended prompt with no quotes attached — not dropped — because dropping it
would let the boundary silently shrink the agenda and make the visibility choice
look free when it is not.

**Every temporal comparison is integer epoch millis.** ISO-8601 strings are a
serialization format and are never a comparison key. This is a ported defect
class, not a style preference — in a sibling project an ISO-string sort inside a
resolver allowed a revoked grant to remain active under mixed UTC offsets while
byte-stability tests stayed green. A property test permutes serialized UTC
offsets across the golden log and asserts the fold produces an identical graph.

**Google Cloud.** Cloud Run Jobs for ingestion and nightly reconciliation, Cloud
Run services for the interview and successor surfaces, Firestore for the
claim-event log and sessions, Cloud Scheduler for the unattended nightly pass,
and Gemini on Vertex AI for every reasoning call. Model identifiers live in
exactly one module and nowhere else; a compliance lint fails the build on a model
string literal anywhere else in the tree.

**The offline demo runs on recorded cassettes, not fabricated responses.** A
cassette is a recording of a real Vertex call, carrying its model ID, run ID and
date. If a cassette is missing for a prompt, the offline client raises rather
than inventing a response or silently falling through to a stub. A number derived
from a cassette replay is a *replayed* measurement and says so wherever it
appears.

## Challenges I ran into

**The requirements document arrived incomplete, and the honest response was to
say so.** The authoritative PRD was recovered only in part; roughly 35
requirement IDs exist in the tree as identifiers with no acceptance criteria, and
the recovery note explicitly forbids reconstructing them from memory. I built the
substrate anyway — none of it depends on the unrecovered sections — but made
`make compliance` exit **2** ("the audit could not run") as distinct from exit
**1** ("the audit found problems"), so the gap reads as a gap rather than as a
pass. A green gate that quietly skipped its main check is exactly the failure
this project keeps naming.

**A lint nobody has seen fail is a lint that might not work.** I verified all
four invariant checks by planting violations — a model-ID literal, a protected
field access, an ISO-string sort — running the audit, and confirming each was
reported with a clickable `file:line`. The first version of the model-pin regex
false-positived on the word "Gemini" opening a docstring; requiring a version
suffix fixed it. Worth recording, because the failure mode of an over-broad lint
is that someone adds an allowlist entry and it quietly stops covering the real
case.

**The obvious illustration of the temporal bug is wrong.** The intuitive example
— `09:00-05:00` versus `08:00Z` — does not actually diverge: string order and
instant order agree, and a test built on it passes for the wrong reason. A pair
that genuinely diverges has to cross a date boundary. That pair is what the
corpus plants and what the property test names.

**Evidence of autonomy only accumulates in real time.** The differential ledger —
what the agent found overnight while nobody watched — needs night 1, then a
document that did not exist during night 1 landing in the corpus, then night 2,
then the diff. A diff between two snapshots taken minutes apart proves nothing.
That is why a stub reconcile Job and its Scheduler trigger are supposed to go up
on day two rather than in the deploy phase: execution history is the cheapest
honest autonomy evidence available, and it cannot be compressed retroactively.

**Measuring adaptation without grading my own homework.** A metric computed by
the same codebase over its own configured personas is one step away from
displaying a hardcoded literal as a real count. So the application does not
compute the published metric. It emits labelled transcripts, and a standalone
scorer with no imports from the application package computes mean follow-up depth
from the committed raw transcripts — runnable by a judge, reproducible to the
digit.

## Accomplishments that I'm proud of

**The boundary that fails closed by construction.** Not "we remember to check
permissions" — the check is unavoidable because the data is unreachable without
it, and the build fails if anyone routes around it.

**Refusing to write a plausible number.** Every metric in `docs/metrics.json` is
currently the literal string `not yet measured`, and the compliance script fails
the build on any entry that is neither a measured value with a run ID and date
nor that exact string. There are no placeholder estimates anywhere in this
project, including in this description.

**A closed loop rather than a demo.** A resolved contradiction leaves the ledger
and every future agenda as a consequence of approval, not as a bookkeeping step
someone has to remember. The next interview is shorter because the system
retired its own questions.

**A refusal I did not engineer away.** The easiest way to make a demo look better
is to let the model answer anyway. Keeping the refusal — and putting it in the
video — is the decision I would make again.

## What I learned

**Invariants that depend on discipline decay; invariants that depend on types and
lints do not.** Every constraint I moved from "remember to do this" into "the
build fails otherwise" stayed intact; the ones I left as conventions are the ones
I kept catching myself about to break.

**Deterministic error beats plausible output, everywhere.** The offline client
that raises on a cassette miss, the temporal normalizer that raises on an
ambiguous instant rather than guessing, the model resolver that raises on an
unknown role rather than falling back to a cheaper model — each one turns a
silent correctness bug into a loud one.

**Recording what you did not do is worth more than it costs.** The absent PRD; a
prior decision whose supporting document I could not locate, and therefore did
not summarize from memory, because a remembered paraphrase of evidence is not
evidence; the framework claim that is not yet backed by an import. Writing these
down as open items made every remaining claim more credible, not less.

**"Not yet measured" is a real answer.** It is uncomfortable to write in a
submission and it is the only thing that makes the measured numbers mean
anything.

## What's next for Baraza

Honest ordering, most-blocking first:

1. **Merge the recovered PRD** so `make compliance` can run its actual audit
   instead of exiting 2, and so the ~35 requirement IDs currently satisfied
   against inference are satisfied against a contract.
2. **Back the agent-framework claim with an import**, or state plainly that the
   runtime is the GenAI SDK on Vertex. A framework name never appears in the
   compliance matrix unless the code uses it.
3. **Run `make verify-models`** so a document in this repository may finally
   state which model version shipped.
4. **Deploy and accumulate Scheduler history**, so the autonomy claim rests on
   execution rows rather than on architecture.
5. **Measure everything currently marked `not yet measured`** — the pre-filter
   survival rate in a supervised session with the endpoint scripted up and down,
   the entity scorecard as a rate, the adaptation metric from committed replay
   transcripts.
6. **The kill-survival rig**: prove session state survives a mid-turn SIGKILL and
   resumes at the same turn, because "state survives" is proven by a kill, not by
   liveness.

Explicitly **not** next, and recorded as negative decisions: no vector database,
no ML entity matcher, no destructive identity merges, no voice, no multi-org
features, no enterprise deployment claims.

---

## Built With

`python` · `google-cloud-vertex-ai` · `google-gen-ai-sdk` · `gemini` · `gemma` ·
`google-cloud-run` · `google-cloud-firestore` · `google-cloud-scheduler` ·
`google-cloud-logging` · `opentelemetry` · `fastapi` · `uvicorn` · `pydantic` ·
`pytest` · `hypothesis` · `pypdf` · `pdfplumber` · `openpyxl` · `python-docx`

> **Before submitting:** add `google-adk` to this list **only if** a module under
> `src/` imports it. It is currently a declared dependency that nothing imports,
> and the repository's own rule is that a framework is named only where the code
> uses it. Do **not** list specific pinned model version strings here until
> `make verify-models` has run green.

---

## Category fit — The Collaborative Partner

**Why this category.** Baraza's core loop is a working relationship between an
agent and a person under time pressure, where each holds something the other
cannot get alone. The agent holds the documentary record — thousands of claims
across a decade of formats no person will re-read. The departing officer holds
the reasons, which were never written down anywhere. Neither can produce the
handover alone.

The partnership shows up in four concrete places:

1. **The agent sets the agenda, the human sets the truth.** Baraza decides what
   is worth asking by finding what the corpus disagrees with. It does not decide
   what is true — a contradiction is closed only by testimony plus an explicit
   approval.
2. **The divergence moment is a collaboration, not a correction.** When testimony
   conflicts with the record, the agent surfaces both citations and asks which is
   right. It never adjudicates a person against a document on its own authority.
3. **Approval is the only path to committed memory**, and it carries the
   visibility choice. The extractor cannot write `committed`; the reconciler
   cannot write `committed`; in the deployed design neither service account holds
   the IAM permission to. The human is not a rubber stamp in the loop — they are
   the only writer of the tier that matters.
4. **The relationship compounds.** Every approved answer retires a question
   permanently, so the agent asks for less of the person's time each cycle. The
   collaboration gets cheaper for the human, which is the only kind of
   collaboration a volunteer officer will actually sustain.

And the refusal is the partnership's honesty condition: an agent that answers
when it does not know is not a partner, it is a liability with a friendly tone.

---

## Also engineered for — Continuous Action Engine

**Unattended nightly execution.** The reconcile pass runs as a Cloud Run Job on a
Cloud Scheduler trigger with no human present. What makes this evidence rather
than architecture is the **differential ledger**: two ledger snapshots from two
genuinely different nights, with a document landing in between that did not exist
during the first pass, and a computed diff showing exactly what the agent found
while nobody watched — contradictions added, contradictions retracted because the
new document settled them, rankings that moved. Snapshots carry a `scheduled`
flag; a snapshot taken by hand during a demo is never presented as autonomy
evidence, and scheduled runs are labelled as scheduled in any accounting rather
than counted as organic activity.

The build process itself ran unattended under a written execution profile: each
phase exit is a set of commands and assertions rather than a judgment call, and a
session that cannot mechanically verify a gate writes a `STOPPED.md` naming the
failing gate, the exact error, the state of the working tree, and what was not
attempted — then halts. Four failure modes are individually prohibited: widen a
scope to unblock, hardcode a number where a measured one belongs, report an
in-process timing as a deployed measurement, weaken the rule the gate was
testing.

**BYOF — the personal friction.** This is my own friction, not a market
abstraction. I have watched the May handover fail from inside it. The system is
built for one organization's specific mess, and the demo corpus is a synthetic
reconstruction of exactly that mess — a crooked scan, spreadsheets with no
headers, a chat export where the real decisions live, minutes that contradict the
chat.

**Current status, stated plainly:** `scheduler_nightly_runs_completed` is
`not yet measured` and nothing is deployed as this text is written. The
requirement I am building toward is ≥10 nightly runs visible in execution history
before recording day, which is arithmetic, not hope — but it is not yet
satisfied.

---

## Also engineered for — Evolving Knowledge Engine

**Messy, unstructured, multimodal, and genuinely so.** The ingestion path reads
four native formats with four different failure modes: a **skew-scanned PDF**
constitution where the text layer is unreliable and a layout-aware fallback is
needed; **headerless spreadsheets** where the column meaning has to be inferred
from content; a **group-chat export** that is mostly scheduling noise and where
timestamps arrive as bare epoch integers in a non-UTC context; and **meeting
minutes** that reference decisions the chat records differently. A relevance
pre-filter runs before any expensive extraction call so the reasoning model never
sees the majority of a chat export that is logistics.

**Synthesis, then mutation.** Claims are extracted with mandatory citations —
`quote` is required, anchors must resolve to registered source locations, and an
unresolvable anchor is a stop condition rather than a warning. Contradictions are
detected on write, blocked and temporally gated. The knowledge then **mutates**
in three distinct ways, all of which are events in the log rather than edits:

- **Testimony supersedes record.** An interview answer, once approved, enters the
  same claim log as the corpus claims and can win against them.
- **Resolution retracts.** A resolved contradiction leaves the ledger and every
  future agenda permanently; a rejected claim leaves the retrieval pool entirely.
- **New documents rewrite the dispute set overnight.** The differential ledger is
  literally the record of the knowledge base mutating without supervision.

Nothing is ever edited in place. The graph is a fold over an append-only log, so
every state the knowledge base has ever been in is reconstructible, and a
correction is a new event rather than a lost one.

---

## Also engineered for — Multi-Agent Nexus

Four agents, with separation of concerns **enforced** rather than described:

| Agent | Reads | Writes | Cannot |
|---|---|---|---|
| **Extractor** | Corpus chunks | `pending` claims with mandatory citations | Write `committed`. Not by convention — the deployed service account does not hold the permission. |
| **Reconciler** | The claim pool, including claims the current audience cannot read | Contradiction events, ledger, agenda | Render an unreadable claim's text into a question. It may *count* it; `render_for` redacts per audience. |
| **Interviewer** | The agenda and the readable record | Session turns, testimony claims | Promote anything. It asks; it never commits. |
| **Librarian** (successor mode) | `committed` ∧ readable-by-successor only | Nothing | Answer uncited. It refuses instead, and the refusal has its own acceptance criterion. |

The separation is enforced at three levels, which is the part I would point a
judge at: **the type system** (protected text is unreachable without an
audience), **the build** (a compliance script fails on any access that routes
around the boundary, on a model literal outside the pin module, and on an
ISO-string comparison), and **IAM** (per-stage least-privilege service accounts,
where only the approval path can promote a claim to `committed`).

A separation of concerns that exists only in a diagram is a naming convention.
This one fails the build.

---

## Honesty statement — what is and is not measured

As this text is written:

- **Measured:** nothing. Every entry in `docs/metrics.json` is the literal string
  `not yet measured`. The compliance script enforces that shape, so this cannot
  drift quietly.
- **Verified mechanically:** the four invariant lints (visibility boundary, model
  pin location, temporal comparison, metrics provenance) run green, and each was
  confirmed by planting a violation and watching it fail with a `file:line`.
- **Not yet verified:** the BAR-007 PRD audit (the PRD is incomplete, so
  `make compliance` exits 2 rather than falsely passing); the pinned model IDs
  (`make verify-models` has not run); the agent-framework claim (declared as a
  dependency, not yet imported); the deployment (nothing is deployed);
  Scheduler execution history (does not yet exist).

Every number in the final submission traces to a query, a committed metrics
entry, or a script a judge can run. Where a number would go and none exists, this
document says `not yet measured` and means it.
