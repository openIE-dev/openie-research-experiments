# Cultural, linguistic and identity sources of noise in code (for RCE / Form-first design)

Scope note: "Evidence" = Cited Findings (dated, linked). "Essay" = Inferences. Classic essays (Iverson, Dijkstra, Abelson–Sussman, Knuth, Gabriel, Spolsky) are cited by canonical URL from memory where not fetched this session; they are marked (not fetched) and the writer should treat quotes as paraphrase unless verified.

## KQ1. Programming languages as communities and identities: tribes, adoption, and the belief-vs-evidence episode

### Takeaway
Language choice is driven overwhelmingly by social/ecosystem factors (libraries, existing code, peers), not intrinsic features; the one widely-cited "evidence" that languages determine code quality (Ray et al. 2014) collapsed under reproduction (Berger et al. 2019), yet 26 of 30 citing papers had already read it as causal. Language culture runs on belief; the evidence base for most syntax/feature tribal positions is thin or null.

### Cited Findings
- Meyerovich & Rabkin, "Socio-PLT: Principles for Programming Language Adoption" (Onward! 2012): argues PL research should study sociological adoption; many language features have benefits programmers cannot readily observe ("observability barriers," analogised to clean water / safe sex in public health) — [Cornell seminar abstract](https://www.cs.cornell.edu/projects/tpls/papers/20140414.shtml)
- Meyerovich & Rabkin, "Empirical Analysis of Programming Language Adoption" (OOPSLA 2013): external factors (library availability, social influence) matter far more than intrinsic features; performance ranks second behind libraries; ~1/3 of developers value static types vs ~2/3 valuing unit tests; C++ hardest to master, Python/Ruby easiest; "Growth comes by expanding to new domains," niche by niche (NumPy, Rails) — [Haldar summary](https://vivekhaldar.com/articles/empirical-analysis-of-programming-language-adoption)
- Ray et al., "A Large Scale Study of Programming Languages and Code Quality in GitHub" (FSE 2014; CACM Research Highlight 2017) reported 11 languages significantly associated with defects (6 positive, 5 negative) — per the reproduction below.
- Berger, Hollenbeck, Maj, Vitek, "On the Impact of Programming Languages on Code Quality: A Reproduction Study" (TOPLAS 2019): repetition only partly successful; reanalysis found 27,450 duplicate commits (1.86% overall, up to 15% for some languages), ~36% false-positive rate in keyword-based bug-fix labelling, TypeScript mislabelled (only 16 of 41 "TypeScript" projects contained TypeScript; ~34% of remaining commits touched only type declarations), 16 p-values compared against one cutoff with no family-wise correction. After correction only 4 languages remained significant (C++ positive; Clojure, Haskell, Ruby negative) and "the effect size is exceedingly small" — [arXiv 1901.10220](https://arxiv.org/abs/1901.10220); [Rebuttal² arXiv 1911.11894](https://ar5iv.arxiv.org/html/1911.11894)
- Citation audit in Rebuttal²: of papers citing FSE/CACM versions, only 4 described results as associations; 26 implied causality (e.g., "static typing is better than dynamic typing") — [arXiv 1911.11894](https://ar5iv.arxiv.org/html/1911.11894)
- Ray et al.'s rebuttal disputes the 36% FP estimate and the Bonferroni choice, and says TOPLAS should have compared against the CACM version; Berger et al. respond CACM data was requested and never provided — [Ray et al. rebuttal arXiv 1911.07393](https://arxiv.org/pdf/1911.07393); [Berger response](https://ar5iv.arxiv.org/html/1911.11894)
- Stefik & Siebert, "An Empirical Investigation into Programming Language Syntax" (ACM TOCE 2013): novices using Perl and Java were not significantly more accurate than with "Randomo" (keywords drawn at random from ASCII); Quorum, Python, Ruby outperformed the placebo; `for`, `while`, `foreach` were among the three most unintuitive tokens to non-programmers; authors conclude designers skip basic usability testing — [Never Work in Theory summary](https://neverworkintheory.org/2014/01/29/stefik-siebert-syntax.html); [PDF](https://www.vidarholen.net/~vidar/An_Empirical_Investigation_into_Programming_Language_Syntax.pdf)
- Shrestha, Barik, Parnin, "Here We Go Again: Why Is It Difficult for Developers to Learn Another Programming Language?" (ICSE 2020; CACM 2022): of 450 Stack Overflow posts across 18 languages, 276 (61%) contained incorrect assumptions carried over from another language; 16 interviewed professionals described interference and the need to "suppress old habits" — [CACM 2022](https://cacmb4.acm.org/magazines/2022/3/258915-here-we-go-again)
- Practitioner essay (Steve Francia / spf13, Nov 2025): language is "the single most expensive choice a company makes," yet decided by identity and ego; gatekeeping by language; cites no data — [Conffab](https://conffab.com/elsewhere/why-engineers-cant-be-rational-about-programming-languages/)
- Conference-talk genre on "dev tribes" exists ("Sacred Syntax: Dev Tribes, Programming Languages, and Cultural Code," PHP Conference NL; "You're in a code cult and that's OK," Sessionize) — anecdotal, no empirical content — [phpconference.nl](https://phpconference.nl/session/sacred-syntax-dev-tribes-programming-languages-and-cultural-code/); [Sessionize](https://sessionize.com/s/serges-goma/youre-in-a-code-cult-and-thats-ok/106481)

### Inferences
- The Ray→Berger episode is the clearest documented case of language culture operating on belief: a weak-to-null association was consumed as causal by 87% of citers because it confirmed existing tribal priors (static vs dynamic, functional vs imperative). This is noise at the ecosystem level: language-selection decisions (and the rewrites they trigger) are justified by evidence that does not exist.
- Stefik–Siebert's placebo result implies that a large fraction of surface syntax carries no measurable cognitive benefit over random symbols for newcomers; its persistence is cultural inheritance (C lineage), not cognition.
- Shrestha et al.'s 61% interference rate means multi-surface ecosystems impose a real cognitive tax that is purely an artefact of surface diversity; a single canonical Form with projections eliminates the mapping problem rather than multiplying it.
- Meyerovich–Rabkin's "observability barrier" is the key adoption lesson for RCE: a Form whose benefits (energy, provability) are not observable at the point of authoring will not be adopted on merit; it must arrive via libraries/ecosystem and a niche.

### Gaps
- No peer-reviewed empirical study of "programming language tribalism" or flame-war dynamics per se was found; the literature is talks and essays. Stack Overflow / Octoverse surveys were not consulted (flagged weak in the brief).
- Hanenberg's controlled static/dynamic typing experiments (OOPSLA 2010 and later) not fetched; would complement Stefik–Siebert.

## KQ2. Notation as culture: Iverson, APL, Lisp, PEP 8/20, gofmt, tabs vs spaces, aesthetics and craft framing

### Takeaway
The notation traditions each claim a cognitive justification but behave as identity markers: APL's terseness, Lisp's parentheses, Python's "readability counts," Go's enforced sameness, and "software craftsmanship" are all positions that define a community as much as a style. Human preference for "natural"/familiar forms is empirically real (Casalnuovo 2020), which means readability norms are partly a familiarity loop rather than a fixed cognitive constant.

### Cited Findings
- Iverson, "Notation as a Tool of Thought" (ACM Turing Award lecture 1979; CACM 23(8), 1980): argues notation should be a tool of thought with properties such as ease of expression, suggestivity, subordination of detail, economy, amenability to formal proof; APL as exemplar — [ACM DL](https://dl.acm.org/doi/10.1145/358896.358899) (not fetched this session)
- Casalnuovo, Lee, Wang, Devanbu, Morgan, "Do People Prefer 'Natural' Code?" (2019/2020): corpus study on top-starred Java/Python GitHub projects — original code was assigned lower surprisal than meaning-preserving rewrites (Java arithmetic swaps: original ~1.68× more probable under global n-gram, ~8× under cache model); human study (50 valid MTurk participants) agreed with the language model's preference 61.9% of the time (65.6% by majority vote), ~80% on relational swaps; humans often preferred extra parentheses regardless of the model. Core claim: "developers still prefer it to be coded in more familiar forms"; code is "bimodal: it is executed by machines, but also read by humans" — [arXiv 1910.03704](https://ar5iv.arxiv.org/html/1910.03704)
- Hindle et al., "On the Naturalness of Software" (ICSE 2012): code is highly repetitive and more predictable than natural language — cited within the above — [arXiv 1910.03704](https://ar5iv.arxiv.org/html/1910.03704)
- PEP 20, "The Zen of Python" (Tim Peters, 2004): "Readability counts"; "There should be one-- and preferably only one --obvious way to do it" — [peps.python.org/pep-0020](https://peps.python.org/pep-0020/) (not fetched)
- PEP 8 (2001): "code is read much more often than it is written" — [peps.python.org/pep-0008](https://peps.python.org/pep-0008/) (not fetched)
- PEP 3131 (2007) permitted non-ASCII identifiers in Python 3, i.e., the language community explicitly chose to allow non-English identifiers while the standard library stays ASCII — [peps.python.org/pep-3131](https://peps.python.org/pep-3131/) (search hit; not fetched)
- Rust RFC 2457 (2018) likewise allowed non-ASCII identifiers — [rust-lang RFC 2457](https://rust-lang.github.io/rfcs/2457-non-ascii-idents.html) (search hit; not fetched)
- Go proverb (Rob Pike, 2015): "Gofmt's style is no one's favorite, yet gofmt is everyone's favorite" — [go-proverbs](https://go-proverbs.github.io/) (not fetched)
- Stack Overflow blog, "Developers Who Use Spaces Make More Money Than Those Who Use Tabs" (David Robinson, June 2017): 2017 survey analysis; spaces users reported ~8.6% higher salary, effect persisted after controls — [Stack Overflow blog](https://stackoverflow.blog/2017/06/15/developers-use-spaces-make-money-use-tabs/) (not fetched)
- Knuth, "Literate Programming" (The Computer Journal 27(2), 1984): programs as works of literature addressed to humans; code order subordinated to exposition — [literateprogramming.com PDF](http://www.literateprogramming.com/knuthweb.pdf) (not fetched)
- Gabriel, *Patterns of Software* (Oxford UP, 1996): "habitability" of code; software as something people live in — [dreamsongs.com PDF](https://www.dreamsongs.com/Files/PatternsOfSoftware.pdf) (not fetched)
- McBreen, *Software Craftsmanship* (Addison-Wesley 2001) and "Manifesto for Software Craftsmanship" (2009): "Not only working software, but also well-crafted software" — [manifesto.softwarecraftsmanship.org](https://manifesto.softwarecraftsmanship.org/) (not fetched)
- "The Hidden Cost of Readability" (ICSE 2026; arXiv Aug 2025): measured formatting share of tokens per language under the GPT-4o tokenizer across 100k files each: Java 14.7%, C# 13.2%, C++ 13.2%, Python 4.0% — [arXiv 2508.13666](https://arxiv.org/html/2508.13666v1)

### Inferences
- Casalnuovo's result cuts both ways for RCE: human readability preference tracks statistical familiarity, which is exactly what a language model also tracks. "Readable to humans" and "low-surprisal to models" are largely the same thing today — but only because models were trained on human code. A canonical Form changes the training distribution and therefore the readability equilibrium.
- gofmt and PEP 8 are evidence that communities will accept a style "no one's favorite" if it removes the identity argument. That is the social precedent for a canonical Form: the win was not the style, it was the elimination of the debate.
- Formatting whitespace is an explicit, measurable cultural tax (4–15% of tokens depending on language) that carries zero semantic content; it is the most tractable noise to drop in a projection.
- Craft/guild framing (literate programming, habitability, craftsmanship) assigns value to the artefact's legibility as a human product. Under model authorship that value either migrates to the Form's proofs/invariants or becomes pure identity.

### Gaps
- No controlled study found quantifying how much reading time formatting conventions actually save humans (vs. familiarity). Buse & Weimer 2010 / Scalabrino 2018 readability metrics and Oliveira et al. 2020 review ("Evaluating Code Readability and Legibility") were not fetched.
- Lisp-parentheses-as-identity has no empirical source; only folklore (xkcd 297, 2007) — not cited as evidence.

## KQ3. Linguistic relativity in programming and natural-language effects (English dominance, non-native naming)

### Takeaway
The strong Whorfian claim (first language mutilates the mind) is rhetoric; the measurable effect is interference: prior-language habits cause 61% of cross-language Stack Overflow errors. English dominance is a real, quantified barrier for the majority of the world's programmers, and non-English identifiers/comments are common in industry code (half of studied industrial systems) while nearly absent from open source — a selection/survivorship effect, not a usage preference.

### Cited Findings
- Dijkstra, EWD498 "How do we tell truths that might hurt?" (1975): "It is practically impossible to teach good programming to students that have had a prior exposure to BASIC: as potential programmers they are mentally mutilated beyond hope of regeneration" — [UT Austin EWD archive](https://www.cs.utexas.edu/users/EWD/transcriptions/EWD04xx/EWD498.html) (not fetched)
- Shrestha, Barik, Parnin (ICSE 2020): 61% of 450 cross-language SO posts carried incorrect assumptions from a prior language; interviewees "had to go and learn that stuff from scratch" (Rust ownership) — [CACM 2022](https://cacmb4.acm.org/magazines/2022/3/258915-here-we-go-again)
- Guo, "Non-Native English Speakers Learning Computer Programming: Barriers, Desires, and Design Opportunities" (CHI 2018): 840 survey responses, 86 countries, 74 native languages; barriers = reading instructional materials, technical communication, reading/writing code, learning English and programming simultaneously; desires = simplified English without slang, more visuals, culturally neutral examples, inline dictionaries; "the majority of programming languages, libraries, documentation, and instructional materials are in English" — [UCSD PDF/text](https://pg.ucsd.edu/publications/non-native-english-speakers-learning-programming_CHI-2018.txt)
- Pawelka & Juergens, "Is This Code Written in English? A Study of the Natural Language of Comments and Identifiers in Practice" (ICSME 2015): 23 systems (13 OSS, 10 industry); non-English content found only in industry; 5 of 10 industry projects had non-English comments or identifiers; non-English comments 50–~90% in five systems; non-English identifiers 28–45% in three; no project had non-English identifiers without non-English comments; identifiers ≈70% of code by the authors' account; language identifier F0.5 0.986 on comments, 0.941 on identifiers — [Teamscale PDF](https://teamscale.com/hubfs/26978363/Publications/2015-is-this-code-written-in-english-a-study-of-the-natural-language-of-comments-and-identifiers-in-practice.pdf?hsLang=en)
- Piech & Abu-El-Haija, "Human Languages in Source Code: Auto-Translation for Localized Instruction" (2019): of 1.1M GitHub users, 12.7% wrote non-English commit messages (Chinese 28.6% of those); 90% of non-English writers also use that language in comments/identifiers; 87.2% of Spanish speakers' projects use Spanish identifiers vs 23.3% of Chinese speakers' projects using Chinese identifiers; non-Latin-script users use English identifiers in 82% of projects vs 12% for Latin-alphabet users; 93% of Chinese-speaker projects ASCII-only identifiers; only 0.6% of RTL-country repos contain Arabic/Hebrew identifiers or comments; authors attribute underrepresentation of non-English users on GitHub to survivorship bias — [arXiv 1909.04556](https://ar5iv.arxiv.org/html/1909.04556)

### Inferences
- The "first language shapes later code" claim is supported in its weak form (interference, 61%), not its strong form (permanent mutilation). Interference is a cost of surface multiplicity, which is an argument for one Form and projected surfaces that are explicitly derived rather than independently learned.
- English keyword dominance is a cultural layer that doubles as a cognitive tax for roughly the non-anglophone majority; the ASCII-transliteration behaviour of Chinese and RTL-script programmers (93%, 99.4%) shows people conform to tooling and community expectation over their own language — identity-by-conformity. A Form with no natural-language keywords, where identifiers are content-addressed and surfaced in the reader's language, removes this layer entirely.
- Non-English identifiers are concentrated in industrial, domain-specific code (insurance terminology etc.): the "noise" here is domain vocabulary, which must survive projection as metadata, not as tokens in the Form.

### Gaps
- No controlled study found on whether non-native naming measurably raises defect rates or review time (Pawelka–Juergens argue it hampers comprehension but do not measure).
- Wadler's and Iverson's Whorfian positions not sourced to a specific text this session.
- No 2024–2026 study found on LLM comprehension of non-English identifiers vs English (would be directly relevant to whether model readers inherit the English-dominance bias).

## KQ4. "Programs must be written for people to read" and its inversion under model authorship (2024–2026)

### Takeaway
Under current frontier models, human-oriented formatting is 4–15% of input tokens (≈25% reducible on average) with no significant loss in code-completion accuracy, and models themselves show a massive culturally-inherited bias (Python in 90–97% of unspecified-language solutions). But format restriction demonstrably hurts reasoning (JSON-mode GSM8K drops of 27–63 points on some models), and models keep emitting human formatting unless prompted or fine-tuned — the "written for people" premise is loosening at the artefact level, not at the reasoning level.

### Cited Findings
- Abelson & Sussman, *SICP* (MIT Press, 1985; 2nd ed. 1996), preface: "programs must be written for people to read, and only incidentally for machines to execute" — [SICP full text](https://mitp-content-server.mit.edu/books/content/sectbyfn/books_pres_0/6515/sicp.zip/full-text/book/book-Z-H-7.html) (not fetched)
- "The Hidden Cost of Readability: How Code Formatting Silently Consumes Your LLM Budget" (Dehghan et al.?, arXiv 2508.13666, Aug 2025; accepted ICSE 2026): Fill-in-the-Middle on McEval (Java 355, C# 318, C++ 314, Python 330) across 10 LLMs; removing formatting cut input tokens 24.5% on average (Java 34.9%, C++ 31.1%, C# 25.3%, Python 6.5%); "performance ... remains largely unaffected" — largest Pass@1 drop 4.2% (Phi-3.5, C++), none statistically significant; DeepSeek-V3 79.1% formatted vs 80.0% unformatted; GPT-4o rose 66.4→71.5% on Python. Output tokens only fell ~2.5% unprompted ("models tend to keep their own formatting style"); prompting cut GPT-4o output 27.2% (up to 36.1% Java); fine-tuning on 50 unformatted Java samples cut output 35.9% (Gemini) / 24.8% (GPT-4o) with Pass@1 unchanged within noise; but prompting can backfire (Gemini-1.5 C++ Pass@1 67.2→11.1% under one prompt). Tool released with 100% AST equivalence — [arXiv 2508.13666](https://arxiv.org/html/2508.13666v1); [ICSE 2026 listing](https://conf.researchr.org/details/icse-2026/icse-2026-research-track/39/The-Hidden-Cost-of-Readability-How-Code-Formatting-Silently-Consumes-Your-LLM-Budget)
- "Token Sugar: Making Source Code Sweeter for LLMs through Token-Efficient Shorthand" (arXiv 2512.08266, Dec 2025): proposes shorthand surface syntax for token economy — [arXiv 2512.08266](https://arxiv.org/html/2512.08266v1) (search hit; not fetched; findings unknown)
- "LLMs Love Python: A Study of LLMs' Bias for Programming Languages and Libraries" (arXiv 2503.17181, Mar 2025): 8 models (GPT-4o, GPT-3.5, Claude 3.5 Sonnet/Haiku, Llama 3.2, Qwen 2.5, DeepSeek, Mistral 7B); Python used for 90–97% of benchmark problems when language unspecified; 58% in project-initialisation tasks where Python is unsuitable; no model used Rust for any of five high-performance tasks; models used only 6–14 languages and 32–39 libraries; NumPy imported unnecessarily in 48% of its uses; models contradicted their own language recommendations in 83% of cases — [arXiv 2503.17181](https://arxiv.org/html/2503.17181v1)
- Follow-on practitioner benchmark "LangChoiceBench" (Aug 2026) on Python over-selection in coding agents and the effect of an AGENTS.md language directive — [codex.danielvaughan.com](https://codex.danielvaughan.com/2026/08/09/langchoicebench-python-over-selection-bias-llm-coding-agents-codex-cli-agents-md-language-directive/) (search hit; not fetched; unverified)
- Tam et al., "Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performance of LLMs" (EMNLP Industry 2024; arXiv 2408.02442): GSM8K — GPT-3.5 Turbo text 76.6 vs JSON 49.3; Claude 3 Haiku text 86.5 vs JSON 23.4 (60% parsing errors); Llama 3 8B 74.7 vs 48.9; Last Letter — Llama 3 8B 70.1 vs JSON 28.0; GPT-3.5 56.7 vs 25.2, traced to "100% of GPT 3.5 Turbo JSON-mode responses placed the 'answer' key before the 'reason' key." Removing the schema from the prompt restored Claude's JSON score 23.4→87.0. Classification tasks improved under JSON (DDXPlus Gemini 41.6→60.4). Six models, six datasets — [arXiv 2408.02442](https://arxiv.org/html/2408.02442v1)
- agentlanguages.dev (community catalogue, ~30 languages, taxonomy from "Three camps alike in dignity," Negroni Venture Studios, May 2026; page as of 19 Oct 2026): Syntactic camp examples — Codong (Mar 2026: one canonical way to express each operation, structured JSON errors with fix/retry fields; 73 stars), Tacit (Apr 2026: "the AST is the source of truth," canonical text, content-addressed definitions, explicit effects; 4 stars), X07 (Apr 2026: programs are JSON ASTs edited via JSON Patch with deterministic quickfixes), Magpie (Apr 2026: SSA as surface syntax), Mog (Mar 2026: spec fits in ~3,200 tokens), Axis (May 2026: LL(1) grammar for 1B–7B models), NERD (Jan 2026: English keywords instead of operators). Verification camp — Vera (Feb 2026: Z3-checked contracts, typed slot references instead of variable names; 418 stars), Vow (ESBMC-discharged "vows"), MoonBit (2023; ICSE 2024 semantics-aware token sampling). Orchestration — Boruna (hash-chained evidence bundles), Plasm. Catalogue is descriptive and does not verify token/readability claims; Faber Romanus (Jul 2026) explicitly positions as "for agents to write and humans to read" — [agentlanguages.dev](https://agentlanguages.dev/); [CLAUDE.md mirror](https://tomevault.io/tome/aallan/agentlanguages)
- "Tokenmaxxing" (term "became common in 2026"): maximising AI token usage as a proxy for productivity/adoption; examples include agent loops that fail to converge and verbose unused output; opposite is token economics tied to accepted work, not minimising spend; cites Guardian (30 Jul 2026) on Atlassian tightening AI-use tracking — [promptmetheus glossary](https://promptmetheus.com/resources/llm-knowledge-base/tokenmaxxing) (secondary source; Guardian not verified)
- Casalnuovo 2020: human preference and LM surprisal agree ~62–66% — i.e., model and human "readability" are correlated but far from identical; humans over-prefer parentheses — [arXiv 1910.03704](https://ar5iv.arxiv.org/html/1910.03704)

### Inferences
- The inversion is partial and layered. (a) Artefact layer: formatting/whitespace is already pure cost for model readers (≈25% of input, nil accuracy effect). (b) Reasoning layer: forcing a rigid output schema during generation costs accuracy, and the mechanism is specific (key order forcing answer-before-reason, schema-in-prompt). The reconciling design is "reason freely, emit canonically" — generation in free text, then a deterministic transform to the Form (the Hidden-Cost paper's 100%-AST-equivalent bidirectional tool is a prototype of exactly this).
- "LLMs Love Python" shows models are not culture-free readers: they inherited the dominant human tribe's defaults and amplify them (90–97% Python, 0% Rust where Rust is appropriate). A Form-first ecosystem does not escape culture by removing humans; it has to escape the training-corpus prior explicitly.
- The agentlanguages catalogue is thin evidence of practice (star counts 3–418) but strong evidence of direction: within 2026, independent designers converged on content-addressed definitions, AST-as-source, one-canonical-way, structured errors, explicit effects — the RCE Form's premises restated by others. Faber Romanus's "agents write, humans read" is the counter-position within the same catalogue.
- Models "keep their own formatting style in output regardless of input" — the human-readability convention is baked into model priors and must be removed by fine-tuning or prompting; it is cultural inheritance at the weight level.

### Gaps
- No study found that measures model *comprehension or editing* accuracy on a JSON-AST surface vs text surface at scale (the Hidden-Cost paper covers whitespace only; X07/Tacit are unevaluated).
- Octoverse/Stack Overflow 2024–2026 "Python overtook JavaScript" signal not consulted (flagged weak).
- No evidence found on whether human auditors can review canonical-Form or projected code as effectively as native text; the "humans still audit" counter-evidence is asserted in the brief, not measured in anything I found.
- Token Sugar findings not extracted.

## KQ5. History of removing the human from the surface: UNCOL, CASE, UML/MDA, low-code, visual programming

### Takeaway
Every prior attempt to make the human-facing surface derivative failed or stalled for social reasons, not technical ones: Hutchinson et al. (ICSE 2011) found MDE's code-generation gains (typically 20–30%) do not justify the organisational change, that "social and organizational factors are at least as important ... as technical ones," and that "most projects fail at scale-up"; the successes were narrow DSLs built bottom-up. Visual programming succeeded only where the notation matched a bounded domain and audience.

### Cited Findings
- Hutchinson, Whittle, Rouncefield, Kristoffersen, "Empirical Assessment of MDE in Industry" (ICSE 2011) and companion "MDE Practices in Industry": 450-respondent survey (36% developers, 37% project managers; 52% at firms <100 staff) + 22 interviews across 17 companies in 9 sectors (>150k words of transcript); reported productivity from −27% to +800%, most 20–30%; "the authors conclude that gains of that size don't justify the training costs and organizational change"; real benefit is architectural ("documenting a good software architecture"); bottom-up adoption succeeds, top-down mandates fail; code gurus resist (fear losing importance), hobbyist developers resist (fear losing creative freedom), middle managers are bottlenecks; hiring favours technology familiarity over domain knowledge; one firm estimated only ~3% of coders can think abstractly (authors call this unscientific); "Most projects fail at scale-up"; "Don't obsess about code generation"; watch for "higher certification costs for poorly readable generated code" — [InfoQ summary by the authors](https://www.infoq.com/articles/the-state-of-practice-in-model-driven-engineering); [ICSE 2011 listing](https://2011.icse-conferences.org/content/empirical-assessment-mde-industry.html); [Lancaster eprint](https://eprints.lancs.ac.uk/id/eprint/57678)
- Petre, "Why Looking Isn't Always Seeing: Readership Skills and Graphical Programming" (CACM 38(6), June 1995): graphical readership is a learned skill; experts exploit "secondary notation" (layout) that novices cannot see; visual programs are not inherently easier to read — [CACM abstract](https://cacmb4.acm.org/magazines/1995/6/8808-why-looking-isnt-always-seeing/abstract) (fetch blocked; claims from memory, verify)
- Low-code: industry reports (Kissflow "CIO Low-Code Strategy Pulse 2025," Hostinger "26 low-code trends," KPMG 2024) exist; none fetched; all vendor/analyst-sourced — [Kissflow](https://kissflow.com/cio-reports); [KPMG](https://kpmg.com/cy/en/home/insights/2024/01/how-low-code-platforms-are-driving-digital-transformation.html) (unverified, low quality)

### Inferences
- The MDE failure mode is a prediction for RCE: generated/projected surfaces that humans cannot audit raise certification cost (Hutchinson's explicit warning), and status actors (code gurus) resist losing the artefact that carries their identity. RCE's answer must be that the Form is more auditable than the surface (proofs attached), not less.
- The MDE successes were small DSLs built in ~two weeks by domain teams: narrow, bottom-up, domain-vocabulary-rich. This matches Meyerovich–Rabkin's niche-by-niche adoption and suggests RCE's path is projections per domain, not a universal surface replacement.
- UNCOL (1958), CASE (1980s–90s) and executable UML (2001–2010s) share the pattern of a universal intermediate owned by tool vendors; the social failure was lock-in and loss of the human-editable artefact. A CC0/open Form with deterministic bidirectional projection addresses the lock-in half directly.

### Gaps
- UNCOL (Strong et al. CACM 1958), CASE tool failure literature, Scratch (Resnick et al. CACM 2009) and LabVIEW adoption were not sourced this session; included only as framing.
- No independent (non-vendor) quantitative source found on low-code abandonment or governance failure 2015–2026.
- Whitley 1997 ("Visual programming languages and the empirical evidence for and against") and Green & Petre 1996 cognitive-dimensions framework not fetched.

## KQ6. Error and blame culture: how blame, safety regimes and "move fast" shape ceremony and defensive redundancy

### Takeaway
Blame cultures suppress the detail needed to fix systems (Allspaw 2012, after Dekker), while safety cultures encode redundancy as mandatory ceremony (JPL Power of 10: fixed loop bounds, no recursion, ≥2 assertions per function, zero warnings). Both are organisational responses to the absence of proof; code carries their residue as ritual.

### Cited Findings
- Allspaw, "Blameless PostMortems and a Just Culture" (Etsy Code as Craft, 22 May 2012): engineers must give accounts "without fear of punishment or retribution"; blame hides the conditions that cause failures; cites Sidney Dekker's "Bad Apple Theory" ("get rid of the bad apples, and you'll get rid of the human error"); "Having a Just Culture means that you're making effort to balance safety and accountability" — [Etsy Code as Craft](https://www.etsy.com/codeascraft/blameless-postmortems)
- Holzmann, "The Power of 10: Rules for Developing Safety-Critical Code" (IEEE Computer, June 2006; JPL): restrict to simple control flow (no goto/recursion), fixed upper bounds on loops, no dynamic memory after init, functions ≤ ~60 lines, minimum two assertions per function, declare data at smallest scope, check all return values, limit preprocessor, restrict pointers, compile with all warnings and pass static analysis daily — [Wikipedia summary](https://en.wikipedia.org/wiki/The_Power_of_10:_Rules_for_Developing_Safety-Critical_Code); [PDF mirror](https://www.eecs.umich.edu/~imarkov/10rules.pdf) (not fetched; rules from memory, consistent with search hits)
- Perrow, *Normal Accidents* (1984): tightly-coupled, interactively complex systems produce accidents as a normal property — framing only (not fetched)
- Leveson, *Engineering a Safer World* / STAMP (MIT Press 2011, open access): accidents as control-structure failures, not component failures — framing only (not fetched)
- Hutchinson 2011 notes safety-adjacent cost of generated code: "higher certification costs for poorly readable generated code" — [InfoQ](https://www.infoq.com/articles/the-state-of-practice-in-model-driven-engineering)

### Inferences
- Defensive ceremony (assertion density, bounded loops, return-value checks, warning-free builds) is the safety culture's substitute for proof. Where the Form carries machine-checked invariants (Vera/Vow-style contracts, or RCE's provable correctness), the ceremony is redundant *as text* but its function (evidence for a certifier) must be preserved as attached proof artefacts.
- Blameless culture is about preserving information flow after failure. In a Form-first ecosystem with reversibility as the safety mechanism, the postmortem's raw material (what the author knew, the sequence of edits) is natively available as content-addressed history; the cultural ritual becomes a query.
- Certification regimes (DO-178C-style) demand human-reviewable artefacts; this is the hardest cultural function to let go, because the auditor's trust is in a human reading, not a proof — the same observability barrier Meyerovich–Rabkin describe.

### Gaps
- DO-178C objectives and MC/DC coverage requirements not sourced this session.
- No study found quantifying how much code volume is defensive/ceremonial under safety standards vs "move fast" regimes.
- "Move fast and break things" (Facebook motto, retired 2014) not sourced.

## KQ7. Anthropology of maintenance: low status, rewrite preference, Chesterton's fence

### Takeaway
Maintenance is systematically under-valued relative to innovation (Vinsel & Russell 2020), rewrites are preferred to understanding (Spolsky 2000 calls full rewrites "the single worst strategic mistake"), and Chesterton's fence persists as the norm because code carries undocumented reasons. These are culture-level responses to a Form that does not record intent.

### Cited Findings
- Vinsel & Russell, *The Innovation Delusion: How Our Obsession with the New Has Disrupted the Work That Matters Most* (Currency, Sept 2020): "innovation-speak" devalues maintenance; the Maintainers movement — [Kirk Center review](https://kirkcenter.org/reviews/in-defense-of-maintenance/); [CHM blog](https://computerhistory.org/blog/decoding-innovation/) (search hits; not fetched)
- Spolsky, "Things You Should Never Do, Part I" (Joel on Software, 6 April 2000): rewriting from scratch is "the single worst strategic mistake"; old code's ugliness is accumulated bug fixes ("It's harder to read code than to write it"); Netscape 6 example — [joelonsoftware.com](https://www.joelonsoftware.com/2000/04/06/things-you-should-never-do-part-i/) (not fetched; quotes from memory)
- Chesterton, *The Thing* (1929), "The Drift from Domesticity": do not remove a fence until you know why it was put there — framing only (not fetched)
- Hutchinson 2011: "code gurus" resist MDE because they fear losing importance — status attaches to the surface artefact — [InfoQ](https://www.infoq.com/articles/the-state-of-practice-in-model-driven-engineering)

### Inferences
- Spolsky's argument is that ugly code is compressed history whose reasons are not recorded in the Form; Chesterton's fence is the same point. Both norms exist because the artefact does not carry provenance. A Form with content-addressed definitions and recorded intent/proof makes "why is this here" answerable mechanically, which dissolves the rewrite-vs-delete dilemma: deletion is safe when the invariant that justified the code is machine-checkable, and reversible otherwise.
- Maintenance's low status is tied to the illegibility of its output (no new artefact). If energy/correctness deltas on the Form are first-class and attributable, maintenance becomes a measurable contribution — a status fix via instrumentation rather than exhortation.

### Gaps
- Vinsel & Russell's specific claims and data not extracted (reviews only).
- No empirical study found on rewrite frequency or the share of maintenance effort attributable to lost rationale.

## KQ8. Which cultural functions of code must a Form-first ecosystem still serve, and which can it let go?

### Takeaway
The evidence partitions cleanly: functions that encode *information* (trust/audit, teaching, domain vocabulary, failure provenance) must be served, by the Form or its attachments; functions that encode *affiliation* (notation-as-identity, formatting conventions, language tribe, craft aesthetics, English-keyword norms) are pure noise and can be dropped — with the caveat that models currently inherit those affiliations from their training corpus and must be de-biased explicitly.

### Cited Findings
- Audit/certification requires human-reviewable artefacts; generated code raised certification costs — [Hutchinson 2011 via InfoQ](https://www.infoq.com/articles/the-state-of-practice-in-model-driven-engineering)
- Trust after failure requires information flow that blame suppresses — [Allspaw 2012](https://www.etsy.com/codeascraft/blameless-postmortems)
- Teaching: novice accuracy depends on syntax choices (C-style no better than random) and on English proficiency (840 learners, 86 countries) — [Stefik & Siebert 2013](https://neverworkintheory.org/2014/01/29/stefik-siebert-syntax.html); [Guo 2018](https://pg.ucsd.edu/publications/non-native-english-speakers-learning-programming_CHI-2018.txt)
- Domain vocabulary legitimately lives in identifiers (insurance terms etc.) — [Pawelka & Juergens 2015](https://teamscale.com/hubfs/26978363/Publications/2015-is-this-code-written-in-english-a-study-of-the-natural-language-of-comments-and-identifiers-in-practice.pdf?hsLang=en)
- Identity/affiliation functions have no measured benefit: language-quality causation unsupported (4 of 11 survive, tiny effect) — [Berger 2019](https://arxiv.org/abs/1901.10220); formatting removal costs nothing in model accuracy — [Hidden Cost 2025](https://arxiv.org/html/2508.13666v1); adoption driven by ecosystem not features — [Meyerovich & Rabkin 2013](https://vivekhaldar.com/articles/empirical-analysis-of-programming-language-adoption)
- Reasoning needs free form during generation; canonical form must be applied after — [Tam et al. 2024](https://arxiv.org/html/2408.02442v1)
- Models carry the dominant tribe's bias (Python 90–97%) — [LLMs Love Python 2025](https://arxiv.org/html/2503.17181v1)

### Inferences
Must still serve (and how):
1. Trust and audit — the function is "a certifier can convince themselves." Serve it with attached proofs/invariants and a deterministic, AST-equivalent projection to a human surface on demand (the Hidden-Cost tool and Tacit's "canonical text" are precedents). Do not assume proofs alone satisfy auditors; the observability barrier is real.
2. Failure provenance (blameless postmortem material) — serve natively via content-addressed history and recorded intent; this replaces the ritual with a query.
3. Teaching — a projection for learners that is usability-tested (Stefik–Siebert's method) and language-localised (Guo; Piech). Teaching is a projection, not a property of the Form.
4. Domain vocabulary — preserve as metadata bound to content-addressed definitions, projected in the reader's language; never as keyword tokens.
5. Identity, redirected — people will still affiliate; let them affiliate with projections (a Go-style or APL-style view) with zero effect on the Form, the way gofmt removed the argument by making it irrelevant.

Can let go:
1. Formatting conventions and whitespace as content (4–15% of tokens, zero semantic value).
2. Language tribe as a quality signal (no evidence survives reproduction).
3. English as the keyword/identifier language (pure barrier for the non-anglophone majority; transliteration behaviour shows it is conformity, not preference).
4. Craft aesthetics of the surface (habitability, literate ordering) — their informational residue (intent, rationale) moves into the Form; their affiliative residue is noise.
5. Defensive ceremony as text (assertion density, bounded-loop rules) where the Form carries the equivalent machine-checked invariant.
6. Rewrite-over-delete and Chesterton's fence as norms, once rationale is recorded and deletion is reversible.

Does the "written for people" premise invert? Partially. At the artefact level, yes: the dominant reader and author is a model, formatting is cost, and 2026 agent-language designers independently converged on AST-as-source and one-canonical-way. At the reasoning level, no: free-form generation still outperforms constrained generation, so "reason freely, commit canonically" is the design. And at the ecosystem level, not automatically: models reproduce human culture (Python bias, retained formatting), so a Form-first system has to counter the inherited prior rather than rely on the absence of humans.

### Gaps
- No direct evidence on human audit effectiveness over projected vs native surfaces.
- No empirical measure of how much of total code volume is attributable to each cultural function (formatting is the only quantified slice, at ~4–15% of tokens).
