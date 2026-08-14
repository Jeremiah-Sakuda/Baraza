# Social posts — Baraza (BAR-620–624)

**Required hashtag: `#AllThingsAgenticHackathon`** — exactly that, no space, no
variant capitalization. It appears in every post below. Do not post any of these
without it; the bonus-URL credit depends on it being present and findable.

**Before posting:**

- Replace every `<…>` placeholder with a real URL. A post with a placeholder in
  it cannot be deleted-and-fixed quietly once the link is submitted.
- Every URL must have been loaded **logged out**, in a private window, on the day
  of posting.
- No number appears in any post below. Nothing is measured yet
  (`docs/metrics.json` is entirely `not yet measured`), and a social post is the
  easiest place in a submission to let a plausible number slip in.
- Character counts below were measured with `len()` on the exact body text.
  X counts every URL as 23 characters regardless of length, so the totals shown
  assume exactly one link.

---

## X — variant A (the friction)

**Body: 251 chars. With one link: 275 of 280.**

```
Every May, student orgs forget everything.

Baraza reads the mess — chat exports, crooked scans, headerless spreadsheets — finds what the records disagree with, then interviews the departing officer about the disagreements.

#AllThingsAgenticHackathon
```

Then, on its own line, the link: `<VIDEO-URL>`

**Optional reply in-thread** (keeps the main post short, adds the build detail):

```
Built on Google Cloud: Cloud Run Jobs for the nightly reconcile pass, Firestore as an append-only claim-event log, Cloud Scheduler running it unattended, Gemini on Vertex for the reasoning. Repo: <REPO-URL>
```

---

## X — variant B (the refusal)

**Body: 249 chars. With one link: 273 of 280.**

```
The moment I almost cut: the agent refuses to answer.

Successor mode answers only from the cited record. Ask something it doesn't cover and it says so. A confident guess about who can sign a cheque is worse than silence.

#AllThingsAgenticHackathon
```

Then, on its own line, the link: `<VIDEO-URL>`

**Optional reply in-thread:**

```
The refusal has its own acceptance criterion — it's a property, not a bug I didn't get to. A successor can't tell a remembered fact from a fluent guess. Silence is recoverable; they go and ask someone. <REPO-URL>
```

---

## LinkedIn — variant A (what it does)

> LinkedIn truncates at roughly 210 characters before "…see more", so the first
> two lines have to carry the post. They do.

```
Every May, thousands of student organizations forget everything they know. The officers graduate, and the handover is a shared drive with four folders named "final".

I built Baraza for the All Things Agentic Hackathon. It reads years of an organization's mess — chat exports, a constitution scanned crooked years ago, spreadsheets with no header row, meeting minutes — and asks the corpus what it disagrees with.

Overnight and unattended, it produces a ranked ledger of contradictions and an interview agenda no human wrote. Then it interviews the departing officer from that agenda. When their testimony conflicts with the documentary record, it says so in the moment, with both citations on screen, and asks which one is right. It doesn't adjudicate. A divergence between memory and record is a question, not an accusation.

Approved answers become committed memory with an explicit visibility choice, and a resolved contradiction leaves every future agenda permanently — so the next interview is shorter than the last.

Built on Google Cloud: Cloud Run Jobs, Firestore as an append-only claim-event log, Cloud Scheduler for the unattended nightly pass, Gemini on Vertex AI.

Demo video: <VIDEO-URL>
Code: <REPO-URL>

#AllThingsAgenticHackathon
```

---

## LinkedIn — variant B (the engineering)

```
The most useful decision I made on this build was to stop trusting myself to remember a rule.

The system holds private testimony from a departing officer. The requirement wasn't "check permissions before rendering" — it was that the boundary has to hold under carelessness, because a check you have to remember at a dozen read sites is a check that eventually gets forgotten at one.

So the text isn't an attribute. It lives behind quote_for(audience), and code that reaches for the raw field raises AttributeError at the access site instead of quietly returning private testimony to the wrong reader. The permission predicate is defined exactly once, and the build fails if the protected field is touched anywhere outside the schema package.

Two more of the same shape, both from defects I've actually shipped:

Every time comparison is integer epoch millis. ISO-8601 strings are serialization, never a sort key — a string sort under mixed UTC offsets once kept a revoked grant active in a system of mine while the byte-stability tests stayed green.

And every number the project displays has to trace to a run. The metrics file accepts a measured value with a run ID and a date, or the literal string "not yet measured". There is no third form, and right now every entry is the second one — which is the honest state before a measurement run has happened.

I wrote up all three, with the code: <BLOG-URL>

Built for the All Things Agentic Hackathon. Demo: <VIDEO-URL>

#AllThingsAgenticHackathon
```

---

## Rules for any additional post

- `#AllThingsAgenticHackathon`, always, spelled exactly that way.
- No numbers until they are measured. Not a claim count, not a latency, not a
  document count, not a run count.
- No framework named that the code does not import.
- No pinned model version stated until `make verify-models` has run green.
- No real organization or person named, including as an example of a group that
  lost its records. The corpus is synthetic and the story stays synthetic.
- Scheduled runs are described as scheduled. A nightly job is never presented as
  organic usage.
