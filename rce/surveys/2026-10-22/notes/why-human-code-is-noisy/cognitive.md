# Cognitive-psychology sources of noise, redundancy and accidental complexity in human-written code

Scope note: notes for the Form-first language design (Reality Code Engine). Each finding is tagged **[measured]** (empirical result with numbers), **[theory]** (model/argument without direct measurement), or **[classic, not re-fetched]** (canonical reference cited from prior knowledge; URL given but not verified this session). Sample sizes in the program-comprehension literature are small (N=6 to N=63); treat effect sizes as indicative, not settled.

---

## KQ1. Working-memory and chunking limits, and their measured effects on code

### Takeaway
Working memory holds ~4 chunks (Cowan 2001), not 7; the only code metrics that track measured brain load are *textual size* and *vocabulary size* (Halstead) and data-flow dependency degree, not McCabe cyclomatic complexity. Experts beat novices by having stored plans (chunks), reading in execution order rather than story order, and fixating fewer elements. Readability metrics designed by humans do not predict measured understandability (τ ≤ 0.16 for 121 metrics).

### Cited Findings
- **[classic, not re-fetched]** Miller 1956: short-term span ~7±2 chunks; chunking (recoding) is the mechanism by which experts beat the limit — [Miller 1956](http://psychclassics.yorku.ca/Miller/)
- **[measured/meta]** Cowan 2001 reanalysis: when rehearsal and chunking are prevented, the capacity limit is 3–5 chunks, central estimate 4 — [Cowan 2001, BBS](https://pubmed.ncbi.nlm.nih.gov/11515286/)
- **[measured]** Peitek et al. ICSE 2021 (N=19 students, 1 excluded; 16 snippets; 41 metrics). Kendall τ vs. fMRI activation/behaviour: **McCabe: no correlation with anything (τ ≈ .09 correctness, .04–.09 activation).** LOC: τ=.43 activation BA21, −.46 correctness, −.39 deactivation BA32. Halstead vocabulary: τ=.32–.40 across BA6/21/39, −.45 correctness, −.42 deactivation BA32. DepDegree (data-flow): τ=.41 BA21, .36 BA39, −.41 correctness — "strongest correlation to brain activation". Subjective complexity rating vs correctness τ=−.77. Conclusions: "a code's textual size drives programmers' attention"; "vocabulary size burdens programmers' working memory"; no single metric predicts load; a "basket of simple, targeted metrics" beats one complex one; cognitive-complexity metric only small correlation — [Peitek et al. 2021, PDF](https://www.se.cs.uni-saarland.de/publications/docs/PAP+21.pdf); [replication package](https://github.com/brains-on-code/fMRI-complexity-metrics-icse2021)
- **[measured]** Siegmund et al. ICSE 2014 (N=17): bottom-up comprehension of small snippets activated left-lateralised Broca (BA44/45), BA21, BA6, BA40 — interpreted as working memory + attention + language processing. Later work (Ivanova 2020) argues this partly reflected code simulation rather than comprehension — [summary in arXiv 2304.12373](https://arxiv.org/pdf/2304.12373); [original](https://www.se.cs.uni-saarland.de/publications/docs/SKA+14.pdf)
- **[measured]** Ivanova et al. 2020 (N=24 Python, N=19 ScratchJr): code comprehension engages the bilateral *Multiple Demand* (working memory / cognitive control) system (Δβ=2.17 Python), not the language system (Δβ=0.78 weak for Python, 0.15 n.s. for ScratchJr); 17/20 MD fROIs responded more to code than sentences; **replacing English variable names with Japanese had no effect on language-system response (Δβ=0.03, p=.84)**; no code-specialised region found; expertise correlations n.s. (3–6 yrs experience, underpowered) — [arXiv 2304.12373 summary of Ivanova 2020](https://arxiv.org/pdf/2304.12373)
- **[measured]** Floyd et al. 2017 (N=29): decoding could distinguish code from English-prose comprehension patterns — [same source](https://arxiv.org/pdf/2304.12373)
- **[measured]** Peitek/Siegmund 2017 "Neural efficiency" (N=11, mean 1.7 yrs experience): **neither beacons nor pretty-printed vs. disrupted layout produced a significant activation difference** ("Neither beacons nor program layout seem to significantly affect the program comprehension process"); authors caveat low power and low expertise. Cites EEG work that more experienced programmers show lower activation (neural efficiency) — [SPP+17](https://www.se.cs.uni-saarland.de/publications/docs/SPP+17.pdf)
- **[measured]** Busjahn et al. 2015 eye-tracking (14 novices, 6 professionals): linear (story-order) reading ~80% on natural text, ~75% on code for novices, **~60% for experts**; experts make longer saccades (133.9 px vs 80.3 px) and fixate fewer code elements (41.3% vs 52.4%); "the Execution Order model better explains the experts' reading approach than Story Order does" — [Busjahn et al. 2015](https://huang.isis.vanderbilt.edu/cs8395-f23/paper/linear-order-eye.pdf); follow-up [Peitek et al. ICPC 2020, "What drives the reading order"](https://www.se.cs.uni-saarland.de/publications/docs/PSA20.pdf)
- **[measured, 1986]** Letovsky & Soloway "Delocalized plans" (6 professionals, Fortran 77 PDB program ~300 lines/15 routines, think-aloud, 90-min limit, 3/6 finished): when a plan's lines are scattered, readers form plausible-but-wrong local interpretations (e.g., copied a counter increment without seeing it was a distant dirty-bit check → unnecessary DB writes; misread `IREC=0` as a not-found marker, missing that it inhibited a search optimisation). **Readers also missed existing redundancy** (a later assignment making a pointer-reuse step unnecessary; two overflow checks duplicating each other). Remedy proposed: document each variable's goal, document "non-normal" updates, document plans as goal-and-step entries — [Letovsky & Soloway 1986](https://www.cs.kent.edu/~jmaletic/cs69995-PC/papers/letovsky-1986-software.pdf)
- **[theory + measured, 1984]** Soloway & Ehrlich: experts differ from novices in (a) programming plans (stereotyped solution fragments) and (b) rules of programming discourse (e.g., name reflects function); plan-like programs are "much easier to comprehend" than unplan-like ones, the advantage being driven by expectation — [summary](https://research.cs.queensu.ca/home/cordy/cisc860/Biblio/hurd/misc/soloway84.pdf)
- **[measured]** Scalabrino et al. TSE 2019 (63 developers, 50 Java methods, 444 evaluations, 121 metrics → 73 after dedup): **"None of the metrics we considered achieve a medium/strong correlation with any of the proxies"**; best single |τ| ≈ 0.16 (and Average Textual Coherence correlated in the *opposite* direction to expectation); best combined model τ=0.37; classifier AUC 0.72 with ~33% misclassification; interviewed developers *said* they weigh readability and identifier quality heavily, which the data did not support; developer background mattered more than snippet properties — [Scalabrino et al. TSE'19](https://www.cs.wm.edu/~denys/pubs/TSE'19-Understandability.pdf)
- **[theory/popularisation]** Hermans 2021 *The Programmer's Brain* organises this as three memories (STM/WM ~4–6 chunks, LTM, working memory) and three confusion types (lack of knowledge, lack of information, lack of processing power); recommends chunking, beacons, refactoring for cognitive load; it is a synthesis, not new measurement — [book page](https://www.happycoders.eu/books/the-programmer-s-brain)

### Inferences
- The brain-load metrics that matter — token count and vocabulary size — are precisely the quantities that redundant code, extra names, and defensive checks inflate. Human noise is self-defeating even on its own terms.
- Control-flow nesting (McCabe) is not the cost; *dependency reach* (DepDegree, delocalized plans) is. A Form that localises state transitions (total step over explicit state) directly targets the measured cost.
- Experts read in execution order and skip; novices read in story order. A notation optimised for story order (sequential prose-like code) is optimised for the reader who matters least.
- Beacons and layout — the things humans spend formatting effort on — showed no measurable fMRI effect in the one direct test (N=11, low power); treat as "no evidence of benefit", not "proven useless".

### Gaps
- No fMRI/eye-tracking study measures *code writing* (production) load; everything above is comprehension.
- No study was found that measures working-memory load as a function of the *number of distinct concurrent state variables* in a snippet (the DepDegree result is the closest).
- Expertise effects in fMRI are underpowered (Ivanova n.s., Peitek 2017 N=11); the "neural efficiency" claim rests on cited EEG work not fetched here.

---

## KQ2. Why humans serialize: over-specified order, premature commitment, concurrency

### Takeaway
"Most programmers think sequentially" is the explicit conclusion of the largest real-world concurrency-bug study (Lu et al. 2008): 97% of non-deadlock bugs are unenforced atomicity or order assumptions, 96% involve ≤2 threads, and ~30% of fixes were themselves wrong. Green & Petre's cognitive dimensions name the mechanism: notations that force an order of entry cause *premature commitment*, and sequential text makes the actual (partial-order) dependencies *hidden*.

### Cited Findings
- **[measured]** Lu, Park, Seo, Zhou ASPLOS 2008, 105 real bugs (MySQL, Apache, Mozilla, OpenOffice; 74 non-deadlock, 31 deadlock): atomicity violations 51/74 (69%), order violations 24/74 (32%); **97% of non-deadlock bugs are atomicity-or-order**; 66% involve one variable; **101/105 (96%) involve ≤2 threads**; 92% (abstract) / 90% (Finding 8.1, 67/74 — paper is internally inconsistent) manifest with ≤4 memory accesses; only 27% of non-deadlock fixes added/changed locks (73% fixed otherwise: condition checks, design changes); **17 of 57 Mozilla bugs had at least one buggy intermediate patch** (23 buggy patches); diagnosis mostly by reading source (29/57 Mozilla reports mention no tools). Authors: "Most programmers think sequentially and therefore they make mistakes easily when writing concurrent programs"; programmers "assume small code regions run atomically, or assume an order between threads without enforcing it"; locks cannot express "A before B" — [Lu et al. 2008](https://www.cs.columbia.edu/~junfeng/10fa-e6998/papers/concurrency-bugs.pdf); [MSR page](https://www.microsoft.com/en-us/research/?p=1123215)
- **[classic, not re-fetched; theory]** Lee 2006 "The Problem with Threads": threads discard determinism and composability by default; "nondeterminism is the problem"; the programmer must prune enormous nondeterminism by hand (locks), which is error-prone; argues for deterministic concurrent models (actors, dataflow, synchronous languages) — [Lee 2006, UCB EECS-2006-1](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2006/EECS-2006-1.pdf)
- **[theory, framework]** Green & Petre 1996 / Blackwell & Green CD tutorial: **premature commitment** = "constraints on the order of doing things force the user to make a decision before the proper information is available"; **hidden dependencies** = a relationship between components where the link is not fully visible (one-way pointers; the cost is search); **viscosity** = cost of small change (repetition viscosity: one change → many edits; knock-on viscosity: one change → further consistency edits); **secondary notation** = information carried outside the official syntax (indentation, comments); **diffuseness** vs terseness. Stated trade-offs: abstractions lower viscosity but raise the abstraction barrier and often add premature commitment "because they are often chosen by guesswork"; removing hidden dependencies via explicit cueing raises viscosity, and dataflow notations become more diffuse; "relaxing order constraints may make notation diffuse or increase errors, and it requires a more sophisticated system"; high viscosity + premature commitment is the worst case — [CD tutorial](https://www.cl.cam.ac.uk/~afb21/CognitiveDimensions/CDtutorial.pdf); [Wikipedia overview](https://en.wikipedia.org/wiki/Cognitive_dimensions_of_notations)
- **[measured]** Busjahn 2015 (above): novices' reading aligns with story order (top-to-bottom); experts align with execution order — i.e., even *reading* sequential text is a learned de-serialisation skill — [Busjahn 2015](https://huang.isis.vanderbilt.edu/cs8395-f23/paper/linear-order-eye.pdf)

### Inferences
- Sequential text obliges the author to pick a total order even where only a partial order is meant; the extra order is "noise" the reader cannot distinguish from required order (hidden dependency). Lu's 97% figure is the bill for this when the environment is actually concurrent.
- The ≤2-threads / ≤4-accesses result means the hard part is not scale but the *representation*: a total-step-over-state model (one atomic step at a time, events as inputs) removes the atomicity-assumption class by construction.
- Green's trade-off warns that a Form that makes dependencies explicit will look *more diffuse* to humans; the surface projection must hide that diffuseness again for human readers.

### Gaps
- No study was found quantifying how much ordering in typical sequential code is *semantically required* vs incidental (e.g., fraction of statement pairs that commute). This is the number a Form-first design would most want; it may exist in compiler/parallelisation literature (not searched here).
- No direct experiment on "premature commitment" in programming languages with numbers; CD is a vocabulary, validated mostly by questionnaire studies.

---

## KQ3. Why humans copy: clones, Stack Overflow, cognitive economy

### Takeaway
Cloning is mostly deliberate and often rational: Kapser & Godfrey found 71% of clones (Apache httpd, 30-token threshold) judged beneficial, driven by forking, templating (language can't abstract it), and customization (modifying shared code is risky). GitHub-scale duplication (Lopes 2017: 94% JS / 73% C++ / 71% Python / 40% Java files are exact copies) is dominated by vendored dependencies and generated code. Copying is the transfer channel for tacit plans that the language cannot name.

### Cited Findings
- **[measured]** Kapser & Godfrey EMSE 2008 (Apache httpd 2.2.4, 312 kLOC; Gnumeric 1.6.3, 327 kLOC): 11 clone patterns in 4 motivation groups — **Forking** (hardware/platform/experimental variation), **Templating** (boiler-plating due to language limits, API/library protocols, general language/algorithmic idioms, parameterised code), **Customization** (bug workarounds, replicate-and-specialize), **Exact match** (cross-cutting concerns, verbatim snippets). "As many as 71% of the clones could be considered to have a positive impact on maintainability" — specifically 71.2% of 59 clone groups in Apache at 30-token minimum rated good, 13.6% harmful; **but other samples varied widely**: Apache/60-token 42% good/39% harmful; Gnumeric/30-token 33% good/57% harmful; Gnumeric/60-token 57% good/42% harmful. Reasons: reuse trusted code when language lacks generics/polymorphism; follow standard API call sequences; adapt code when modifying in place is risky, owned by others, or too costly to test; time-to-market; some carelessness — [Kapser & Godfrey 2008 PDF](https://cormack.uwaterloo.ca/~migod/papers/2008/emse08-ClonePatterns.pdf); [author page](https://swag.uwaterloo.ca/publications/cloning-considered-harmful-considered-harmful.html)
- **[measured]** Lopes et al. OOPSLA 2017 "DéjàVu": 4.5M non-fork GitHub projects, 482M files, only ~85M unique → 82% chance a given file has a duplicate; **file-level exact duplicates: JavaScript 94%, C++ 73%, Python 71%, Java 40%**; near-duplicates (SourcererCC ~80% token similarity): Java 46%; 48% of JS projects have ≥50% of files duplicated elsewhere, 15% are 100% duplicated. Causes: committed `node_modules` (6% of projects, ~70% of all JS files — "single biggest cause"), vendored libraries (jQuery, boost, freetype, ActionBarSherlock, Cordova), **auto-generated code** (Axis, Android, JAXB, Django, Angular, Express) dominated sampled near-clone pairs; hand-copied libraries invisible to fork tracking — [Morning Paper summary](https://blog.acolyer.org/2017/11/20/dejavu-a-map-of-code-duplicates-on-github/); [paper DOI](https://api.crossref.org/works/10.1145%2F3133908)
- **[measured]** Baltes & Diehl EMSE 2019 / ICSE 2019 journal-first: 3.3%–11.9% of GitHub projects (across project sets) contain files referencing Stack Overflow; **at most ¼ of copied SO snippets are attributed as required**; almost half of surveyed developers admit copying SO code without attribution; at most 1.8% of repos with SO code used it CC BY-SA-compatibly — [arXiv 1802.02938](https://arxiv.org/abs/1802.02938); [ICSE 2019 page](https://2019.icse-conferences.org/details/icse-2019-Journal-First-Paper/32/Usage-and-Attribution-of-Stack-Overflow-Code-Snippets-in-GitHub-Projects)
- **[measured, 1986]** Letovsky & Soloway: a programmer *copied* a counter increment into a new routine without understanding its distant purpose — copy as a substitute for understanding a delocalized plan — [Letovsky & Soloway 1986](https://www.cs.kent.edu/~jmaletic/cs69995-PC/papers/letovsky-1986-software.pdf)
- **[theory, 1984]** Soloway & Ehrlich: experts carry a library of *plans*; a plan not expressible as a language construct must be re-instantiated by hand each time — i.e., templating clones are plans the language cannot abstract — [summary](https://research.cs.queensu.ca/home/cordy/cisc860/Biblio/hurd/misc/soloway84.pdf)

### Inferences
- The 70% GitHub clone rate cited in the RCE paper is mostly *not* individual cognition: it is vendoring + generation. The cognitive part (Kapser's templating/customization) is smaller but is exactly the part a Form can absorb: idioms the surface language cannot parametrise.
- "Modifying in place is risky / owned by others" is the loss-aversion signature: copy-and-specialise is the reversible, low-blame move. A system where reversibility is cheap removes that reason to clone.
- Copying transfers plans whose *intent* is not in the text (Naur's theory); the copier reproduces the surface without the theory, which is how the Letovsky errors arise.

### Gaps
- No study found that measures the *cognitive* cost saved by copy-paste versus re-derivation (reaction-time or error-rate experiment); "copy-paste as cognitive economy" remains an inference from the motivational taxonomies.
- Roy & Cordy's clone-detection survey (2007) was not fetched; its prevalence figures (commonly quoted 7–23% of code in clones) are not verified here.

---

## KQ4. Naming and intent: what names carry, why intent is not recorded

### Takeaway
Names are low-agreement (median 6.9% chance two developers pick the same name, Feitelson 2021) but high-dependency: humans and LLMs both lean on them as semantic anchors, and LLM summarisation drops up to 29 points when names are obfuscated (GPT-4o 87.3→58.7). Comments co-evolve with code only 7–13% of the time (Wen 2019, 1,500 projects, 3.3M commits). Naur's argument is that the theory lives in the programmer, not in the text, and is not recoverable from the text.

### Cited Findings
- **[classic, not re-fetched; theory]** Naur 1985 "Programming as Theory Building": the program text and documentation are not the program; the programmer holds a *theory* that lets them explain, modify, and justify; the theory cannot be transmitted by text alone, only by working with the theory-holder; "program death" occurs when the team holding the theory dissolves — [Naur 1985](https://pages.cs.wisc.edu/~remzi/Naur.pdf)
- **[classic, not re-fetched; theory]** Brooks 1987 "No Silver Bullet": essential complexity (conformity, changeability, invisibility, complexity of the conceptual construct) vs accidental; "the hardest single part of building a software system is deciding precisely what to build" — [Brooks 1987](http://worrydream.com/refs/Brooks-NoSilverBullet.pdf)
- **[measured]** Feitelson, Mizrahi, Noy et al. 2021 (TSE/arXiv; 334 participants): across 47 naming instances, **median probability that two developers choose the same name = 6.9%** (range 2.5%–64.6%); yet given names are interpreted consistently (96.4%/97.8% read `arrangeFilesByName(files)` as returning an ordered list) except on technical ambiguities (`add([1,2,3],[4,5,6])`: 70.9% element-wise, 20.9% concatenation); three-step model (choose concepts → choose words → choose mold/order), each step multiplies variability; **experienced developers' names 1.75 chars longer** (p<.0001), 16.7% one-word vs 26.2% for novices; function names 2.43 chars longer than variable names; model-guided names preferred 2:1 by judges (κ=0.366); longer names preferred 74% of the time, more-concept names 83% — [arXiv 2103.07487](https://arxiv.org/pdf/2103.07487); replication [arXiv 2402.10022](https://arxiv.org/pdf/2402.10022)
- **[measured]** Hofmeister, Siegmund, Holt 2017 (not fetched directly; referenced in [40-years mapping study](https://arxiv.org/pdf/2206.11102)): full-word identifiers vs abbreviations/letters — commonly reported as ~19% faster defect finding with words. Not verified this session; see Gaps.
- **[measured]** Wen, Nagy, Bavota, Lanza 2019 (1,500 Java projects ≥500 commits, 3,323,198 commits, ~1.3B AST changes): **co-evolution of code and comments in 7% of cases for method comments, 13% for class comments**; 13–20% of code changes trigger any comment change; Array/Lambda/Iteration/Literal/Method-Invocation/Name changes "rarely trigger updates"; of 362 manually-classified comment-fix commits: application-logic 136 (wrong description 35, new logic 25, more detail 53), code-design/quality 80 (technical-debt comments 54), formatting 63. Paper does not measure the fraction of comments that are inconsistent at any instant — [Wen et al. 2019](https://www.inf.usi.ch/faculty/lanza/PUBS/P/Wen2019a.pdf)
- **[measured]** Ivanova 2020: swapping English identifiers for Japanese had no effect on human language-system activation (Δβ=0.03) — names are not processed as *language* at the neural level in that task — [via arXiv 2304.12373](https://arxiv.org/pdf/2304.12373)
- **[measured, 2025]** "When Names Disappear" (arXiv 2510.03178; GPT-4o, Qwen3-Coder 480B, DeepSeek V3, Llama 4 Maverick; four semantics-preserving obfuscations: alpha-renaming, ambiguous `llllIII`, cross-domain terms, misleading names): **class-level summarisation drops 11 pts (DeepSeek 87.7→76.7) to ~29 pts (GPT-4o 87.3→58.7)**; GPT-4o method-level 65.9→44.6; LiveCodeBench summarisation drops only 0.7–5.6 (Llama slightly improved); **execution prediction also degrades** — GPT-4o ClassEval 76.6→70.2 (alpha), DeepSeek 90.0→69.3 (ambiguous), Llama LCB 80.2→56.4 (cross-domain). Authors: names are "semantic anchors"; without them models "regress to line-by-line narration"; execution drops indicate "identifier leakage" — names used as retrieval cues for memorised patterns rather than reasoning from structure — [arXiv 2510.03178](https://arxiv.org/pdf/2510.03178)
- **[classic, not re-fetched; theory]** Zave & Jackson 1997 "Four dark corners of requirements engineering": requirements are about the environment, specifications about the machine/environment interface; the designated terminology and the assumptions about the environment are what make a specification meaningful — these are exactly what is dropped when only code survives — [Zave & Jackson 1997, TOSEM](https://dl.acm.org/doi/10.1145/237432.237434)

### Inferences
- Names are a lossy, author-idiosyncratic encoding of intent (6.9% agreement) that readers nevertheless decode consistently (~97%). They are the only intent channel the language gives, so they are overloaded; the same information could be carried once, in a structured intent record, rather than smeared across every identifier.
- The LLM obfuscation result cuts both ways for a Form-first design: current models *need* names to reason about structure (execution prediction drops), so a machine-facing projection cannot simply alpha-rename; but the class-level summarisation collapse shows names are substituting for an intent record that the Form could make explicit.
- Comment drift (7–13% co-evolution) is the measured form of "intent is not recorded": free-text intent decouples from behaviour within a few commits because nothing checks it. An intent channel that is *checked* (e.g., a logged event vocabulary or invariants) is the only one that survives.

### Gaps
- Hofmeister et al. 2017 numbers not verified from primary source (fetch not performed).
- No study found quantifying how much of a program's *essential* information (in the Brooks/Shannon sense) resides in identifiers vs structure; the obfuscation study is the nearest proxy and is model-specific.
- Zave & Jackson not fetched; cited from prior knowledge.

---

## KQ5. Defensive and dead code: why nobody deletes

### Takeaway
Measured: 54–60% of files in three production systems were never executed over 6–16 months; prior work found ~25% of methods unused over 2 years and 28% of features unused over 5 months. Developers' stated reasons for not deleting — lack of knowledge, low confidence, "to avoid any risk", unknown external dependents — are a textbook loss-aversion/status-quo profile, and the authors conclude "the risk of code deletion was bigger than the benefit of it" because deletion earns no recognition. Dead-code detectors are only 32% precise, which keeps the fear rational.

### Cited Findings
- **[measured]** Haas, Niedermayr, Roehm, Apel TOSEM 2020 "unnecessary code" (14 systems; usage data on 3; 25 developers from 5 projects interviewed): **files executed at least once over the recording period: 42%, 46%, 40%** (BIS2, BIS3, Teamscale) → 54–60% of files not executed in 6–16 months; cites Eder et al. 2012 (~25% of methods unused over 2 years) and Juergens et al. 2011 (28% of features unused over 5 months); 34% of 50 recommended chunks confirmed unnecessary; **developers deleted only 10/50 (20%)** shortly after interviews; reasons for keeping: "no one was familiar with" old code; "not confident enough"; migration code kept "to avoid any risk"; Jenkins would remove nothing because of unknown plug-in dependents; UCDetector dead-code warnings 32% correct (24/76); 29% of recommended classes still reachable (so reachability-based detection misses them); authors' hypothesis: "the risk of code deletion was bigger than the benefit of it", developers get little recognition for deleting — [Haas et al. 2020](https://teamscale.com/hubfs/26978363/Publications/2020-unnecessary-code-tosem.pdf?hsLang=en)
- **[measured]** Romano et al. TSE 2018 "multi-study investigation into dead code" and ESEM 2021 dead-methods study (Java desktop apps): dead methods are prevalent and persist; not fetched in full — [TSE18](https://mustang.cec.miamioh.edu/Resources/Publication/TSE18-DeadCode.pdf); [ESEM 2021](https://conf.researchr.org/details/esem-2021/esem-2021-technical-papers/16/An-Exploratory-Study-on-Dead-Methods-in-Open-source-Java-Desktop-Applications)
- **[measured, 1986]** Letovsky & Soloway: professional readers failed to notice two duplicated overflow checks and a redundant assignment — redundancy is invisible to local reading, so it accumulates — [Letovsky & Soloway 1986](https://www.cs.kent.edu/~jmaletic/cs69995-PC/papers/letovsky-1986-software.pdf)
- **[measured]** Lu et al. 2008: 19/74 non-deadlock concurrency fixes were "condition checks" — adding a defensive check rather than removing the race; and 17/57 Mozilla bugs had buggy intermediate patches, i.e., fixes layered on fixes — [Lu et al. 2008](https://www.cs.columbia.edu/~junfeng/10fa-e6998/papers/concurrency-bugs.pdf)
- **[classic, not re-fetched; theory]** Kahneman & Tversky 1979 prospect theory: losses weigh ~2× gains; Samuelson & Zeckhauser 1988 status-quo bias. No study applying these quantitatively to code deletion was found; the Haas interview data is qualitative — [Kahneman & Tversky 1979, Econometrica](https://www.jstor.org/stable/1914185)
- **[classic, not re-fetched; theory]** Dijkstra 1972 "The Humble Programmer": "the competent programmer is fully aware of the strictly limited size of his own skull"; argues for programs whose correctness is *demonstrated* by structure, not by testing ("testing can show the presence of bugs, never their absence"), and for avoiding "clever tricks" — [EWD340](https://www.cs.utexas.edu/~EWD/transcriptions/EWD03xx/EWD340.html)
- **[measured, 2025]** "When Names Disappear": misleading identifiers cause models to narrate wrong behaviour — a machine-side analogue of defensive reading, where the reader cannot tell live from dead intent — [arXiv 2510.03178](https://arxiv.org/pdf/2510.03178)

### Inferences
- Dead code is an *asymmetry-of-evidence* problem: proving a check unnecessary requires global knowledge (reachability, all callers, all plug-ins) that no one has, while leaving it costs nothing visible. In a Form with a total step and an explicit event set, "unreachable" is a decidable property of the Form, which removes the evidential asymmetry.
- Defensive checks are the human substitute for a totality proof: each `if (x != null)` is a locally-provable fragment of a globally-unknown invariant. A total step function makes the invariant the object, not the checks.
- Low detector precision (32%) is why the fear is rational, not irrational; the design lever is making deletion *reversible* and *checked*, consistent with the user's "reversibility replaces approval" invariant.

### Gaps
- No quantitative experiment applying loss aversion to code-deletion decisions (e.g., willingness-to-delete vs willingness-to-add under matched uncertainty). The claim "nobody deletes code" is supported only by the 20% deletion rate in Haas et al. and qualitative interviews.
- Rates of *defensive* (redundant) checks specifically — as opposed to unreachable code — were not found; Letovsky's two duplicated overflow checks is anecdotal.

---

## KQ6. Readability as cognitive need vs information-theoretic cost; does it invert for models?

### Takeaway
Human readability models (Buse & Weimer 2010) predict *perceived* readability but not measured understanding (Scalabrino 2019); formatting is ~13–15% of tokens in Java/C#/C++ (4% Python) and can be stripped with ≤4.2% Pass@1 change, saving 24.5% input tokens on average (ICSE 2026). But names cannot be stripped: LLMs depend on identifiers more than structure for intent-level tasks. Readability-for-models therefore does *not* simply invert: whitespace/layout is an artifact; lexical intent carriers are not — yet.

### Cited Findings
- **[classic, not re-fetched]** Abelson & Sussman, SICP preface: "Programs must be written for people to read, and only incidentally for machines to execute" — [SICP](https://mitpress.mit.edu/9780262510875/structure-and-interpretation-of-computer-programs/)
- **[measured, 2010]** Buse & Weimer TSE 2010: a learned readability model from 120 human annotators on 100 snippets; strongest features were average line length, number of identifiers, and indentation; the model correlated with defect density and churn — [Buse & Weimer 2010 preprint](https://web.eecs.umich.edu/~weimerw/p/weimer-tse2010-readability-preprint.pdf) (numbers from prior knowledge, not re-verified)
- **[measured]** Scalabrino et al. TSE 2019: 121 metrics incl. Buse-Weimer features and textual coherence, **no metric reaches τ>0.16 with actual understandability**; best combined τ=0.37 — readability ≠ understandability — [TSE'19](https://www.cs.wm.edu/~denys/pubs/TSE'19-Understandability.pdf)
- **[measured, 2025/ICSE 2026]** "The Hidden Cost of Readability" (arXiv 2508.13666): formatting share of tokens (GPT-4o tokenizer, Stack v2): **Java 14.7%, C# 13.2%, C++ 13.2%, Python 4.0%**; fill-in-the-middle Pass@1 formatted vs unformatted: DeepSeek-V3 79.1% → 80.0%; **no model-language pair dropped more than 4.2%** (Phi-3.5 on C++); GPT-4o on Python *rose* 66.4→71.5; Claude-3.7 and GPT-4o varied <1.6% when single formatting elements were removed; Gemini-1.5 dropped significantly. Input-token savings: avg 24.5% (abstract) / 25.8% (§3.1.2) — Java 34.9%, C++ 31.1%, C# 25.3%, Python 6.5%. Output savings only ~2.5% avg because "LLMs tend to maintain formatting conventions in their outputs regardless of input formatting"; prompting cut output tokens 27.2%; fine-tuning on 50 unformatted Java samples cut output 35.9% (Gemini, Pass@1 64.1→63.7) and 24.8% (GPT-4o, 64.8→67.4). Conclusion: "code format can be and should be removed when LLMs work with source code"; proposes a bidirectional formatter (100% AST equivalence on McEval) so humans keep layout and models get compact code. Limits: 4 languages, FIM task, commercial models opaque — [arXiv 2508.13666](https://arxiv.org/html/2508.13666v1); [ICSE 2026 listing](https://conf.researchr.org/details/icse-2026/icse-2026-research-track/39/The-Hidden-Cost-of-Readability-How-Code-Formatting-Silently-Consumes-Your-LLM-Budget)
- **[measured, 2025]** "When Names Disappear" (arXiv 2510.03178): see KQ4 — identifier removal costs 11–29 points on summarisation and up to 24 points on execution prediction; models rely on names as retrieval cues — [arXiv 2510.03178](https://arxiv.org/pdf/2510.03178)
- **[measured, 2024]** Yang et al. "Less is More: DocString Compression in Code Generation" (ShortenDoc, Oct 2024): compressing docstrings by dropping low-importance words preserved and sometimes improved generation quality; cross-language transfer of compressed Python docstrings caused a slight dip — numbers not available from the secondary page fetched — [summary](https://www.promptlayer.com/research-papers/slimming-down-docstrings-less-is-more-for-ai-code-generation)
- **[measured, 2026]** "The Readability Spectrum: Patterns, Issues, and Prompt Effects in LLM-Generated Code" (arXiv 2605.13280) and Vitale et al. ICPC 2026 / EMSE 2026 (Politecnico di Torino) on readability of LLM-generated code — found in search, not fetched; listed for the report writer — [arXiv 2605.13280](https://www.arxiv.org/abs/2605.13280); [Vitale ICPC'26](https://iris.polito.it/retrieve/5d3a3db1-dfec-411e-8212-1645451c21ac/icpc_vitale_26.pdf)
- **[measured]** Peitek 2017: beacons and layout showed no significant fMRI effect on humans either (N=11) — [SPP+17](https://www.se.cs.uni-saarland.de/publications/docs/SPP+17.pdf)

### Inferences
- Three layers of "readability" separate cleanly in the evidence: (1) **layout/whitespace** — zero measured benefit for models, no measured fMRI benefit for humans, 13–15% of tokens: pure medium artifact; (2) **identifier semantics** — needed by both humans (Soloway discourse rules) and current models (obfuscation drops), but author-idiosyncratic and unchecked; (3) **structural locality** (DepDegree, delocalized plans) — the only layer with a measured human cost, and the one a Form controls directly.
- Readability-for-models does not invert; it *narrows*. Models need intent anchors (names or an equivalent) and structure; they do not need the human secondary notation. Whether a structured intent record can replace names for models is untested — the obfuscation study replaced names with nothing, not with a schema.
- Output-side stickiness (models reproduce formatting regardless of input) means a projection layer, not model behaviour, must own the format.

### Gaps
- No 2024–2026 study found that tests models on a *canonical/normalised* representation (e.g., AST, SSA, or a state/step form) versus surface code with names — the direct question for a Form-first design is open.
- Buse & Weimer numbers cited from memory; primary PDF not fetched.
- No evidence yet on whether models trained on Form-like representations would retain the name-dependence.

---

## KQ7. Expertise effects: pattern recognition and shorter code

### Takeaway
The chess-analogy mechanism (Chase & Simon: masters recall real positions, not random ones) is reproduced in programming: experts recognise plans, read in execution order, skip 10 points more of the code, and give longer, more-concept names. I found **no measured study relating years of experience to code size or entropy of the code produced**; the "experts write less code" claim is folklore without a traceable source.

### Cited Findings
- **[classic, not re-fetched; measured 1973]** Chase & Simon "Perception in chess": masters reconstruct meaningful positions far better than novices but equal them on random positions; expertise = ~50k stored chunks — [Chase & Simon 1973](https://doi.org/10.1016/0010-0285(73)90004-2)
- **[measured, 1984]** Soloway & Ehrlich: experts' advantage is confined to plan-like programs; on unplan-like programs experts drop toward novice level — expertise is recognition, not raw capacity — [summary](https://research.cs.queensu.ca/home/cordy/cisc860/Biblio/hurd/misc/soloway84.pdf)
- **[measured]** Busjahn 2015: experts fixate 41.3% of code elements vs 52.4% for novices; saccades 134 px vs 80 px; linearity 60% vs 70% — [Busjahn 2015](https://huang.isis.vanderbilt.edu/cs8395-f23/paper/linear-order-eye.pdf)
- **[measured]** Feitelson 2021: experienced developers choose names 1.75 chars longer with more concepts (2.29 vs 2.03 words) — expertise *adds* lexical information rather than compressing it — [arXiv 2103.07487](https://arxiv.org/pdf/2103.07487)
- **[measured]** Scalabrino 2019: developer background explained more variance in understandability than any snippet property — [TSE'19](https://www.cs.wm.edu/~denys/pubs/TSE'19-Understandability.pdf)
- **[measured]** Kapser & Godfrey: clone taxonomy is largely expert behaviour (deliberate forking/templating), not novice error — [Kapser & Godfrey 2008](https://cormack.uwaterloo.ca/~migod/papers/2008/emse08-ClonePatterns.pdf)
- **[unsupported]** "Experienced programmers write the same lines per day but keep more of them": the widely circulated John D. Cook post attributes it to "a study I heard of recently" with no citation, sample, or numbers — [Cook 2008](https://www.johndcook.com/blog/2008/06/03/experienced-programmers-and-lines-of-code/)
- **[measured, cited secondhand]** EEG studies cited in Peitek 2017 report lower activation in experienced programmers (neural efficiency) — [SPP+17](https://www.se.cs.uni-saarland.de/publications/docs/SPP+17.pdf)

### Inferences
- Expertise does not reduce the *entropy of the text*; it reduces the entropy of the *reader's model* by matching stored plans. Expert code is "shorter" only in the sense that it uses recognised idioms, which are then cheap to read for other experts and opaque to everyone else.
- The Soloway result (experts collapse on unplan-like code) is the strongest argument that a surface projection must emit *canonical idioms* per target community, not merely correct code.

### Gaps
- No measured relation between experience and produced code size, Halstead volume, or compression ratio was found. The claim should be stated as untested.
- Chase & Simon not re-fetched.

---

## Synthesis: what the evidence implies for a Form-first language

### Takeaway
Human noise has four measured sources with different fates under a Form (state, events, total step, log): (1) serialisation of a partial order (Lu 97%; Green premature commitment) — eliminated by construction; (2) delocalised state/plans (Letovsky; DepDegree τ≈.4) — eliminated by explicit state; (3) copying as plan transfer and risk avoidance (Kapser; Haas) — absorbed into the Form as parametrised idioms, with reversibility removing the risk motive; (4) names/comments as the only intent channel (Feitelson 6.9%; Wen 7–13%; obfuscation −29 pts) — **not eliminable**: the surface must still carry intent anchors because both human experts (discourse rules) and current models (identifier leakage) read through them.

### Cited Findings
- All findings above; key anchors: [Peitek 2021](https://www.se.cs.uni-saarland.de/publications/docs/PAP+21.pdf), [Lu 2008](https://www.cs.columbia.edu/~junfeng/10fa-e6998/papers/concurrency-bugs.pdf), [Kapser & Godfrey 2008](https://cormack.uwaterloo.ca/~migod/papers/2008/emse08-ClonePatterns.pdf), [Haas 2020](https://teamscale.com/hubfs/26978363/Publications/2020-unnecessary-code-tosem.pdf?hsLang=en), [Feitelson 2021](https://arxiv.org/pdf/2103.07487), [Wen 2019](https://www.inf.usi.ch/faculty/lanza/PUBS/P/Wen2019a.pdf), [Hidden Cost 2025](https://arxiv.org/html/2508.13666v1), [When Names Disappear 2025](https://arxiv.org/pdf/2510.03178), [Scalabrino 2019](https://www.cs.wm.edu/~denys/pubs/TSE'19-Understandability.pdf), [Busjahn 2015](https://huang.isis.vanderbilt.edu/cs8395-f23/paper/linear-order-eye.pdf)

### Inferences
**Artifacts of the medium (drop from the Form, regenerate in projection only):**
- Layout, indentation, whitespace, line breaks: 13–15% of tokens; no measured human (fMRI, N=11) or model (≤4.2% Pass@1) benefit. Secondary notation in Green's sense.
- Total statement order where only a partial order is semantic: the premature-commitment artifact; the source of the atomicity/order bug class.
- Replicated idioms (templating/boiler-plate clones): the language-limitation artifact.
- Defensive checks that re-prove locally what a total step proves globally; dead branches that no one can prove unreachable in a sequential text but are decidable over an explicit event set.
- Free-text comments as an intent record: drift measured at 87–93% non-co-evolution.

**Human needs the surface must still serve (because the measurement says the reader fails without them):**
- **Locality**: the surface must present each plan's lines together (Letovsky) and keep dependency reach (DepDegree) small; this is the one metric with medium correlation to measured brain load.
- **Small vocabulary per view**: Halstead vocabulary tracks working-memory load (τ≈.4); projections should minimise distinct symbols in any one view, consistent with Cowan's ~4 chunks.
- **Recognisable plans/idioms**: experts collapse on unplan-like code (Soloway); projections must emit the target community's canonical idioms, not merely equivalent code.
- **Intent anchors**: names (or a structured equivalent the projection renders as names) — humans decode them at ~97% consistency and current models lose 11–29 points without them. Since authors agree only 6.9% of the time on a name, the Form should hold the *concept* and let the projection choose words, which is exactly Feitelson's step 1 vs steps 2–3.
- **Execution-order navigability**: experts read in execution order; a projection should make the step function's order the reading order rather than story order.

**Open empirical questions the design should test, because no evidence exists:**
- Whether models reason correctly from a canonical Form (state/step/events) *without* surface names — the obfuscation study replaced names with nothing, not with a schema.
- What fraction of ordering in ordinary sequential code is semantically required (commutation rate).
- Whether making deletion reversible changes the measured 20% deletion rate (Haas) — the direct test of "reversibility replaces approval".

### Gaps
- See per-question gaps. The largest: no production-side (writing) cognitive measurements; no experience-vs-code-entropy data; no model studies on canonical intermediate forms.
