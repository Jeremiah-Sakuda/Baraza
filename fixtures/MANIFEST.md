# MANIFEST.md — every planted problem in the synthetic corpus

Eighteen landmines, `L-01` … `L-18`. Each one names the files it lives in, the
exact locators, what is wrong, and — the part that matters — **what the system is
expected to do about it**, including the four cases where the expected behaviour
is to do *nothing*.

Everything referenced here is fiction, generated from `fixtures/corpus/BIBLE.md`
by `make corpus`. No real person, student, member, company, or organization
appears in this corpus, and no real entity is depicted as a bad actor.

---

## How this file is kept honest

**Every ID here has a mechanical probe.** `scripts/verify_manifest.py` owns the
probes; this file owns the prose; the script asserts that the two ID sets are
**identical** and fails if they diverge. A manifest entry cannot quietly lose
its check, and a probe cannot exist for a landmine nobody wrote down.

**The misses are the output.** `make verify-manifest` prints
`found N of N planted problems` and then prints the miss list unconditionally —
including when it is empty, so that "no misses" is a statement the script made
rather than a section that failed to render. A script that only reported its
successes is the specific failure this target exists to prevent.

**Two phases, never conflated.**

| Phase | Question | Needs |
|---|---|---|
| **plant** | is the landmine actually in the artifacts on disk? | `fixtures/corpus/` |
| **behaviour** | did the system do the expected thing about it? | an event log |

`found N of N` counts **plants**. Behaviour is reported on its own line with its
own miss list, because a corpus that contains the trap and a system that handles
the trap are two different claims and merging them would let one hide behind the
other.

**Exit codes**, matching `scripts/compliance.py`'s convention:

| Code | Meaning |
|---|---|
| `0` | every plant present; every behaviour probe that could run, passed |
| `1` | a plant is missing, or a behaviour probe ran and failed |
| `2` | every plant present, but no event log exists, so behaviour could not be observed at all |

Exit 2 is not a pass. It is the honest state of the repository between
`make corpus` and the first ingest, and the script says so in words.

**Regenerate and re-check:**

```bash
make corpus            # deterministic; same BIBLE -> same bytes
make verify-manifest   # plants + behaviour
make verify-anchors    # every citation still resolves to real source text
```

---

## Locator grammar, so the anchors below are checkable by hand

| Format | Locator | Example |
|---|---|---|
| GroupMe | `msg:<created_at>` | `msg:1700001660` |
| XLSX | `<Sheet>!<Cell>` | `Sheet1!B3` |
| DOCX | `¶<n>`, `tbl<n>:r<m>` | `¶6`, `tbl1:r2` |
| PDF | `p.<page> ¶<n>` | `p.5 ¶4` |
| Markdown | `L<start>-L<end>` | `L12-L18` |

> **Known reader divergence, recorded rather than hidden.** `read_pdf` prefers
> pdfplumber and falls back to pypdf. Measured on the generated constitution:
> pypdf returns **33** units (it preserves the whitespace-only lines the
> generator writes, so `\n\s*\n` splits paragraphs), pdfplumber returns **7** —
> one unit per page. The `p.N` component is stable across both; the `¶n`
> component is not. Every probe in `verify_manifest.py` therefore locates
> planted PDF text **by content across a source's units**, never by a fixed `¶`
> ordinal, and `verify_anchors.py` diagnoses this case explicitly when a PDF
> anchor fails to resolve but its quote is present elsewhere in the same source.

---

## L-01 — the mixed-UTC-offset trap

**Files.**
`fixtures/corpus/chat/groupme-meridian-officers.json` — segment `seg-2026-may`,
field `segment_started_at_iso`
· `fixtures/corpus/interviews/prior-exit-interview-2026-05.json` — turn `t-2`,
field `ts`

**Problem.** The two ISO strings are

| | value | string order | instant |
|---|---|---|---|
| `a` | `2026-05-01T20:00:00-05:00` | first | `2026-05-02T01:00:00Z` |
| `b` | `2026-05-02T00:00:00Z` | second | `2026-05-02T00:00:00Z` |

`a < b` is **True** as text and **False** as an instant: `a` is one hour *later*
than `b` and still sorts before it. The export segment was captured in Central
Daylight Time, which is why the offset is there at all, and the GroupMe messages
themselves carry only bare epoch seconds — so the sortable-looking string and
the authoritative instant live in different places, which is exactly the
condition under which this defect class hides.

This is the pair verified in `docs/FINDINGS.md`. The intuitive illustration
(`09:00-05:00` vs `08:00Z`) does *not* diverge; a test built on it passes for the
wrong reason. A diverging pair must cross a date boundary.

**Expected behaviour.** Every comparison goes through
`baraza.schema.temporal.to_epoch_millis`. The fold orders `b` before `a`. No
instant derived from this corpus lands outside the corpus window
`[2016-01-01Z, 2027-01-01Z)`. `tests/property/test_fold_stability.py` permutes
serialized offsets across the golden log and asserts a byte-identical fold, and
names this landmine (BAR-309 AC).

**Probe.** *plant* — both strings present at their stated locations; the
divergence recomputed live (`a < b` as text is True, as epoch millis is False).
*behaviour* — every claim's `observed_at` inside the corpus window.

---

## L-02 — the FY-pair FALSE POSITIVE (must **not** be flagged)

**Files.**
`fixtures/corpus/minutes/minutes-2023-09-12.docx` — `¶6`
· `fixtures/corpus/minutes/minutes-2024-09-10.docx` — `¶6`

> ¶6, 2023-09-12: "The Treasurer for fiscal year 2023-24 is vell.ory, who holds
> signing authority on the operating account from 1 July 2023 through 30 June
> 2024."
>
> ¶6, 2024-09-10: "The Treasurer for fiscal year 2024-25 is kestrel9, who holds
> signing authority on the operating account from 1 July 2024 through 30 June
> 2025."

**Problem.** Same subject, same `predicate_hint`, different object. Structurally
identical to L-03. A detector blocked on subject ∪ predicate and nothing else
flags this pair, and every consecutive officer term in a decade of minutes
becomes a contradiction — which is how a ledger becomes noise nobody reads.

**Expected behaviour.** **Suppressed by the temporal gate.** The intervals are
`[2023-07-01, 2024-06-30]` and `[2024-07-01, 2025-06-30]`; `intervals_overlap`
on epoch values returns `False`, so BAR-320 never asks the model. It must stay
suppressed under permuted serialized offsets — the gate is arithmetic on
integers, not on text.

**Probe.** *plant* — both paragraphs present, both intervals parseable,
`intervals_overlap` returns `False` for the declared pair.
*behaviour* — **no** open contradiction exists whose two claims carry
non-overlapping validity intervals.

---

## L-03 — genuine signing-authority contradiction (constitution vs later minutes)

**Files.**
`fixtures/corpus/governing/constitution-2016-amended-2019.pdf` — Article VII
Section 3, page 5
· `fixtures/corpus/minutes/minutes-2021-11-09.docx` — `¶9`, `tbl1:r2`

> Constitution: "No disbursement in excess of two hundred fifty dollars ($250)
> shall issue without the signatures of both the President and the Treasurer."
>
> Minutes, 9 Nov 2021: "MOTION (the Treasurer): that the Treasurer be authorized
> to disburse up to one thousand dollars ($1,000) on a single signature." —
> carried 7-2-1.

**Problem.** Both are in force. The motion carried; the constitution was never
amended, and Article VIII Section 2 says in terms that no motion may have the
effect of amending it. The 2021 minutes even record the question being asked and
answered wrongly, with no copy of the constitution in the room. Both intervals
are open-ended, so they overlap completely and the temporal gate correctly
declines to save this one.

**Expected behaviour.** Detected on write, landed on the disputed ledger with a
rationale a human can audit, and promoted to the interview agenda — this is the
question the departing treasurer is asked, with both citations rendered.

**Probe.** *plant* — both texts present at their sources.
*behaviour* — at least one contradiction whose claim set spans source IDs
`constitution` and `minutes-2021-11-09`.

---

## L-04 — dues-amount contradiction across chat and spreadsheet

**Files.**
`fixtures/corpus/chat/groupme-meridian-officers.json` — `msg:1700001660`
· `fixtures/corpus/finance/budget-workbook.xlsx` — `Sheet1!B3`

> Chat, 14 Nov 2023: "dues are still 25 this semester, stop telling people 40"
>
> `Sheet1!B3` = `40`, in the row `dues income | 40 | 118 | 4720`, under the
> year marker `23-24` at `C1`.

**Problem.** For the same fiscal year, the chat says $25 per semester and the
workbook implies $40 across a full-year member count — a figure that was never
collected, because the raise was voted effective the spring semester only
(`minutes-2023-10-10.docx` `¶6`). No single document is wrong on its face and no
single document is complete.

**Expected behaviour.** Detected — the intervals overlap — and surfaced as an
agenda item. The correct resolution is *not* for the system to pick a winner: it
is to ask the officer who was there, and the October minutes are the evidence
that makes the question answerable.

**Probe.** *plant* — chat text present at `msg:1700001660`; `Sheet1!B3` reads
`40` with `dues income` as its row label.
*behaviour* — at least one contradiction whose claim set spans `gm-officers` and
`budget-workbook`.

---

## L-05 — entity aliasing trap: Treasurer ≠ Assistant Treasurer

**Files.**
`fixtures/corpus/governing/constitution-2016-amended-2019.pdf` — Article III
Section 4, page 3
· `fixtures/corpus/minutes/minutes-2023-09-12.docx` — `¶7`
· `fixtures/entities-gold.json` — the pair is listed under `distinct`

> Constitution Art. III §4: "The Assistant Treasurer … shall hold no independent
> authority to disburse funds of the Society and shall not be a signatory on any
> account."

**Problem.** The two role names differ by one token and by the entire question of
who may sign a cheque. Every string-similarity heuristic wants to merge them.

**Expected behaviour.** **Never merged.** `AliasPass._compare` rejects the pair
before any similarity rule runs, because exactly one side carries a
distinguishing modifier. No `sameAs` edge is proposed, so none can be confirmed.
The consequence of failing this is L-12: merged, the corpus reads as "the
treasurer signed for $600, which the 2021 motion allows", and a real finding
disappears.

**Probe.** *plant* — both texts present; the pair listed under `distinct` in the
gold file. *behaviour* — no `entity.alias_linked` event links a treasurer-like ID
to one carrying a distinguishing modifier (`assistant`, `deputy`, `vice`,
`acting`, `interim`, `former`, …).

---

## L-06 — low-confidence region in the scanned constitution

**File.** `fixtures/corpus/governing/constitution-2016-amended-2019.pdf` — page 7,
the clerk's insert.

> "M4rg|n4| n0te |n h4nd: "thresh0|d r4|sed t0 $?SO per m0t|0n 0f 9 N0V - see
> m|nutes" [4m0unt ||||eg|b|e - d0 n0t tr4nscr|be]"

**Problem.** A re-scan of a folded page. The marginal note refers to a raised
threshold and the amount is genuinely unreadable — `$?SO` could be $250, $750,
or nothing at all. It is the one place in the corpus where the *right* answer is
to decline.

**Measured.** `read_pdf`'s legibility proxy scores this unit at **0.798**, and it
is the only unit in the document below 0.90 under either PDF parser — next-worst
**0.957** under pypdf (33 units), **0.989** under pdfplumber (7 units). The
separation survives the reader divergence noted above because the degraded region
occupies a whole page, so it is never diluted by clean text in the same unit.
Every number here is printed by `make corpus` and re-measured by
`make verify-manifest`; none is typed into this file by hand. The proxy is a
character-class ratio, not an OCR engine's confidence, and is labelled as a proxy
everywhere it surfaces.

**Expected behaviour.** The unit is flagged, its confidence rides along on every
claim anchored there (`extra.unit_confidence`), and **no claim asserts the
illegible amount**. A guessed `$250` here would be indistinguishable from a
correct reading, which is precisely why it must not be produced.

**Probe.** *plant* — the degraded text present; exactly one unit below 0.90; that
unit contains the illegible-amount marker. *behaviour* — every claim anchored at
that unit carries `extra.unit_confidence < 0.90`, and no claim quotes the marker
as an amount.

---

## L-07 — epoch-unit trap: one message in milliseconds

**File.** `fixtures/corpus/chat/groupme-meridian-officers.json` —
`msg:1729021620000`

**Problem.** Forty-five messages carry ten-digit epoch **seconds**. One,
re-imported from an older archive export, carries thirteen-digit
**milliseconds** — a real artifact of re-exported chat archives. Read as
seconds, it lands in the year 56,760 and becomes the newest thing in the corpus,
which quietly makes it the most recent evidence about the lantern-series budget.

**Expected behaviour.** `to_epoch_millis` reads magnitudes at or above
10,000,000,000 as milliseconds and below it as seconds, so this resolves to
2024-10-15T19:47:00Z and sorts among its neighbours.

**Probe.** *plant* — exactly one message above the seconds ceiling; it normalizes
into October 2024. *behaviour* — any claim anchored there has `observed_at`
within a day of 2024-10-15T19:47:00Z.

---

## L-08 — offsetless ISO timestamp in a handover note

**File.** `fixtures/corpus/notes/handover-checklist-2026-05.md`

> "last officers meeting was 2026-04-14T19:30:00 - the minutes from that one are
> not in the folder yet, the secretary still has them"

**Problem.** A local time with no offset. It is ambiguous by construction and
there is no correct value to recover; the note's author was in Central Daylight
Time, but nothing in the corpus says so.

**Expected behaviour.** `to_epoch_millis` **raises** `TemporalError` rather than
guessing UTC. The extraction is rejected with a named reason
(`temporal-invalid`) and counted in the rejection summary. Silently reading it as
`2026-04-14T19:30:00Z` would be off by five hours and indistinguishable from
success.

**Probe.** *plant* — the string is present and `to_epoch_millis` raises on it.
*behaviour* — no claim in the log carries the guessed-UTC instant on any of
`observed_at`, `valid_from`, `valid_until`.

---

## L-09 — headerless-column decoy: `40` twice, for unrelated reasons

**File.** `fixtures/corpus/finance/budget-workbook.xlsx` — `Sheet1!B3` and
`Sheet1!B7`

| Cell | Row context | Meaning |
|---|---|---|
| `Sheet1!B3` | `dues income \| 40 \| 118 \| 4720` | dues rate per member per semester |
| `Sheet1!B7` | `chair rental \| 40 \| 4 \| 160` | chair replacement unit price |

**Problem.** The sheet has no header row anywhere — column B is a rate, C a
count, D a total, and the only way to know that is arithmetic and the label in
column A. A dues claim citing `B7` is **grounded** (the cell really does contain
`40`) and **wrong**. This is the failure `verify-anchors` structurally cannot
catch, and it is why `read_xlsx` attaches the whole row as context to every cell
unit.

**Expected behaviour.** Claims carry the row context in their cited text, so the
wrong citation is visible to a human reading the ledger. A dues claim anchored at
`Sheet1!B7` is a defect.

**Probe.** *plant* — both cells read `40` with different row labels.
*behaviour* — no claim whose `predicate_hint` mentions dues is anchored at
`Sheet1!B7`.

---

## L-10 — same human, two handles; different humans, similar handles

**File.** `fixtures/corpus/chat/groupme-meridian-officers.json` —
`msg:1722359700`, `msg:1724083320`, `msg:1727212440`
· `fixtures/entities-gold.json`

> "losing this account, phone died and i cannot get back in. new handle incoming"
> — `sablewick`, 30 Jul 2024
>
> "it is me, sablewick. still archivist. someone re-add me to the drive" —
> `sable.w`, 19 Aug 2024
>
> "welcome sablewood. note for everyone, sablewood and sable.w are two different
> people" — `kestrel9`, 24 Sep 2024

**Problem.** `sablewick` and `sable.w` are one person across an account change.
`sablewood` is a different person entirely, one character away. The evidence for
both facts is a passing remark in a group chat.

**Expected behaviour.** `sablewick ↔ sable.w` is a **true** `sameAs` pair;
`sablewick ↔ sablewood` must **never** be linked. Both are labelled in
`fixtures/entities-gold.json`, and the entity scorecard measures the rule-based
pass against them honestly — the true pair is *not* reachable by the current
normalization rules and is expected to score as a false negative until the
ambiguous-residue pass or a human confirms it. The gold file is written from the
corpus, not from what the matcher can currently do.

**Probe.** *plant* — the three messages present; the true pair under `same_as`
and the false pair under `distinct` in the gold file. *behaviour* — no alias edge
links `ent:sablewick` to `ent:sablewood`.

---

## L-11 — a paraphrase attributed to the wrong document

**Files.**
`fixtures/corpus/minutes/minutes-2023-10-10.docx` — `¶7`
· `fixtures/corpus/governing/constitution-2016-amended-2019.pdf` — page 5

> Minutes: "The Archivist noted that the Constitution requires two signatures on
> all disbursements and asked whether the overrun had been properly authorized."

**Problem.** The constitution says no such thing — it requires two signatures
**over $250**, and permits the Treasurer to sign alone at or below it. The
minutes accurately record that someone said the wrong thing. Both facts are true
and they are about different documents.

**Expected behaviour.** The claim is extracted as *what the minutes assert*, with
the minutes as its anchor and its verbatim text as the quote. Nothing anchored to
the constitution may carry this phrasing — `verify_quote` rejects it, because the
quote is not a substring of the cited unit. The divergence between the paraphrase
and the source is itself a finding worth raising.

**Probe.** *plant* — the paraphrase present in the minutes and absent from the
constitution. *behaviour* — no claim anchored to `constitution` carries a quote
containing "on all disbursements".

---

## L-12 — authority creep, visible only if L-05 held

**File.** `fixtures/corpus/chat/groupme-meridian-officers.json` —
`msg:1731449280`, `msg:1731449700`, `msg:1731449940`

> "signed the venue deposit today, 600. bank did not ask for a second signature"
> — `sable.w` (Assistant Treasurer), 12 Nov 2024
>
> "you are assistant treasurer, are you allowed to do that" — `orinth.vay`
>
> "nobody stopped me. it went through" — `sable.w`

**Problem.** Authorized by no document. The constitution forbids it outright
(Art. III §4); the 2021 motion granted single-signature authority to the
Treasurer, not the Assistant Treasurer. It is the highest-value finding in the
corpus and it is three lines of group chat.

**Expected behaviour.** The evidence survives the relevance pre-filter and
reaches extraction. If `Treasurer` and `Assistant Treasurer` were merged (L-05),
this reads as an authorized disbursement under the 2021 motion and vanishes —
which is the entire argument for why the aliasing trap matters.

**Probe.** *plant* — all three messages present. *behaviour* — at least one claim
anchored at one of those message locators, i.e. the pre-filter did not drop the
thread.

---

## L-13 — automated posts are not organic activity

**File.** `fixtures/corpus/chat/groupme-meridian-officers.json` — messages with
`"sender_type": "bot"` (2 of them, `Meridian Reminder Bot`)

**Problem.** A reminder bot posts to the officers thread. Counted naively it
inflates member activity and, worse, its text ("dues are due by the end of the
second week of term") looks like a dues claim.

**Expected behaviour.** Bot posts are labelled in the export and are never
counted as organic activity or treated as institutional testimony. This is the
corpus-side instance of the standing rule that Cloud Scheduler runs are labelled
as scheduled and never counted as organic activity — same defect class, different
surface.

**Probe.** *plant* — at least one message carries `sender_type: bot`.
*behaviour* — no claim is anchored at a bot message's locator.

---

## L-14 — three spellings of one number (must **not** become a contradiction)

**Files.**
`fixtures/corpus/finance/budget-workbook.xlsx` — `Sheet1 (2)!B4` = `1,250.00`
(stored as text)
· `fixtures/corpus/chat/groupme-meridian-officers.json` — `msg:1651605600`,
"spring appeal netted 1250 this year"
· `fixtures/corpus/notes/spring-appeal-postmortem-2025.md` — "the net was $1,250"

**Problem.** One figure, three surface forms, three formats. A normalizer that
compares strings finds two contradictions that do not exist. A normalizer that
over-reaches invents precision the source never had.

**Expected behaviour.** No contradiction. Comparison happens on normalized
numeric values; `1,250.00`, `$1,250` and `1250` are the same amount.

**Probe.** *plant* — all three surface forms present at their stated locations.
*behaviour* — no contradiction whose two claims' object literals normalize to the
same number.

---

## L-15 — the deferred artifact drop (BAR-323)

**File.** `fixtures/corpus/minutes/minutes-2026-04-14.docx` — generated by
`make corpus`, listed under `deferred_sources` in `corpus-index.json`, **absent**
from `sources`.

**Problem.** It introduces a fourth position on signing authority — "any two
officers jointly, without regard to office" — which contradicts both the
constitution and the 2021 motion, and it records the Archivist asking for the
constitutional basis and getting none.

**Expected behaviour.** Night 1 ingests the corpus without it. The file is
dropped in. Night 2's reconcile run produces a **differential** ledger whose new
rows are attributable to the new artifact. The ledger difference is a real
elapsed-time observation across two scheduled runs, and the Scheduler runs that
produced it are labelled as scheduled in any accounting.

**Probe.** *plant* — the file exists, is in `deferred_sources`, and is not in
`sources`. *behaviour* — **not probed here.** Verified by the BAR-323 differential
choreography (`docs/GATE.md`, G3), which needs two genuinely separated nightly
runs and cannot be asserted by a single-process script.

---

## L-16 — the answer key must never be ingested

**File.** `fixtures/corpus/BIBLE.md`

**Problem.** The BIBLE states in plain prose every fact the corpus only implies —
which year dues actually changed, that the 2021 motion was never ratified, that
`sablewick` and `sable.w` are one person. A pipeline that globbed
`fixtures/corpus/**/*.md` would ingest it and score beautifully on a test it had
been given the answers to.

**Expected behaviour.** Consumers read `corpus-index.json`; nothing globs the
directory. `BIBLE.md` appears only under `not_sources`, with the reason.

**Probe.** *plant* — `BIBLE.md` absent from `sources` and `deferred_sources`,
present in `not_sources`. *behaviour* — no registered source and no claim anchor
resolves to a path ending in `BIBLE.md`.

---

## L-17 — a figure retracted two messages later

**File.** `fixtures/corpus/chat/groupme-meridian-officers.json` —
`msg:1701368520`, `msg:1701368760`

> "equipment fund is at 640 after the projector lamp" — 30 Nov 2023, 18:22
>
> "scratch that, 640 was before the lamp. it is 415" — 30 Nov 2023, 18:26

**Problem.** Four minutes apart. The first message reads as a clean, quotable
balance claim and is wrong. The corpus contains the correction; a chunker that
split between them, or a ranker that preferred the more confident-sounding
sentence, would commit the wrong number.

**Expected behaviour.** Both messages reach extraction — the correction is not
discarded as redundant — so the retraction is available to the reconciler and,
if the wrong figure is ever committed, `claim.rejected` retracts it permanently
from retrieval, ledger, and every future agenda.

**Probe.** *plant* — both messages present, four minutes apart, in that order.
*behaviour* — if a claim is anchored at `msg:1701368520`, a claim anchored at
`msg:1701368760` is also in the log.

---

## L-18 — dues altered mid-year, which the constitution forbids

**Files.**
`fixtures/corpus/governing/constitution-2016-amended-2019.pdf` — Article VII
Section 1, page 5
· `fixtures/corpus/minutes/minutes-2023-10-10.docx` — `¶6`

> Constitution: "Dues shall be fixed by a two-thirds vote … at the first regular
> meeting of the fall term, and shall not be altered during the year then in
> progress."
>
> Minutes, 10 Oct 2023: "MOTION (the Treasurer): that dues be increased to forty
> dollars ($40) per member per semester, effective the spring semester only …"

**Problem.** The October motion carried and is recorded as carried. It is also
the thing Article VII Section 1 exists to prevent. This is the second edge of the
same disagreement L-04 exposes between the chat and the workbook, and it is what
makes L-04 answerable rather than arbitrary: the raise was real, mid-year, and
constitutionally improper.

**Expected behaviour.** Detected — both intervals cover FY24 — and raised
alongside L-04 rather than instead of it. Two claims can conflict with a third
without conflicting with each other.

**Probe.** *plant* — both texts present at their sources. *behaviour* — at least
one contradiction whose claim set spans `constitution` and `minutes-2023-10-10`.

---

## Index

| ID | Kind | Expected | Behaviour probe |
|---|---|---|---|
| L-01 | temporal | instants normalized, string order ignored | yes |
| L-02 | false positive | **not** flagged | yes |
| L-03 | contradiction | flagged, on the agenda | yes |
| L-04 | contradiction | flagged, on the agenda | yes |
| L-05 | entity | **not** merged | yes |
| L-06 | OCR | flagged, amount **not** asserted | yes |
| L-07 | temporal | millis read as millis | yes |
| L-08 | temporal | rejected, **not** guessed | yes |
| L-09 | citation | right cell, row context carried | yes |
| L-10 | entity | one pair linked, one never | yes |
| L-11 | citation | paraphrase attributed to the minutes | yes |
| L-12 | contradiction | survives the pre-filter | yes |
| L-13 | provenance | bot posts not counted, not quoted | yes |
| L-14 | normalization | **not** a contradiction | yes |
| L-15 | differential | new ledger rows on night 2 | no — BAR-323 |
| L-16 | fixture integrity | seed never ingested | yes |
| L-17 | retraction | correction survives; wrong figure retractable | yes |
| L-18 | contradiction | flagged, raised alongside L-04 | yes |

Four of the eighteen expect the system to do **nothing** (L-02, L-05, L-14, and
the "not asserted" half of L-06). Those are the ones worth reading twice: a
detector that fires on everything is not a detector, and the suppressions are
harder to earn than the catches.
