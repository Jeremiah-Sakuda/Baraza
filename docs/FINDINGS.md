# FINDINGS.md

Measured numbers and toolchain observations, appended per session with the date.
What the tools supported, where they fought the design, what the long-context
passes got right and wrong.

Admitting that something degraded is more credible than claiming everything
worked.

---

## 2026-08-13 — session B0

### The repository arrived without its own contract

`docs/PRD.md` was absent. `baraza-prd-v1.2-amendments.md` amends a v1.1 file
that is not in the tree, and its §6 integration instruction ends with an
explicit stop condition: *"if any is missing from the v1.1 file itself, STOP per
§2.5.2 — do not reconstruct."*

Roughly fifteen requirement IDs have full text in the amendments. The remaining
~35 — BAR-001/002/004/006, 101/102, 301–308, 321–323, 331–336, 338, 340, 411,
501, 505, 506, 601–608, 620–624 — exist in this session only as identifiers with
no acceptance criteria.

**What was done about it:** the substrate was built anyway, because none of it
depends on the unrecovered sections — the hard constraints in AGENTS.md and the
amended requirement text fully specify the schema, the fold, the boundary, and
temporal normalization. `make compliance` distinguishes exit **2** ("the audit
could not run") from exit **1** ("the audit found problems") so the gap reads as
a gap rather than as a pass. Nothing was reconstructed.

**What this costs:** any requirement whose AC lives only in v1.1 is currently
being satisfied against inference rather than against a contract. That is a real
and unquantified risk, and it is the single highest-value thing to close.

### The visibility boundary was made structural rather than conventional

The first design had `Claim.quote` as an ordinary attribute with a `readable_by`
call expected at each read site. That is a boundary held by discipline, and the
requirement says it must hold under carelessness.

Changed to: the text lives in `_quote_protected` and is reachable only through
`quote_for(audience)`. Code that writes `claim.quote` now raises `AttributeError`
at the access site rather than returning private testimony. `scripts/compliance.py`
fails the build if `_quote_protected` appears anywhere outside
`src/baraza/schema/`.

The cost is real and worth naming: serialization has to reach through the same
door, so `to_dict()` lives inside the schema package and every consumer of the
raw dict is trusted. That is a smaller trusted surface than "every read site",
but it is not zero.

### The compliance lints were verified by planting violations, not by reading them

A lint nobody has seen fail is a lint that might not work. All three structural
lints were confirmed by writing a file containing a model-ID literal, a
`_quote_protected` access, and an ISO-string sort, running the audit, and
checking that each was reported with a file:line. All three fired; removing the
file returned the audit to green.

The first version of the model-pin regex produced a false positive on the word
"Gemini" opening a docstring. Requiring a `-<digit>` version suffix fixed it.
Worth recording because the failure mode of an over-broad lint is that someone
adds an allowlist entry and the lint quietly stops covering the real case.

### BAR-309's trap needed a real example, and the obvious one is wrong

The intuitive illustration — `09:00-05:00` vs `08:00Z` — does **not** diverge:
string order and instant order agree, and a test built on it would pass for the
wrong reason.

A pair that genuinely diverges crosses a date boundary:

| a | b | string says `a<b` | instant says `a<b` |
|---|---|---|---|
| `2026-05-01T20:00:00-05:00` | `2026-05-02T00:00:00Z` | **True** | **False** |

`a` is 2026-05-02T01:00Z, one hour *after* `b`, but sorts before it as text.
This is the pair planted in the corpus manifest and named by the fold-stability
property test.

### Not yet measured

Nothing in `docs/metrics.json` carries a value. Every entry is the literal
string `"not yet measured"`, which is the correct state before any run has
happened.

### Toolchain observations

- Model IDs are **pinned but unverified**. `scripts/verify_models.py` resolves
  every pin against live Vertex and exits nonzero on any that does not. Until
  that has run green against the target project, no document in this repository
  may state which model version shipped. A pinned literal nobody checked is a
  plausible value where a verified one belongs.
- ADK and GenAI SDK version floors in `pyproject.toml` are floors, not verified
  compatible sets. First `make install` on a clean machine is the check.
