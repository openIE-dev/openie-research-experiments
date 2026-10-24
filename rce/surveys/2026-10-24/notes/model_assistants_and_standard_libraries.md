# Working note 17: LLM code assistants' reuse of standard libraries, and the low-resource penalty for new languages

Raised by the completeness critic: The knowledge-of-available-APIs strand concluded that 'standard-library use by LLMs is unmeasured here.' Two kinds of claim the synthesis may want to make both depend on that measurement. One is that a single shipped library makes available functionality discoverable for code agents. The other concerns whether a new universal language and library could be adopted, given the 111 new-entrant languages surveyed. Both need evidence on whether assistants reuse stdlib functions or reimplement them or import packages, and on how code-model accuracy falls for low-resource and newly released languages.

Written 24 October 2026 by a research agent with web search; github.com was reachable and most other hosts were not, so many sources were confirmed from search extracts, as each bullet says. Not independently re-verified claim by claim, unlike notes 7 and 8.

**How I got the sources.** No web searches ran because the session's search budget was already used up when this task started, so no claim below rests on search extracts. arxiv.org, ACL Anthology, OpenReview, Hugging Face, figshare, Zenodo and usenix.org were all unreachable. Every figure below comes from the authors' own GitHub repositories (READMEs, released data files, and paper PDF or LaTeX kept in the repo). Where I computed a number myself from released data, I say so. I could not check the full paper text for most candidates.

**(a) Do code generators reuse the standard library, reimplement it, or import third-party packages?**

- **LLM library preferences.** Eight LLMs overuse widely adopted libraries such as NumPy, and in up to 48% of cases that use is unnecessary and departs from the ground-truth solution (the authors' poster says "up to 45%"). Each LLM used only 32–39 distinct libraries, and the slides show pandas in 58% of tasks and Polars in 0%.
  - **Caveat from the released data:** all 525 BigCodeBench-derived library prompts, including the three ablation variants, contain "Choose, import and use at least one external library". Every ground-truth solution in that subset also uses an external library, and the import extractor removes standard-library modules by default (`sys.stdlib_module_names`). So this study measures which third-party library gets chosen, not whether the standard library would have been used.
  - Citation: Lukas Twist, Mark Harman, Don Syme, Joost Noppen, Helen Yannakoudakis, Detlef Nauck, Jie M. Zhang, "A Study of LLMs' Preferences for Libraries and Programming Languages" (arXiv title "LLMs Love Python…", arXiv:2503.17181), Findings of ACL 2026, pp. 331–351, doi:10.18653/v1/2026.findings-acl.15; https://github.com/itsluketwist/llm-code-bias

- **BigCodeBench.** The benchmark has 1,140 tasks using 139 libraries: 281 calls from 77 standard-library modules and 442 calls from 62 external libraries. The best of 60 LLMs scored up to 60% against 97% for humans.
  - Table 2: the generated solution's library set stays within the ground-truth set in 79.84% of passing and 71.78% of failing solutions. Its function calls stay within the ground truth in only 40.46% (passing) and 22.47% (failing).
  - The authors say the extra libraries that models import are "mostly standard". That is added standard-library use, not reimplementation.
  - Domain results are qualitative only: models do better on computation, cryptography and general tasks and fail often on network tasks. The text gives no per-library failure rates.
  - Citation: Terry Yue Zhuo, Chien Vu, Jenny Chim, et al. (33 authors), "BigCodeBench: Benchmarking Code Generation with Diverse Function Calls and Complex Instructions," ICLR 2025, arXiv:2406.15877. Figures are from the preprint PDF at https://github.com/bigcode-bench/bigcode-bench.github.io (paper.pdf).

- **Library usage in agent-authored pull requests (26,760 PRs).** 29.5% of PRs import libraries, but only 1.3% add new dependencies, and 75.0% of added dependencies specify a version.
  - Per-language rates from the released LaTeX table:

    | Language | PRs importing external libs | PRs importing stdlib | Avg external imports per PR | PRs adding new dependencies |
    |---|---|---|---|---|
    | TypeScript | 38.1% | 11.1% | 1.87 | 0.1% |
    | Python | 26.6% | 33.1% | 0.73 | 2.8% |
    | Go | 3.2% | 12.3% | 0.08 | 0.2% |
    | C# | 37.2% | 37.5% | 0.73 | 6.1% |

  - This is observational: repositories and tasks are not controlled across languages.
  - The released aggregate file reports 0.0% standard-library imports for 1,079 Rust PRs, and Rust is missing from the paper table, so the Rust row cannot be used.
  - Citation: Lukas Twist, Jie M. Zhang, "A Study of Library Usage in Agent-Authored Pull Requests," MSR '26, 2026, doi:10.1145/3793302.3793562; https://github.com/itsluketwist/agent-library-usage

- **Package hallucinations.** Across 16 LLMs and 576,000 Python and JavaScript code samples, 19.7% of recommended packages did not exist, giving 205,474 unique hallucinated names.
  - Released Figure 2 data: JavaScript rates are higher than Python for all 14 models that have both (GPT-4 Turbo 3.35% vs 5.64%; CodeLlama-7B 26.28% vs 37.80%).
  - Released Figure 4 data: prompts based on last year's most popular packages hallucinate more than all-time prompts for all 16 models (GPT-4 Turbo 3.89% vs 3.26%).
  - Citation: Joseph Spracklen, Raveen Wijewickrama, A H M Nazmus Sakib, Anindya Maiti, Bimal Viswanath, Murtuza Jadliwala, "We Have a Package for You! A Comprehensive Analysis of Package Hallucinations by Code Generating LLMs," USENIX Security 2025; https://www.usenix.org/system/files/conference/usenixsecurity25/sec25cycle1-prepub-742-spracklen.pdf; https://github.com/Spracks/PackageHallucination

- **Library hallucinations under realistic prompts (7 LLMs, Python/PyPI).** A one-character misspelling triggers hallucinations in up to 26% of tasks, fabricated library names are accepted in up to 99%, and time-based prompts produce up to 84%.
  - LibHalluBench leaderboard: the control rate is 0.0–0.3%.
  - Asking for libraries "from 2025": GPT-4o-mini 84.4%, GPT-5-mini 64.5%, Qwen2.5-Coder-32B 61.7%, DeepSeek-chat 37.7%, Llama-3.3-70B 1.9%, Claude Haiku 4.5 0.6%.
  - Citation: Lukas Twist, Mark Harman, Helen Yannakoudakis, Jie M. Zhang, "Library Hallucinations in LLM-Generated Code: A Risk Analysis Grounded in Developer Queries," EMNLP 2026, pp. 1785–1812, https://aclanthology.org/2026.emnlp-main.78/, arXiv:2509.22202; https://github.com/itsluketwist/realistic-library-hallucinations

- **LibEvolutionEval (version-specific code completion).** Scores are F1.
  - Adding retrieved documentation for the right version raises StarCoder2-7B from 68.8 to 73.3 on PyTorch and from 69.7 to 75.4 on Matplotlib, and GPT-4o-mini from 52.5 to 66.7 on Matplotlib.
  - CodeGen 1.0 (training cutoff 2022) scores lower on Matplotlib APIs introduced after its cutoff: 56.29 (2022), 44.08 (2023), 41.37 (2024).
  - StarCoder2 scores 38.58–57.14 on deprecated Matplotlib APIs, against 60.12–66.08 overall (2019–2023).
  - Citation: Sachit Kuhar, Wasi Uddin Ahmad, Zijian Wang, Nihal Jain, Haifeng Qian, Baishakhi Ray, Murali Krishna Ramanathan, Xiaofei Ma, Anoop Deoras, "LibEvolutionEval: A Benchmark and Study for Version-Specific Code Generation," NAACL 2025, pp. 6826–6840, https://aclanthology.org/2025.naacl-long.348/; project-page source at https://github.com/lib-evolution-eval/lib-evolution-eval.github.io

- **VersiCode.** The dataset covers 301 Python libraries and 2,208 versions over 9 years, plus small Java, C# and JavaScript sets.
  - Table 3 (an image on the project page, possibly the early preprint version), token-level completion pass@1: GPT-4o 70.44, Llama-3-70B 47.55, GPT-3.5 37.59, open 7–15B code models 13.28–15.71.
  - Block-level ISM@6: GPT-4o 64.73, the open 7–15B code models 0–4.34.
  - Citation: Tongtong Wu, Weigang Wu, Xingyu Wang, Kang Xu, Suyu Ma, Bo Jiang, Ping Yang, Zhenchang Xing, Yuan-Fang Li, Gholamreza Haffari, "VersiCode: Towards Version-controllable Code Generation," arXiv:2406.07411, 2024; https://github.com/wutong8023/VersiCode (docs/)

- **Wang et al., deprecated APIs in code completion.** The replication README confirms the setup: 145 mappings from deprecated APIs to their replacements across 8 Python libraries, 7 models (CodeGen 350M/2B/6B, DeepSeek-1.3B, StarCoder-3B, CodeLlama-7B, GPT-3.5), and "outdated" versus up-to-date code contexts.
  - The deprecated-usage rates are only in the paper and on figshare, which were unreachable, so they are **not verified**.
  - The README calls the work "ASE submission #1438". An awesome-list entry gives an earlier title, arXiv:2406.09834 [secondhand]. The ICSE 2025 venue is not verified here.
  - Citation: Wang et al., "LLMs Meet Library Evolution: Evaluating Deprecated API Usage in LLM-based Code Completion"; https://github.com/cs-wangchong/LLM-Deprecated-API

- **Not verified at all:**
  - CloudAPIBench / "On Mitigating Code LLM Hallucinations with API Documentation" (arXiv:2407.09726): no reachable repository or page.
  - Any measured rate of LLMs reimplementing standard-library functionality: no source found.

**(b) How does accuracy depend on how much training data a language has?**

- **MultiPL-E by language-frequency tier.** I computed these myself from the repo's `results/per_problem_all.csv`, using the authors' High/Medium/Low/Niche labels in `analysis/frequency-map.csv`.
  - HumanEval (reworded), mean pass@1:

    | Model | High | Medium | Low | Niche |
    |---|---|---|---|---|
    | Codex | 46.6% | 37.2% | 36.6% | 27.8% |
    | CodeGen | 19.8% | 7.5% | 3.3% | 3.5% |
    | InCoder | 10.6% | 6.5% | 4.9% | 2.4% |

  - MBPP, Codex: 51.2%, 44.4%, 34.0%, 33.2% for the same four tiers.
  - Individual languages break the pattern: Lua (Niche) scores 40.8% against Go (Medium) at 31.4%, and Rust (Low) scores 43.4% against Python at 46.7%.
  - Citation: Federico Cassano, John Gouwar, Daniel Nguyen, Sydney Nguyen, Luna Phipps-Costin, Donald Pinckney, Ming-Ho Yee, Yangtian Zi, Carolyn Jane Anderson, Molly Q Feldman, Arjun Guha, Michael Greenberg, Abhinav Jangda, "MultiPL-E: A Scalable and Polyglot Approach to Benchmarking Neural Code Generation," IEEE TSE, 2023, doi:10.1109/TSE.2023.3267446; https://github.com/nuprl/MultiPL-E

- **MultiPL-T.** Python code is translated into Racket, Julia, R, OCaml and Lua, and translations are kept only if they pass translated tests.
  - StarCoderBase-1B on Racket goes from 4.7% to 11.3% pass@1 after fine-tuning (Table 2, as quoted in the artifact README).
  - A full reproduction needs about 550 A100-days.
  - Citation: Federico Cassano, John Gouwar, Francesca Lucchetti, Claire Schlesinger, Carolyn Jane Anderson, Molly Q Feldman, Michael Greenberg, Abhinav Jangda, Arjun Guha, "Knowledge Transfer from High-Resource to Low-Resource Programming Languages for Code LLMs," PACMPL (OOPSLA), 2024, arXiv:2308.09895; https://github.com/nuprl/MultiPL-T

- **Language choice (same Twist et al. 2026 paper as in (a)).** Python is the language used in 90–97% of benchmark-task solutions (poster). It is still the dominant choice in 58% of high-performance project-setup tasks, and Rust is never chosen.

- **SWE-AGI on MoonBit [self-reported].** The benchmark was built by MoonBit-affiliated authors.
  - It has 22 tasks, each specified from standards documents and needing 10^3–10^4 lines of code. gpt-5.3-codex solves 19/22 (86.4%), gpt-5.2-codex 17/22, claude-opus-4.6 15/22 (68.2%), and claude-opus-4.5 10/22.
  - The paper says MoonBit is "largely absent from existing large-scale pretraining corpora" but runs no comparison with other languages.
  - Citation: Zhirui Zhang, Hongbo Zhang, Haoxiang Fei, et al. (14 authors), "SWE-AGI: Benchmarking Specification-Driven Software Construction with MoonBit in the Era of Autonomous Agents," arXiv:2602.09447, 2026; https://github.com/moonbitlang/SWE-AGI (paper/main.tex)

- **MoonBit's "AI-friendly" design claims [self-reported].** These blog posts describe the LLM4Code 2024 paper "MoonBit: Explore the Design of an AI-Friendly Programming Language".
  - They claim that a flat top-level structure with mandatory type signatures is "more KV-cache friendly".
  - They claim MoonBit's type-aware sampler gives "a significant improvement in compilation rates" at about a 3% performance cost and about 0.86 s per suggestion fix. No compile-rate figure is given.
  - Citation: MoonBit team, "MoonBit: Exploring the design of an AI-Native Language Toolchain" (2024-02-18) and "The future of programming languages in the era of LLM" (2024-04-18), moonbitlang.com/blog; source at https://github.com/moonbitlang/website (blog/2024-02-18-moonbit-ai, blog/2024-04-18-ai-coding)

- **Mojo, Zig, Gleam:** I found no benchmark I could verify (MojoBench was not reachable). Two Cangjie studies are listed but their contents are not verified [secondhand listing in https://github.com/codefuse-ai/Awesome-Code-LLM]:
  - CangjieBench, arXiv:2603.14501, 2026
  - "Bridging the Knowledge Void", arXiv:2602.06976, 2026

- **Batteries-included versus small-stdlib languages:** none of the sources I could check runs a controlled comparison of how many dependencies LLM-generated code adds in Python or Go versus JavaScript or Rust.
  - The closest is the uncontrolled agent-PR table above (Go adds new dependencies in 0.2% of PRs, TypeScript 0.1%, Python 2.8%), and its Rust row cannot be used.
  - Spracklen et al. compare hallucinated packages in Python and JavaScript, not dependency counts.

**What this establishes**

- Generated code favours a small set of popular third-party libraries: NumPy is unnecessary in up to 48% of cases and pandas beats Polars 58% to 0% (Twist et al. 2026, ACL Findings). BigCodeBench solutions often use function calls outside the ground truth.
- No verified source measures how often generated code uses the standard library versus third-party packages, or reimplements the standard library, when the model is free to choose. The main preference study forces an external library in every prompt (Twist et al. 2026, ACL Findings; Zhuo et al. 2025).
- In real agent pull requests, adding a dependency is rare (1.3%), and external-import rates vary widely by ecosystem: Go 3.2% versus TypeScript 38.1% (Twist & Zhang 2026). JavaScript prompts produce more hallucinated packages than Python prompts for every model tested (Spracklen et al. 2025). No controlled comparison of batteries-included and small-stdlib languages exists in these sources.
- Pass@1 drops as a language's training-data tier falls: Codex goes from 46.6% (High) to 27.8% (Niche) on HumanEval (MultiPL-E data, my calculation). Synthetic data for low-resource languages narrows but does not close the gap: Racket goes from 4.7% to 11.3% (Cassano et al. 2023; 2024). Individual languages such as Lua and Rust buck the tier trend.
- New libraries and APIs are a separate weak point:
  - APIs introduced after a model's training cutoff score lower (Kuhar et al. 2025).
  - Version-specific completion is hard for small models (Wu et al. 2024).
  - Asking for 2025 libraries makes some models hallucinate in 37.7–84.4% of tasks (Twist et al. 2026, EMNLP).
  - Retrieving the right version's documentation helps but does not fix this (Kuhar et al. 2025).
  - The only MoonBit evidence comes from the MoonBit team itself and includes no comparison with other languages (Zhang et al. 2026; MoonBit blog 2024).
