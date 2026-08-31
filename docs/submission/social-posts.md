# Social posts — Baraza

Two variants per platform; post one of each. Every post must carry
`#AllThingsAgenticHackathon` exactly (verify the spelling character by
character after pasting — a mangled hashtag earns nothing).

Before posting, replace `<VIDEO-URL>` and `<BLOG-URL>` with the live links.
Posts must be **publicly visible** — a connections-only LinkedIn post does not
count. No unmeasured number appears in any variant; keep it that way if you
edit.

---

## X (Twitter)

### Variant X-1 — the mechanism

> My hackathon agent keeps a file on me — and I can open it. Every belief is my
> verbatim quote + a turn anchor, in a Firestore log whose rules reject edits.
> When I contradict myself, it shows me both quotes and makes me rule. Memory
> with due process.
>
> <VIDEO-URL>
>
> #AllThingsAgenticHackathon

### Variant X-2 — the moment

> Mid-draft, my agent stopped me: "On turn t-9 you said 'never pad estimates.'
> Just now you said the opposite. Which governs?" Both quotes mine, both
> timestamped, in a log that refuses edits. I split it into a conditional; the
> next draft obeyed it. Built on Cloud Run + Firestore + Gemini via Vertex AI.
>
> <BLOG-URL>
>
> #AllThingsAgenticHackathon

---

## LinkedIn

### Variant LI-1 — the trust argument

> Every AI product is adding "memory," and almost every memory is an opaque
> blob: a paraphrase of you, silently mutable, that keeps whichever version of
> you it heard last.
>
> For the All Things Agentic Hackathon I built Baraza, a working partner whose
> model of its user gets due process instead:
>
> — Every belief about me is a claim carrying my verbatim quote and an anchor
> to the exact exchange where I said it.
> — Claims live in an append-only Firestore log whose deployed rules reject
> update and delete — you can try to edit one in the console and watch it
> refuse.
> — When I contradict my own earlier guidance, it puts both quotes on screen
> and refuses to silently overwrite the old rule until I adjudicate.
> — Nothing acts on my behalf until I ratify it, and I can retract any belief —
> the retraction is itself an append-only event, and the same task then reruns
> under the amended doctrine, every rule citing the claim that created it.
>
> Built on Google Cloud end to end: Cloud Run, Firestore, Cloud Scheduler, and
> Gemini 3.7/3.5 Flash on Vertex AI, with the extraction agent driven by the
> Agent Development Kit.
>
> Demo: <VIDEO-URL>
> Write-up: <BLOG-URL>
>
> #AllThingsAgenticHackathon

### Variant LI-2 — the builder's story

> I have told AI tools "never pad estimates" more times than I can count, into
> memories that evaporate or resurface stale. So for the All Things Agentic
> Hackathon I built the version I'd trust: Baraza, an agent whose file on me I
> can open, audit, and retract.
>
> The moment that sold me on my own project: I gave it a rule while drafting,
> then contradicted that rule a few minutes later. It caught me — both of my
> quotes on screen, each anchored to the turn where I said it — and made me
> resolve the collision. The resolution became a conditional rule, ratified
> through an approval flow, compiled into a doctrine where every rule cites the
> sentence that put it there. The next draft followed it.
>
> The engineering that makes this honest: an append-only event log (Firestore
> rules reject edits — demonstrated live in the video), quotes as mandatory
> evidence with fabricated anchors treated as a stop condition, and a strict
> phrasing discipline — the belief-to-doctrine compilation is replayable byte
> for byte, while model compliance with the doctrine is measured, not promised.
>
> Google Cloud stack: Cloud Run services and jobs, Firestore, Cloud Scheduler
> (every scheduled run labelled as scheduled in the log), Gemini via Vertex AI,
> ADK.
>
> Demo: <VIDEO-URL>
>
> #AllThingsAgenticHackathon
