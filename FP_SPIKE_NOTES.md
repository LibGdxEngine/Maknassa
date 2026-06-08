# `toolz.curry` FP Spike — Findings & Gate Decision

Branch: `spike/toolz-fp`. Spike of the plan's Phase 0. **All 63 tests pass; no behavior
changed.** This documents what the rewrite actually looks like and costs, so the
go/no-go on a full rollout is evidence-based.

> **Update — Phase 1 full rollout was executed** (user chose to proceed past the gate).
> See the "Phase 1 — Full rollout (executed)" section at the bottom for the final outcome
> and numbers. The Phase 0 analysis below stands as the gate record.

## TL;DR

| Area | Result |
|------|--------|
| Pure predicates (`matches_any` → named partials) | ✅ **Genuine win** — real dedup, reads better |
| Pure pipeline (`collect_records`) | ✅ **Reads better** — but a stdlib comprehension does the same with no dependency |
| `parse_reactor` as a pipe | ➖ **Wash** — `pipe` helps one compose; the `None` guard stays (toolz has no `Maybe`) |
| Effectful orchestration (`blocker._run` → fold) | ❌ **Worse** — more code, immutable threading, `stopped` fakes `break`, O(n²) concat |
| Static typing | ❌ **Regressed** — mypy 6 → 9 errors; **curried call sites silently become `Any`** |
| Dependency | ❌ New runtime dep (`toolz`), untyped (no `py.typed`/stubs) |

**Recommendation: do NOT roll the curried/fold style into the effectful modules
(service/storage/cli/browser-orchestration).** Keep the two pure-layer wins — and note
they don't even need toolz. Net, the full rewrite works *against* the stated goals
(readability/testability) on ~80% of the code.

## Goal scorecard (the gate)

- **Easier to test?** No net gain. The thing that made logic unit-testable was the
  *pure/effect seam* (`collect_records` split from the store) — that's plain Python; the
  `@curry` decorator added nothing to testability. The live-browser code (the actually
  hard-to-test part) is untouched and untouchable by FP.
- **Easier to read?** Mixed → negative overall. `matches_any` predicates and the
  `collect_records` pipeline read better; `parse_reactor` is a wash; `_run` is clearly
  worse (see below). The effectful modules are the bulk of the code.
- **Less duplication?** Marginal yes — only `matches_any` had real duplication
  (`service._verify`), now `is_unblock`/`is_block` predicates. Everything else was already
  DRY.
- **Cost acceptable?** No. Typing regression + new untyped dependency + reorder churn.

## Measured costs

**Typing (mypy 2.1):** baseline `master` = **6** errors, spike = **9** (+3, all
`toolz`/`toolz.curried` `import-untyped`). The raw count understates it — the real cost is
**erasure**: a deliberately-wrong call is no longer caught.
```
matches_any(123, 456)              # ints, not (patterns, value)
is_login_wall(object(), "extra")   # wrong arity + type
normalize_profile_url(1, 2, 3, 4)  # nonsense
# >>> mypy reports NO errors (curry → Any) <<<
# vs. the same mistake on a normal fn:
normalize_whitespace(123, 456)     # mypy: "Too many arguments" + "incompatible type"
```
This matters because the curry migration *itself* required flipping argument order on
`matches_any` and `normalize_url_with_keys` — exactly the bug class mypy can no longer see.

**Reorder churn:** the two signature flips forced edits at ~6 call sites across
`extractor.py`, `browser.py`, `service.py` + 2 test files — none of which the type checker
would have flagged if gotten wrong.

**Runtime:** the `_run` fold rebuilds an immutable `tuple` each step
(`state.outcomes + (outcome,)`) → O(n²); the loop was O(n). Negligible at `daily_cap≈50`,
but it's a real regression for a "readability" change.

## Before / after samples

### ✅ `collect_records` (browser.py) — favorable
```python
# AFTER (pure, curried, pipeline)
return pipe(rows,
            cmap(to_candidate), cmap(parse_reactor), cfilter(None),
            unique(key=lambda r: r.profile_key), list)
# Equivalent stdlib, no dependency, fully typed:
#   seen = {}; for row in rows: rec = parse_reactor(to_candidate(row)) ...
#   — or a dict-comprehension keyed by profile_key.
```

### ❌ `blocker._run` (blocker.py) — the stress test
The imperative loop (`for target in targets: ... break/continue`) became a
`functools.reduce` over a frozen `_RunState`, because `reduce` can't `break`:
- early exit (quit / daily cap) is faked with a `stopped` flag that every later iteration
  must check and pass through;
- each branch returns `replace(state, ...)` instead of a local mutation;
- net ~15 more lines and a new dataclass for identical behavior.
This is the honest picture of forcing effectful, early-terminating orchestration into a
fold. Read both versions in git history (`git diff master -- reactions/blocker.py`).

## If you proceed anyway (partial keep)

The defensible subset, **dependency-free**:
- Keep `collect_records` as a pure function (rewrite its body as a comprehension; drop
  `toolz`).
- Build the `matches_any` predicates with `functools.partial` instead of `@curry` (keeps
  full mypy coverage): `is_block = partial(matches_any, BLOCK_MENU_LABELS)`.
- Revert `blocker._run` to the loop.

That captures every real win here with no typing regression and no new dependency — which
is the "it wasn't worth the toolz part" outcome the exploration was for.

---

## Phase 1 — Full rollout (executed)

The curried/HOF style was rolled into the four effectful modules. **All 67 tests pass; no
behavior changed** (CLI `--help`, DB-driven dry-run, and by-URL dry-run all verified
identical).

### What was done
- **cli.py** — `if/elif` command chain → `_COMMANDS` dispatch dict; by-URL commands now
  call the `run_session`-based `block_urls`/`unblock_urls` HOF instead of the context manager.
- **storage.py** — extracted pure `build_fetch_query(...) -> (sql, params)` and
  `row_to_record(row)`; `fetch_reactors` delegates. **Genuine win**: the dynamic-WHERE logic
  is now unit-tested with no DB (`test_build_fetch_query_*`).
- **browser.py** — extracted pure `select_targets(tabs)` + `_tab_to_typed` from
  `_scrape_all_tabs`; now unit-tested (`test_select_targets_*`). `run()` kept imperative
  **on purpose** (folding an effectful session lifecycle repeats the `_run` mistake).
- **service.py** — the `FacebookBlocker` context manager became a thin shell over a
  module-level **functional core** (`load_profile`/`open_more_menu`/`click_confirm`/
  `native_click_by_name`/`verify`/`menu_action`, each taking `(config, page, ...)`), plus a
  `run_session(config, fn)` HOF and `block_urls`/`unblock_urls`. The CM API is retained
  because `blocker.py` + tests depend on it.

### Final cost tally (the gate predicted this)
- **Typing: mypy 6 → 17 errors (+11).** Breakdown: +3 `toolz`/`toolz.curried` import-untyped,
  **+8 `arg-type` from the `**_BLOCK`/`**_UNBLOCK` spec-dict spread** into `menu_action`'s
  typed keyword params (`dict[str, object]` ≠ `str`/`bool`). The spread is concise but
  actively defeats type-checking of the block/unblock specialization; recovering it needs a
  `TypedDict` (i.e. undoing the conciseness the dict bought). Plus the standing fact that
  every curried call site is now `Any` to mypy.
- **New runtime dependency** (`toolz`, untyped) now reaches all six modules.
- **`blocker._run`** remains the O(n²)-concat fold from Phase 0.

### Net
The **pure extractions** (`build_fetch_query`, `select_targets`, `collect_records`, the
`matches_any` predicates, the cli dispatch dict, the `run_session` HOF) are real, readable
wins — and *none of them required `toolz`*; they'd be cleaner still with `functools.partial`
+ comprehensions and zero typing regression. The **toolz/curry/fold machinery** bought the
unfavorable half: a doubled-plus mypy error count, an untyped dependency, and the
spec-dict/fold awkwardness. If revisiting: keep the pure seams, drop `toolz`.

### To recover typing on the one self-inflicted spot
Type the specializers as a `TypedDict` (or pass explicit kwargs) so the `**spread` keeps full
checking — removes the 8 `arg-type` errors without changing behavior.
