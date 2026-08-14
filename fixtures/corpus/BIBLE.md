<!--
baraza-corpus-role: seed-and-answer-key
never-ingest: true
-->

# BIBLE.md — the generative source of truth for the synthetic corpus

**Everything below is invented.** The Meridian Society, Ashgrove Polytechnic
Institute, every handle, every officer, every dollar figure, every meeting and
every message is fiction written for this fixture. No real person, student,
member, company, or organization is named anywhere in this file or in anything
generated from it, and nothing here depicts a real entity as a bad actor. The
one character who quietly widens their own signing authority is a fictional
handle attached to a fictional role in a fictional club.

**This file is never ingested.** It is the seed *and* the answer key: it states
in plain language the facts that the corpus only implies, contradicts itself
about, or scans badly. Feeding it to the ingestion pipeline would let the system
read the answers instead of deriving them, which would make every downstream
number meaningless. `scripts/generate_corpus.py` emits
`fixtures/corpus/corpus-index.json` and BIBLE.md is deliberately absent from it;
`scripts/verify_manifest.py` asserts that absence as landmine **L-16**.

**This file is the whole input.** `make corpus` is a pure function of these
bytes — no wall clock, no unseeded randomness, no network. Same BIBLE, same
output bytes, therefore same SHA-256 for every source, therefore every anchor
committed against the corpus keeps resolving after a regeneration. That property
is not cosmetic: `Anchor.checksum` is the source's content hash and
`SourceRegistry.register` refuses a re-registration whose checksum moved, so a
non-deterministic generator would invalidate the entire citation layer on every
run of `make corpus`.

---

## 1. The organization

The Meridian Society is a student organization at Ashgrove Polytechnic Institute,
founded in the fall of 2016. It runs three things: the **Lantern Lecture
Series** (a monthly outside-speaker evening), the **Spring Appeal** (an annual
fundraiser), and an **equipment lending library** of projectors, PA gear and
folding chairs that other campus groups borrow.

It has the shape every organization of its kind has. Roughly 120 dues-paying
members. An operating account at the campus credit union and a restricted
**Spring Appeal Fund** that nobody has looked at closely since 2019. A
constitution adopted in 2016, amended once in 2019, scanned in 2024 from a
folded paper copy, and cited by people who have never opened it. Ten years of a
GroupMe thread. Minutes kept well in some years and not at all in others. A
budget workbook with no header row, inherited by each new treasurer as a copy of
the last one.

Ashgrove is in the Central time zone. This matters exactly once, in May 2026,
and it is the point of landmine L-01.

### Why this organization is the right fixture

The interesting failure is not that the records are incomplete. It is that they
**disagree, quietly, in ways nobody noticed**, and that the person who could
resolve the disagreement graduates in May. The constitution says one thing about
who may sign a cheque. A motion in 2021 said another. By 2024 the chat treats
the motion as the rule. By 2025 an officer whom the constitution explicitly
forbids from disbursing funds is signing for $600 and nobody blinks, because
"treasurer" and "assistant treasurer" had collapsed into one idea in everyone's
head years earlier.

That last sentence is the entity-resolution requirement stated as a story.

---

## 2. Officer timeline

Officers are recorded by **role and term**. People appear as GroupMe display
handles, which is how they appear in a real export and which is itself part of
the extraction problem: the corpus never says "the Treasurer for 2023–24 is
`vell.ory`" and "`vell.ory` wrote this message" in the same sentence, so the
link has to come from the minutes.

Fiscal year FY*N* runs 1 July (*N*−1) through 30 June (*N*). "FY24" means
2023-07-01 → 2024-06-30.

```corpus.roster
fy | term_start | term_end | president | treasurer | assistant_treasurer | secretary | archivist
FY17 | 2016-07-01 | 2017-06-30 | corvid.ash | pell.marrow | - | wisk | -
FY18 | 2017-07-01 | 2018-06-30 | pell.marrow | oriole.k | - | wisk | -
FY19 | 2018-07-01 | 2019-06-30 | oriole.k | dunmoss | - | tamsyn.qv | wisk
FY20 | 2019-07-01 | 2020-06-30 | dunmoss | harrowgate | brightmoor | tamsyn.qv | wisk
FY21 | 2020-07-01 | 2021-06-30 | harrowgate | sablewick | brightmoor | quillon.b | wisk
FY22 | 2021-07-01 | 2022-06-30 | quillon.b | sablewick | brightmoor | tamsyn.qv | sablewick
FY23 | 2022-07-01 | 2023-06-30 | brightmoor | brightmoor | vell.ory | quillon.b | sablewick
FY24 | 2023-07-01 | 2024-06-30 | quillon.b | vell.ory | kestrel9 | orinth.vay | sablewick
FY25 | 2024-07-01 | 2025-06-30 | vell.ory | kestrel9 | sable.w | orinth.vay | sable.w
FY26 | 2025-07-01 | 2026-06-30 | orinth.vay | kestrel9 | sable.w | thren.mo | sable.w
```

Notes the corpus does not state and the system must not assume:

- **FY23 has the same handle as President and Treasurer.** `brightmoor` held both
  for one year because nobody else ran. This is true, it is unusual, and it is
  *not* a data error. A system that "corrects" it is wrong.
- **`sablewick` and `sable.w` are the same human.** The handle changed in August
  2024 after a phone replacement. Nothing in the corpus says so directly; the
  only evidence is the Archivist role continuing uninterrupted across the change
  and one chat message about a lost account. This is gold pair **L-10**.
- **`sablewood` is a different human**, Equipment Steward in FY25. One character
  apart from `sablewick`, unrelated. Merging them is the false positive L-10
  guards.

### Handle catalogue

```corpus.people
handle | first_seen | last_seen | note
corvid.ash | 2016-09-20 | 2018-05-02 | founding president
pell.marrow | 2016-09-20 | 2018-06-14 | founding treasurer, then president
oriole.k | 2017-09-11 | 2019-05-30 | treasurer FY18, president FY19
dunmoss | 2018-10-02 | 2020-04-21 | treasurer FY19, president FY20
harrowgate | 2019-09-17 | 2021-05-11 | treasurer FY20, president FY21
sablewick | 2020-09-15 | 2024-07-30 | treasurer FY21-22, archivist FY22-24; handle retired
sable.w | 2024-08-19 | 2026-05-02 | same human as sablewick, new account
sablewood | 2024-09-24 | 2025-04-08 | equipment steward FY25; DIFFERENT human
quillon.b | 2020-09-15 | 2024-06-03 | secretary, then president twice
brightmoor | 2019-10-08 | 2023-06-12 | assistant treasurer FY20-22, then both offices FY23
vell.ory | 2022-09-13 | 2025-06-24 | assistant treasurer FY23, treasurer FY24, president FY25
kestrel9 | 2023-09-12 | 2026-05-02 | assistant treasurer FY24, treasurer FY25-26; the departing officer
orinth.vay | 2023-09-12 | 2026-05-02 | secretary FY24-25, president FY26
thren.mo | 2025-09-09 | 2026-05-02 | secretary FY26; the incoming treasurer for FY27
Meridian Reminder Bot | 2024-09-03 | 2026-04-27 | automated poster; never organic activity
```

---

## 3. Dues history

```corpus.dues
fy | amount_per_semester | set_by | note
FY17 | 15 | founding meeting | -
FY18 | 15 | fall vote | -
FY19 | 15 | fall vote | -
FY20 | 20 | fall vote | -
FY21 | 20 | fall vote | -
FY22 | 20 | fall vote | -
FY23 | 25 | fall vote | -
FY24 | disputed | see below | THE DUES CONTRADICTION (L-04, L-18)
FY25 | 40 | fall vote | uncontested from here on
FY26 | 40 | fall vote | -
```

**What actually happened in FY24**, which no single document states:

The fall 2023 vote set dues at $25, unchanged from FY23. In October 2023 the
treasurer proposed a raise to $40 to cover a speaker fee overrun, and the
motion carried **effective the spring semester only**. The budget workbook was
then updated in place with `40` in the dues-rate cell and the full-year member
count beside it, which produces a number that was never collected. The GroupMe
thread went on saying "$25" for the rest of the fall because that is what people
had actually paid.

Article VII §1 of the constitution forbids altering dues mid-year at all. Nobody
checked. That is landmine **L-18**, and it is the reason the interview agenda
should surface this to the departing treasurer rather than pick a winner.

---

## 4. Signing authority — the silent change

```corpus.signing
effective_from | effective_until | rule | source | ratified
2016-09-14 | - | President AND Treasurer both sign any disbursement over $250 | constitution Art. VII §3 | yes (adopted)
2019-03-02 | - | unchanged by the 2019 amendment; amendment created the Assistant Treasurer office only | constitution Art. III §4 | yes (amended)
2021-11-09 | - | Treasurer may disburse up to $1,000 on a single signature | minutes, motion carried 7-2 | NO - never made a constitutional amendment
2023-07-01 | 2024-06-30 | FY24 signing authority vested in the Treasurer (vell.ory) | minutes 2023-09-12 | routine
2024-07-01 | 2025-06-30 | FY25 signing authority vested in the Treasurer (kestrel9) | minutes 2024-09-10 | routine
2024-11-12 | - | Assistant Treasurer signs a $600 disbursement alone | chat only | NO - authorized by no document
```

The 2021 motion is the genuine contradiction (**L-03**). It is not a
misunderstanding and not a scanning artifact: a real motion really carried, and
the constitution really was never amended, so both statements are in force at
once and they cannot both be true. The temporal gate cannot save this one —
both intervals are open-ended and overlap completely.

The FY24/FY25 rows are the **false positive** (**L-02**). They look identical in
shape to the pair above — same subject, same predicate, different object — and
they are not a contradiction, because their validity intervals are consecutive
and disjoint. A detector without the temporal gate flags them; a detector with
it does not.

The November 2024 row (**L-12**) is only visible if `Treasurer` and
`Assistant Treasurer` stayed distinct entities. Merge them and the corpus reads
as "the treasurer signed for $600, which the 2021 motion allows", and the
finding disappears.

---

## 5. Accounts, funds, and the recurring figures

```corpus.accounts
entity | surface_forms | note
operating account | operating account; the operating account; operating acct | credit union, everyday
spring appeal fund | Spring Appeal Fund; the appeal fund; restricted fund | restricted; untouched since 2019
equipment fund | equipment fund; equipment reserve | replenished from rentals
```

The FY22 Spring Appeal net appears three times in three formats — `1,250.00` as
text in the workbook, `$1,250` in the postmortem note, `1250` in the chat. Same
figure. A normalizer that treats these as three different values invents a
contradiction that does not exist (**L-14**).

---

## 6. What gets emitted

`observed_at` is declared here, not read from the filesystem. A file's mtime is
when it was copied onto a machine; it has nothing to do with when the minutes
were taken, and the difference is exactly the quiet wrongness that poisons a
temporal gate.

`stage` is `night1` for everything in the cold-ingest corpus and `deferred` for
the artifact that is dropped in **between** two nightly reconcile runs to
produce the differential ledger (BAR-323). The deferred file is generated by
`make corpus` but excluded from the night-1 index.

```corpus.sources
id | path | format | observed_at | stage | note
gm-officers | chat/groupme-meridian-officers.json | groupme | 2026-05-04T00:00:00Z | night1 | ten-year officers thread, exported May 2026
budget-workbook | finance/budget-workbook.xlsx | xlsx | 2024-05-20T00:00:00Z | night1 | headerless; inherited copy-of-a-copy
constitution | governing/constitution-2016-amended-2019.pdf | pdf | 2024-03-12T00:00:00Z | night1 | skew scan of the 2016 paper copy
minutes-2021-11-09 | minutes/minutes-2021-11-09.docx | docx | 2021-11-09T00:00:00Z | night1 | the single-signature motion
minutes-2023-09-12 | minutes/minutes-2023-09-12.docx | docx | 2023-09-12T00:00:00Z | night1 | FY24 officers seated
minutes-2023-10-10 | minutes/minutes-2023-10-10.docx | docx | 2023-10-10T00:00:00Z | night1 | mid-year dues raise
minutes-2024-09-10 | minutes/minutes-2024-09-10.docx | docx | 2024-09-10T00:00:00Z | night1 | FY25 officers seated
notes-handover | notes/handover-checklist-2026-05.md | md | 2026-05-03T00:00:00Z | night1 | outgoing treasurer's scrappy list
notes-inventory | notes/equipment-inventory.md | md | 2025-10-02T00:00:00Z | night1 | lending library state
notes-postmortem | notes/spring-appeal-postmortem-2025.md | md | 2025-04-30T00:00:00Z | night1 | what went wrong with the appeal
minutes-2026-04-14 | minutes/minutes-2026-04-14.docx | docx | 2026-04-14T00:00:00Z | deferred | BAR-323 artifact drop, night 2 only
```

The prior exit interview at `interviews/prior-exit-interview-2026-05.json` is
generated but is **not** a corpus source. It is the other half of the L-01
offset trap and the "shorter than the last" baseline; it is read by the
interview layer, not by the ingestion readers.

---

## 7. The constitution (scanned PDF)

Seven pages. Page 7 is the degraded one: a re-scan of a folded page whose lower
third did not survive, carrying a marginal note about a raised threshold whose
amount is illegible. That page is landmine **L-06**, and the correct behaviour
is to record the low confidence and refuse to assert the number — not to guess
`$250`, and not to guess `$750`.

```corpus.pdf id=constitution
@page
@blank
@blank
@center THE MERIDIAN SOCIETY
@center ASHGROVE POLYTECHNIC INSTITUTE
@blank
@center CONSTITUTION AND STANDING RULES
@blank
@blank
@center Adopted 14 September 2016
@center Amended 2 March 2019
@blank
@blank
@center [chapter archive copy - scanned 12 March 2024]
@page
ARTICLE I - NAME AND PURPOSE
@blank
Section 1. The name of this organization shall be The Meridian
Society of Ashgrove Polytechnic Institute, hereinafter the Society.
@blank
Section 2. The purpose of the Society is to convene the Lantern
Lecture Series, to conduct an annual Spring Appeal in support of
that series, and to maintain an equipment lending library for the
use of the Society and of other recognized student organizations.
@blank
ARTICLE II - MEMBERSHIP
@blank
Section 1. Membership is open to any enrolled student of the
Institute upon payment of dues for the current semester.
@blank
Section 2. A member in good standing is one whose dues are paid
for the semester then in progress. Only members in good standing
may vote.
@page
ARTICLE III - OFFICERS
@blank
Section 1. The officers of the Society shall be a President, a
Vice President, a Treasurer, a Secretary, and an Archivist.
@blank
Section 2. The President shall preside at all meetings and shall
be a signatory on every account of the Society.
@blank
Section 3. The Treasurer shall keep the accounts of the Society,
shall report the balance of every account at each regular meeting,
and shall be a signatory on every account of the Society.
@blank
Section 4. (Added by amendment, 2 March 2019.) There shall be an
Assistant Treasurer, who shall assist the Treasurer in the keeping
of the accounts and in the collection of dues. The Assistant
Treasurer shall hold no independent authority to disburse funds of
the Society and shall not be a signatory on any account.
@page
ARTICLE IV - ELECTIONS
@blank
Section 1. Officers shall be elected at the last regular meeting
of the spring term and shall take office on the first day of July
following, serving until the thirtieth day of June next after.
@blank
Section 2. No officer shall serve more than two consecutive terms
in the same office.
@blank
ARTICLE V - MEETINGS AND QUORUM
@blank
Section 1. Regular meetings shall be held not less than once each
month of the academic term.
@blank
Section 2. One third of the members in good standing shall
constitute a quorum for the transaction of business.
@blank
ARTICLE VI - COMMITTEES
@blank
Section 1. The President may appoint such committees as the
business of the Society requires. No committee shall incur an
obligation on behalf of the Society without the prior approval of
the membership.
@page
ARTICLE VII - FINANCE
@blank
Section 1. Dues shall be fixed by a two-thirds vote of the members
in good standing at the first regular meeting of the fall term,
and shall not be altered during the year then in progress.
@blank
Section 2. The Society shall maintain an operating account and a
restricted Spring Appeal Fund. The Spring Appeal Fund shall be
drawn upon only by vote of the membership.
@blank
Section 3. No disbursement in excess of two hundred fifty dollars
($250) shall issue without the signatures of both the President
and the Treasurer. A disbursement of two hundred fifty dollars or
less may issue on the signature of the Treasurer alone.
@blank
Section 4. The books of the Society shall be presented for review
by the outgoing Treasurer to the incoming Treasurer before the
first day of July in each year.
@page
ARTICLE VIII - AMENDMENT
@blank
Section 1. This Constitution may be amended by a two-thirds vote
of the members in good standing at a regular meeting, provided
that the text of the proposed amendment has been circulated in
writing not less than fourteen days before that meeting.
@blank
Section 2. No motion, standing rule, or practice of the Society
shall have the effect of amending this Constitution. An amendment
is effective only upon the vote prescribed in Section 1 and upon
entry of the amended text in this document.
@blank
@blank
Attested by the Secretary, 14 September 2016.
Amendment of 2 March 2019 entered by the Secretary.
@page
CLERK'S |NSERT -- ,4MENDMENT M/1RG|N/1L|A (rev. 2O19)
Th|s p4ge w4s re-sc4nned 12 M/1RCH 2O24 fr0m the ch4pter
4rch|ve c0py. The 0r|g|n4| |s f0|ded 4|0ng the gutter 4nd
the |0wer th|rd d|d n0t surv|ve the sc4n.
M4rg|n4| n0te |n h4nd: "thresh0|d r4|sed t0 $?SO per m0t|0n
0f 9 N0V -- see m|nutes" [4m0unt ||||eg|b|e -- d0 n0t tr4nscr|be]
/// sc4n c0nf|dence |0w /// ~~~ sk3w 4.2 deg /// f0|d ||ne ///
[[[ |0wer th|rd n0t rec0ver4b|e ]]] ***** ///// ~~~~~ |||||
{{{ 0CR eng|ne re-run 3x -- n0 |mpr0vement }}} <<<< >>>> ####
```

---

## 8. Minutes (DOCX)

### 8.1 — 9 November 2021: the motion that never became an amendment

```corpus.docx id=minutes-2021-11-09
@h THE MERIDIAN SOCIETY - MINUTES OF A REGULAR MEETING
@p Tuesday, 9 November 2021, 7:00 p.m., Halloway Hall Room 214.
@p Present: the President, the Treasurer, the Assistant Treasurer, the Secretary, the Archivist, and thirty-one members in good standing. Quorum established by the Secretary.
@p The minutes of 12 October 2021 were approved as circulated.
@h Old business
@p The Treasurer reported that the November speaker invoice of $840 had been delayed eleven days because both required signatures could not be obtained before the Institute's business office closed for the term break.
@p The President observed that this was the fourth such delay in two years.
@h New business
@p MOTION (the Treasurer): that the Treasurer be authorized to disburse up to one thousand dollars ($1,000) on a single signature, so that routine speaker and venue invoices are not held for a second signature.
@p Seconded by the Archivist. Discussion followed. The Assistant Treasurer asked whether this required an amendment to the Constitution. The Secretary answered that a motion of the membership was sufficient. No copy of the Constitution was present at the meeting.
@p The motion CARRIED, 7 in favour, 2 opposed, 1 abstaining, among the officers and members voting.
@table
@row Motion | For | Against | Abstain | Result
@row Single-signature authority to $1,000 | 7 | 2 | 1 | Carried
@p The Treasurer will inform the credit union of the change.
@p No amendment to the Constitution was proposed, circulated, or voted on at this meeting.
@h Adjournment
@p Adjourned 8:05 p.m. Recorded by the Secretary.
```

### 8.2 — 12 September 2023: FY24 officers seated (false-positive side A)

```corpus.docx id=minutes-2023-09-12
@h THE MERIDIAN SOCIETY - MINUTES OF THE FIRST REGULAR MEETING, FALL TERM
@p Tuesday, 12 September 2023, 7:00 p.m., Halloway Hall Room 214.
@p Present: forty-four members in good standing. Quorum established.
@h Seating of officers
@p The officers elected in April took office on 1 July 2023 and were seated: President, quillon.b; Treasurer, vell.ory; Assistant Treasurer, kestrel9; Secretary, orinth.vay; Archivist, sablewick.
@p The Treasurer for fiscal year 2023-24 is vell.ory, who holds signing authority on the operating account from 1 July 2023 through 30 June 2024.
@p The Assistant Treasurer, kestrel9, will collect dues at the door of each Lantern evening and will deposit receipts with the Treasurer. The Assistant Treasurer does not sign on the account.
@h Dues
@p MOTION: that dues for the 2023-24 year be set at twenty-five dollars ($25) per member per semester, unchanged from the prior year. Carried by more than two thirds on a show of hands.
@table
@row Office | Holder | Term begins | Term ends
@row President | quillon.b | 2023-07-01 | 2024-06-30
@row Treasurer | vell.ory | 2023-07-01 | 2024-06-30
@row Assistant Treasurer | kestrel9 | 2023-07-01 | 2024-06-30
@row Secretary | orinth.vay | 2023-07-01 | 2024-06-30
@p Adjourned 7:52 p.m. Recorded by the Secretary.
```

### 8.3 — 10 October 2023: the mid-year dues raise

```corpus.docx id=minutes-2023-10-10
@h THE MERIDIAN SOCIETY - MINUTES OF A REGULAR MEETING
@p Tuesday, 10 October 2023, 7:00 p.m., Halloway Hall Room 214.
@p Present: twenty-nine members in good standing. Quorum established by the Secretary.
@h Treasurer's report
@p The Treasurer reported an overrun of $1,180 on the fall speaker line, chiefly the October speaker's travel, and proposed a increase in dues to meet it.
@p MOTION (the Treasurer): that dues be increased to forty dollars ($40) per member per semester, effective the spring semester only, and that the fall semester rate of twenty-five dollars ($25) stand as already collected.
@p The Archivist noted that the Constitution requires two signatures on all disbursements and asked whether the overrun had been properly authorized. The Treasurer answered that the November 2021 motion permits the Treasurer to sign alone.
@p The motion on dues CARRIED on a show of hands.
@table
@row Item | Fall 2023 | Spring 2024
@row Dues per member per semester | 25 | 40
@p The Secretary will update the roster and the Treasurer will update the budget workbook.
@p Adjourned 8:11 p.m. Recorded by the Secretary.
```

### 8.4 — 10 September 2024: FY25 officers seated (false-positive side B)

```corpus.docx id=minutes-2024-09-10
@h THE MERIDIAN SOCIETY - MINUTES OF THE FIRST REGULAR MEETING, FALL TERM
@p Tuesday, 10 September 2024, 7:00 p.m., Halloway Hall Room 214.
@p Present: fifty-one members in good standing. Quorum established.
@h Seating of officers
@p The officers elected in April took office on 1 July 2024 and were seated: President, vell.ory; Treasurer, kestrel9; Assistant Treasurer, sable.w; Secretary, orinth.vay; Equipment Steward, sablewood.
@p The Treasurer for fiscal year 2024-25 is kestrel9, who holds signing authority on the operating account from 1 July 2024 through 30 June 2025.
@h Dues
@p MOTION: that dues for the 2024-25 year be set at forty dollars ($40) per member per semester. Carried by more than two thirds.
@h Old business
@p The Archivist reported that the constitution scan of March 2024 is legible except for the final inserted page, and asked that a clean copy be obtained from the Institute's student activities office. No one volunteered.
@table
@row Office | Holder | Term begins | Term ends
@row President | vell.ory | 2024-07-01 | 2025-06-30
@row Treasurer | kestrel9 | 2024-07-01 | 2025-06-30
@row Assistant Treasurer | sable.w | 2024-07-01 | 2025-06-30
@row Equipment Steward | sablewood | 2024-07-01 | 2025-06-30
@p Adjourned 8:20 p.m. Recorded by the Secretary.
```

### 8.5 — 14 April 2026: the deferred drop (BAR-323)

Generated by `make corpus`, **excluded** from the night-1 index. Dropping this
file into the corpus between two nightly reconcile runs is what produces a
differential ledger: it introduces a fourth position on signing authority that
contradicts both the constitution and the 2021 motion.

```corpus.docx id=minutes-2026-04-14
@h THE MERIDIAN SOCIETY - MINUTES OF THE LAST REGULAR MEETING, SPRING TERM
@p Tuesday, 14 April 2026, 7:00 p.m., Halloway Hall Room 214.
@p Present: thirty-eight members in good standing. Quorum established.
@h Elections
@p Officers for 2026-27 were elected: President, thren.mo; Treasurer, thren.mo pending a second nomination; Secretary, vacant. The chair noted that no candidate stood for Assistant Treasurer.
@h Treasurer's report and handover
@p The outgoing Treasurer reported that the practice of the Society since November 2021 has been that the Treasurer signs alone up to one thousand dollars, and that in practice the Assistant Treasurer has also signed on the operating account since the autumn of 2024 "because the bank never asked".
@p The Archivist asked for the constitutional basis. None was produced at the meeting.
@p MOTION (the President): that signing authority on the operating account be exercised by any two officers jointly, without regard to office, effective immediately. Carried on a show of hands, 19 in favour, 4 opposed.
@table
@row Motion | For | Against | Result
@row Any two officers may sign jointly | 19 | 4 | Carried
@p The Archivist asked that the minutes record that no amendment to the Constitution was circulated fourteen days in advance and that Article VIII Section 2 may be engaged. So recorded.
@p Adjourned 8:40 p.m. Recorded by the Secretary.
```

---

## 9. The budget workbook (headerless XLSX)

Two sheets, because the FY24 treasurer worked in a copy of the FY22 sheet and
never deleted the original tab. There is no header row anywhere; a reader has to
infer that column B is a rate, C a count, and D a total, from the arithmetic and
from the label in column A. That inference is the point.

The number `40` appears twice on Sheet1 for unrelated reasons — the FY24 dues
rate at `B3` and the chair-rental unit price at `B7`. That is landmine **L-09**:
a claim that cites the wrong cell is grounded (the text really is "40") and
still wrong, which is precisely the failure `verify-anchors` cannot catch and a
human reading the row context can.

```corpus.xlsx id=budget-workbook
@sheet Sheet1
A1 | MERIDIAN SOC
C1 | 23-24
A3 | dues income
B3 | 40
C3 | 118
D3 | 4720
A4 | lantern series
B4 | 6
C4 | 400
D4 | 2400
A5 | spring appeal
D5 | 3115
A6 | equipment repair
D6 | -412.5
A7 | chair rental
B7 | 40
C7 | 4
D7 | 160
A9 | subtotal
D9 | 9982.5
A11 | prior yr
C11 | 22-23
A12 | dues income
B12 | 25
C12 | 131
D12 | 3275
A13 | lantern series
B13 | 6
C13 | 350
D13 | 2100
A15 | note
B15 | 'raise approved oct - spring only?? check w/ sec
@sheet Sheet1 (2)
A1 | 21-22 FINAL
A3 | dues income
B3 | 20
C3 | 142
D3 | 2840
A4 | spring appeal net
B4 | '1,250.00
A6 | equipment fund
B6 | 880
A8 | signed
B8 | 'treasurer only per nov motion
```

---

## 10. The GroupMe export

A decade in one thread, exported May 2026. Timestamps are bare epoch **seconds**,
which is what GroupMe emits — except for one message re-imported from an older
archive, which carries **milliseconds** (landmine **L-07**).

The export carries per-segment metadata including the local UTC offset the
segment was captured under. The May 2026 segment was captured in Central
Daylight Time, `-05:00`, and its `segment_started_at_iso` is one half of the
mixed-offset trap (**L-01**). The other half is a turn in the prior exit
interview in §12.

Grammar: `@segment` opens a segment. Message lines are
`ISO-8601-with-offset | handle | text`. `@raw` overrides the emitted
`created_at` with a literal value. `@bot` marks an automated poster.

```corpus.groupme id=gm-officers name=Meridian Society - Officers
@segment id=seg-2016-fall offset=+00:00 note=founding term, exported from the original group
2016-09-20T22:04:00+00:00 | corvid.ash | ok we are official. student activities approved the constitution today, filed 14 sept
2016-09-20T22:07:00+00:00 | pell.marrow | dues are 15 a semester, i have the cash box
2016-09-21T15:31:00+00:00 | wisk | minutes template is in the shared folder, please actually use it
2016-11-02T23:12:00+00:00 | pell.marrow | reminder anything over 250 needs both me and corvid.ash to sign. that is in the constitution, article 7
2017-02-14T18:45:00+00:00 | corvid.ash | first lantern of the spring is booked. 400 speaker fee
@segment id=seg-2018-spring offset=+00:00 note=-
2018-03-06T21:02:00+00:00 | oriole.k | dues still 15, we voted in september, nobody move
2018-04-19T20:15:00+00:00 | wisk | archive box is in the office closet. there is a paper constitution in it. nobody has opened it since i joined
2018-05-02T16:40:00+00:00 | corvid.ash | last one from me, handing the group over. good luck
@segment id=seg-2019-fall offset=+00:00 note=-
2019-09-17T23:50:00+00:00 | harrowgate | taking over the books from dunmoss. the sheet has no headers and i cannot tell what column B is
2019-09-18T00:04:00+00:00 | dunmoss | B is the per person rate, C is how many people, D is the total. i inherited it like that
2019-10-08T22:30:00+00:00 | brightmoor | new assistant treasurer here. the 2019 amendment says i help with the books and do not sign. noted
2019-11-14T21:18:00+00:00 | harrowgate | dues went to 20 this year btw
@segment id=seg-2021-fall offset=+00:00 note=the single-signature motion
2021-11-02T22:55:00+00:00 | sablewick | the november invoice sat for 11 days because i could not get quillon.b to sign before break. this is untenable
2021-11-09T21:40:00+00:00 | quillon.b | motion carried tonight 7-2. treasurer can sign alone up to 1000
2021-11-09T21:44:00+00:00 | brightmoor | did anyone check whether that needs a constitutional amendment
2021-11-09T21:46:00+00:00 | tamsyn.qv | a motion of the membership is enough, we did it properly
2021-11-10T14:02:00+00:00 | sablewick | credit union informed. done
2022-05-03T19:20:00+00:00 | sablewick | spring appeal netted 1250 this year, best since 2017
@segment id=seg-2023-fall offset=+00:00 note=the dues dispute
2023-09-12T23:58:00+00:00 | vell.ory | seated tonight. dues are 25 a semester for 23-24, same as last year
2023-09-25T19:12:00+00:00 | kestrel9 | collecting at the door thursday. bring exact change, 25 each
2023-10-10T23:30:00+00:00 | vell.ory | motion passed, dues go to 40 for spring. fall stays 25 since people already paid
2023-10-11T15:05:00+00:00 | orinth.vay | so what do i put on the roster
2023-10-11T15:09:00+00:00 | vell.ory | 25 for fall, 40 for spring. i will fix the sheet
2023-11-14T22:41:00+00:00 | vell.ory | dues are still 25 this semester, stop telling people 40
2023-11-30T18:22:00+00:00 | kestrel9 | equipment fund is at 640 after the projector lamp
2023-11-30T18:26:00+00:00 | kestrel9 | scratch that, 640 was before the lamp. it is 415
2024-02-06T20:33:00+00:00 | vell.ory | signed the february speaker invoice myself, 780. that is under 1000 so we are fine
@segment id=seg-2024-fall offset=+00:00 note=handle change, bot joins, authority creep
2024-07-30T17:15:00+00:00 | sablewick | losing this account, phone died and i cannot get back in. new handle incoming
2024-08-19T16:02:00+00:00 | sable.w | it is me, sablewick. still archivist. someone re-add me to the drive
2024-09-03T13:00:00+00:00 | Meridian Reminder Bot | @bot Reminder: dues are due by the end of the second week of term.
2024-09-24T21:11:00+00:00 | sablewood | equipment steward for the year, taking the chair inventory on monday
2024-09-24T21:14:00+00:00 | kestrel9 | welcome sablewood. note for everyone, sablewood and sable.w are two different people
2024-10-15T19:47:00+00:00 | kestrel9 | @raw created_at=1729021620000 re-imported from the old archive export, keeping it for the record: lantern series line is 2400 for the year
2024-11-12T22:08:00+00:00 | sable.w | signed the venue deposit today, 600. bank did not ask for a second signature
2024-11-12T22:15:00+00:00 | orinth.vay | you are assistant treasurer, are you allowed to do that
2024-11-12T22:19:00+00:00 | sable.w | nobody stopped me. it went through
@segment id=seg-2025-spring offset=+00:00 note=-
2025-03-04T20:00:00+00:00 | kestrel9 | appeal fund has not been touched since 2019 as far as i can tell
2025-04-08T18:35:00+00:00 | sablewood | four chairs cracked, rental price is 40 each to replace
2025-04-30T23:05:00+00:00 | vell.ory | postmortem is in the notes folder. short version, we underpriced the appeal
2025-06-24T15:12:00+00:00 | vell.ory | done here. kestrel9 has the books
@segment id=seg-2026-spring offset=-05:00 note=-
2026-04-27T13:00:00-05:00 | Meridian Reminder Bot | @bot Reminder: officer transition paperwork is due to student activities by 15 May.
@segment id=seg-2026-may offset=-05:00 note=EXPORT SEGMENT CAPTURED IN CENTRAL DAYLIGHT TIME - L-01
2026-05-01T20:00:00-05:00 | kestrel9 | last officers meeting of my term. i will write up what i know but honestly most of it is in my head
2026-05-01T20:04:00-05:00 | orinth.vay | please write down the signing thing. nobody agrees on what the rule is
2026-05-01T20:09:00-05:00 | kestrel9 | the rule is i sign up to 1000. that has been true since before i got here
2026-05-01T21:30:00-05:00 | thren.mo | i have the treasurer job next year and i have read none of this
2026-05-02T09:15:00-05:00 | sable.w | archive box is still in the office closet. the paper constitution is in it
```

---

## 11. Loose notes (Markdown)

```corpus.md id=notes-handover path=notes/handover-checklist-2026-05.md
# handover - treasurer - what i actually do

written 2026-05-03, badly, sorry

## money

- operating acct at the campus credit union. login is in the password manager
  under "meridian operating", ask orinth.vay
- i sign things up to 1000 by myself. over that i get the president too.
  this has been the rule since a motion in november 2021
- the spring appeal fund is restricted. i have never touched it and i do not
  know who can
- dues are 40 a semester now. they were 25 when i started and there was some
  confusion in 23-24, ask vell.ory if it comes up

## the sheet

- budget-workbook.xlsx, tab "Sheet1". no headers, sorry. column B is the rate,
  C is the count, D is the total
- there is a second tab that is the old 21-22 sheet. ignore it, i did

## dates

- last officers meeting was 2026-04-14T19:30:00 - the minutes from that one
  are not in the folder yet, the secretary still has them
- transition paperwork to student activities by 15 May

## things i never figured out

- whether the assistant treasurer is allowed to sign. sable.w did it once in
  november 2024 for a 600 venue deposit and nothing happened
- where the clean copy of the constitution is. the scan we have has a bad
  last page
```

```corpus.md id=notes-inventory path=notes/equipment-inventory.md
# equipment lending library - state of things

last walked 2025-10-02 by the equipment steward.

## what we have

- 2 projectors, one with a lamp replaced in november 2023
- 1 PA head, 2 speakers, 4 stands
- 60 folding chairs, of which 4 are cracked and unusable

## what it costs

- chair replacement is 40 each from the campus vendor
- the projector lamp was 225, paid from the equipment fund
- equipment fund balance after the lamp was 415

## rules

- other recognized organizations may borrow. the constitution says so in
  article I. we have never charged them and nobody remembers deciding that
- rentals to non-campus groups are 40 per chair per event, which is where the
  chair rental line in the budget comes from
```

```corpus.md id=notes-postmortem path=notes/spring-appeal-postmortem-2025.md
# spring appeal 2025 - postmortem

written 2025-04-30 by the outgoing president.

## what happened

We ran the appeal the same way we have run it since 2017 and it returned less
than it did in 2022, when the net was $1,250.

## why

- we priced the tickets at what the 2022 committee priced them at, and the
  speaker fee has gone up twice since
- nobody checked the restricted fund. it has been sitting since 2019 and might
  have covered the gap
- the dues change in 23-24 confused people. some members think they overpaid
  and some think they underpaid, and the roster does not settle it

## for next year

- decide what the appeal fund is actually for before the appeal, not after
- get the dues history written down somewhere that is not a group chat
```

---

## 12. The prior exit interview (May 2026)

Four turns before the officer had to leave. This is the "shorter than the last"
baseline and the other half of the **L-01** offset trap: turn `t-2` carries the
ISO string `2026-05-02T00:00:00Z`, which sorts *after* the GroupMe segment's
`2026-05-01T20:00:00-05:00` as a string and *before* it as an instant.

```corpus.interview id=prior-exit-interview-2026-05 subject=kestrel9 role=Treasurer
t-1 | 2026-05-01T23:40:00-05:00 | interviewer | The constitution says a disbursement over $250 needs two signatures. The November 2021 minutes say you can sign alone up to $1,000. Which one has the club been following?
t-2 | 2026-05-02T00:00:00Z | officer | The motion. I have signed alone for everything under a thousand since I took the books, and so did the two treasurers before me.
t-3 | 2026-05-02T00:06:00Z | interviewer | Was the constitution ever amended to match?
t-4 | 2026-05-02T00:09:00Z | officer | I do not know. I have never read it. I have to go, the room closes at seven.
```

---

## 13. Landmine index

The authoritative expected-behaviour text for every planted problem lives in
`fixtures/MANIFEST.md`, and every ID there has a mechanical probe in
`scripts/verify_manifest.py`. The script fails if the two ID sets diverge, so a
manifest entry cannot quietly lose its check.

| ID | Where it lives in this file |
|---|---|
| L-01 | §10 segment `seg-2026-may`, §12 turn `t-2` |
| L-02 | §4 signing table, §8.2, §8.4 |
| L-03 | §7 Article VII §3, §8.1 |
| L-04 | §3, §9 `Sheet1!B3`, §10 `seg-2023-fall` |
| L-05 | §7 Article III §4, §2 roster |
| L-06 | §7 page 7 |
| L-07 | §10 `@raw created_at=1729021620000` |
| L-08 | §11 handover note, "2026-04-14T19:30:00" |
| L-09 | §9 `Sheet1!B3` vs `Sheet1!B7` |
| L-10 | §2 handle catalogue, §10 `seg-2024-fall` |
| L-11 | §8.3 the Archivist's paraphrase |
| L-12 | §4 last row, §10 2024-11-12 messages |
| L-13 | §10 `@bot` messages |
| L-14 | §5, §9 `Sheet1 (2)!B4`, §10 2022-05-03, §11 postmortem |
| L-15 | §8.5 deferred minutes |
| L-16 | this file's own header |
| L-17 | §10 the equipment-fund retraction |
| L-18 | §7 Article VII §1, §8.3 |
