# Survey of 24 October 2026: continuous improvement without versions, and one library on every compute fabric

One survey in two parts, read against the RCE (Reality Code Engine) specification.

The first part asks how a language and its library improve continuously without versions. It is read against the one-language rule (2.7, C.15, decision 64), the definition hashes and manifest of Appendix F (F.4.3, F.5.3), name independence (6.1, T7), replay (T3) and behaviour equivalence (6.10). Its syntheses are `continuous-improvement-without-versions.md` and `new-entrant-languages-2024-2026.md`, written from working notes 1 to 6:

1. software dependency resolution and semantic versioning (`software_dependency_hell.md`);
2. schema and interface evolution and content addressing (`compatibility_theory.md`);
3. hardware change control and continuous improvement (`hardware_change_control.md`);
4. the RCE mechanisms read directly from the repository (`rce_mechanisms.md`);
5. the 72 languages for or by machine authors (`languages_for_machine_authors.md`);
6. the 39 new general-purpose and systems languages and 35 earlier milestones (`new_general_purpose_languages.md`).

The second part asks whether a language should ship a large library ("batteries included") or a small specified core with a free registry, and what one library on every compute fabric requires. It is read against the built-in library (4.1), the closed method table (5.15), the numeric contract (6.3), the fixed reduction tree (C.8) and the fabric rules of the host contract (E.6, E.7). Its synthesis is `batteries-specification-and-fabrics.md`, written from working notes 7 to 18:

7. code across compute fabrics without a platform-specific library (`code_across_compute_fabrics.md`);
8. batteries included against specification and free (`batteries_versus_specification.md`);
9. one semantics compiled to software and hardware (`one_semantics_across_hardware_and_software.md`);
10. energy per operation across fabrics (`energy_per_operation_across_fabrics.md`);
11. library interfaces defined by a specification with conformance suites (`specification_defined_library_interfaces.md`);
12. placement from cost models, and its determinism (`placement_cost_models_and_determinism.md`);
13. what developers and models do not know is available (`knowledge_of_available_apis.md`);
14. concurrency semantics across fabrics (`concurrency_semantics_across_fabrics.md`);
15. one unchanged source across CPU, GPU and FPGA, measured (`one_source_cpu_gpu_fpga_quantitative.md`);
16. standard-library breadth against dependency counts (`library_breadth_and_dependency_counts.md`);
17. model assistants and standard libraries (`model_assistants_and_standard_libraries.md`);
18. the RCE repository's library and fabric mechanisms, inventoried (`rce_library_and_fabric_mechanisms.md`).

Notes 7 and 8 were verified claim by claim by verifiers instructed to refute; `fabric_verification.md` and `batteries_verification.md` record each verdict and the source read. Each note states which sources were read directly and which were confirmed from indexed page text; figures a project reports about itself are marked.

`scripts/` holds the small scripts behind the counts and ratios that the notes computed themselves (notes 12, 15 and 16); each takes the downloaded data set as an argument.
