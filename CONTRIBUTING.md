# Contributing

Corrections and additions are very welcome, especially live test results for
anything currently marked `manifest-only`, `inferred`, or "range unconfirmed".

## The evidence standard

This repository's only real value is that you can trust the distinction between
what was measured and what was guessed. Please keep that intact.

Tag every claim:

| Tag | Use when |
|---|---|
| `live-manifest` | It came from `WEBSERVER_LIST_VARIABLES_JSON` against a running game |
| `live-probe` | You issued the request yourself and read back the result |
| `repo:file:line` | You are citing a community client's source, at that exact location |
| `inferred` | You reasoned it from adjacent facts. Say so |

Always include the game build (`?Variable=GAME_VERSION`). A finding without a
build stamp cannot be checked later.

## Rules that matter more than they look

**Read back after every write.** HTTP 200 has five meanings on this API and four
of them look like success. A claim of the form "posting X works, it returned
200" is not evidence and will not be merged.

**Report ambiguous results as ambiguous.** If a variable moved but you cannot
separate your command from something else happening at the time, that goes in an
"unattributed" section. It does not get promoted to a finding. There is already
precedent for this in
[docs/emergency-controls.md](docs/emergency-controls.md).

**Disclose method limitations.** If your measurement harness has a known bug,
document it next to the results it affects. Again, there is precedent: the
null-probe aliasing disclosure in the same file.

**Test hypotheses where they disagree, not where they agree.** An observation
that two rival explanations both predict is not evidence for either one; it
only feels like it is. It takes a second observation, chosen specifically
because the rivals diverge there, to settle anything. Two examples in this
repository: the rated-power denominator (400 vs 1200,
[docs/value-semantics.md](docs/value-semantics.md) section 12) could not be
settled by a plausible-looking ratio, only by an installed-equipment test.
`TIME_STAMP`'s semantics (minutes since midnight vs. cumulative minutes since
game start, same file section 13) looked settled by a single daytime reading
that both hypotheses explained identically; only a reading taken after
crossing midnight discriminated between them. Before treating a single
reading as a finding, ask what a rival hypothesis would have predicted at
that same point. If the answer is "the same thing," you have not measured
anything yet.

**Do not fit a constant to the event you are explaining.** If you need a plant
capacity or a tank volume, look it up in the manifest. Deriving it from the
transfer you are trying to account for is circular, and it has already produced
one published error here that was off by a factor of 39.

**A conservation violation is a fact about your instrumentation, not the plant.**
If your numbers say a tank cycled more water than existed, the gauge is the
artifact. Do not build a narrative that explains it.

**Where a client's source conflicts with the manifest, the manifest wins**, and
the conflict gets documented rather than silently resolved.

## Safety

Do not add `FUN_*` variables to any probe sweep. Read
[docs/fun-family.md](docs/fun-family.md) first. Those are trigger writes with no
safe no-op form.

Test writes on a throwaway save.

## Regenerating the generated docs

`docs/writable-variables.md` and `docs/valves.md` are generated from the JSON
captures in `data/`. Do not hand-edit them; update the generator or the capture.
[docs/scraping.md](docs/scraping.md) has the full procedure.

The variable-table generator asserts that all 91 manifest names are both grouped
and given a semantics entry. If a future build adds a variable, generation fails
loudly instead of silently dropping it. Please keep that property.
