# Manual review of plausible, not AST-equal patches (g1-100-v2)

Standard: correct only if semantically equivalent to the developer fix on all
inputs (TBar's authors' standard). Overfitting patches stay plausible.
Reviewed 2026-10-11 against framework/projects/<P>/patches/<n>.src.patch.

| bug | judgment | reason |
|---|---|---|
| Chart-7 | plausible | Fixes the start index (minMiddleIndex to maxMiddleIndex) but not the matching end line; the developer fixes both. |
| Chart-9 | correct | `endIndex < startIndex \|\| (endIndex < 0)` is the developer's condition with operands swapped; both side-effect-free, same value. |
| Chart-13 | plausible | Replaces getWidth with getHeight; the developer clamps with Math.max(..., 0.0). Different values for most constraints. |
| Chart-14 | plausible | Calls getAnnotations().remove(marker) instead of guarding markers == null; returns the wrong result when markers exist. |
| Chart-25 | plausible | The meanValue null guard matches, but swapping getStdDevValue for getMeanValue changes the error bar; the developer null-guards the std dev instead. |
| Lang-7 | correct (corrected) | `startsWith("--") && isBlank(str)` is unsatisfiable (a string starting with "--" is not blank), so the if never runs: equivalent to deleting it, which is TBar's patch for this bug, labelled correct by TBar's authors. Counted as correct under the same standard. First review wrongly called it plausible. |
| Lang-10 | plausible | Adds `&& c=='\''` (never true with whitespace); the developer collapses whitespace runs into \\s*+. |
| Lang-13 | plausible | Deletes the resolveClass override; the developer adds a primitive-type fallback. Different class resolution. |
| Lang-20 | correct | Drops the initial capacity argument; StringBuilder capacity is not observable, and like the developer fix it no longer calls array[startIndex].toString() for sizing. |
| Lang-22 | plausible | Makes the u test `==1` but leaves `v <= 1`, so gcd(x, 0) still returns 1; the developer adds the zero and MIN_VALUE cases. |
| Lang-26 | correct | `this.mLocale` and `mLocale` name the same field (no local shadows it). |
| Lang-33 | correct | `classes == null` is dead (it was just allocated); `continue` on a null element leaves classes[i] at its default null, same as the developer's ternary. |
| Lang-39 | correct | Two null `continue`s before the length line are the developer's combined `searchList[i] == null \|\| replacementList[i] == null` continue. |
| Lang-47 | correct | `new String()` is equal to `""`; only appended by value, so the identity difference is not observable. |
| Lang-58 | plausible | Adds `dec != numeric \|\|`, which changes acceptance of other inputs; the developer adds an isDigits(substring(1)) check. |
| Lang-63 | plausible | Passes (end, end, ..., milliseconds); passes the tests by accident, and the developer rewrites the day borrow. |
| Math-2 | plausible | Uses getSupportUpperBound instead of avoiding int overflow; different mean for most parameters. |
| Math-11 | correct | For int dim, `-dim / 2d` equals `-0.5 * dim` exactly in IEEE double arithmetic (halving is exact). |

Result: 8 of 18 judged correct (Lang-7 corrected on second reading). Correct total for g1-100-v2: 13 AST-equal + 8 reviewed = 21.

# Manual review, g1-100-v3 (dev set, binary a8f51153)

19 plausible, not AST-equal. 14 patches are byte-identical to v2 and keep the v2 verdict above. The five that changed or are new:

| bug | judgment | reason |
|---|---|---|
| Chart-13 | plausible | Now `getWidth() + w[2]`; the developer clamps `Math.max(getWidth() - w[2], 0.0)`. Different upper bound whenever w[2] > 0. |
| Lang-7 | correct | `startsWith("--") && !startsWith("-")` is unsatisfiable, so the if is dead: equivalent to TBar's correct removal (same reasoning as v2). |
| Lang-24 | correct | `(foundDigit && !hasExp) && !(hasDecPoint \|\| hasExp)` reduces to `foundDigit && !hasExp && !hasDecPoint`, the developer fix; all operands are side-effect-free booleans. |
| Lang-63 | plausible | Moves the month reduction above the year read; the developer rewrites the day borrow and the whole reduce chain. Different results for other dates. |
| Math-11 | correct | `(1.0 / 2) * -dim` equals `-0.5 * dim` exactly in IEEE double (int dim, halving exact). |

Result v3: 15 AST-equal + 9 reviewed correct = 24 correct, 34 plausible (verdicts in results/g1-100-v3.review.json).
