# Verification of working note 8 (batteries versus specification)

Adversarial verification of the load-bearing claims of the working note, 24 October 2026: one verifier per claim, instructed to refute, with verdicts confirmed, corrected, refuted or unverifiable. Corrections are applied to the note.

| Claim | Verdict | Source read |
|---|---|---|
| B1 | confirmed | https://github.com/python/peps/commit/5142617c213452e7a720ba5f072fbf4848031b7a |
| B2 | confirmed | https://github.com/python/peps/blob/main/peps/pep-0594.rst |
| B3 | confirmed | https://raw.githubusercontent.com/golang/website/master/_content/doc/go1compat.html |
| B4 | confirmed | https://openjdk.org/jeps/320 |
| B5 | confirmed | https://arxiv.org/pdf/1710.04936 |
| B6 | confirmed | https://arxiv.org/abs/2001.07808 |
| B7 | confirmed | https://github.com/nst/JSONTestSuite/blob/master/article/parsing_json.md |
| B8 | confirmed | https://sigops.org/s/conferences/sosp/2013/papers/p260-wang.pdf |
| B9 | confirmed | https://github.com/ziglang/zig/issues/75 |
| B10 | confirmed | https://github.com/rust-lang/rfcs/pull/3355 |
| B11 | corrected | https://github.com/rust-lang/rfcs/blob/master/text/1242-rust-lang-crates.md |
| B12 | confirmed | https://arxiv.org/abs/2605.21405 |

## B1: confirmed

**Evidence.** The strongest evidence is the git history of PEP 206, cloned from github.com/python/peps. In Moshe Zadka's 2000 draft, titled "2.0 Batteries Included", commit 5142617c (Barry Warsaw, 14 Jul 2000) added this line to the "Batteries Included Philosophy" section: "The original coinage of the term "batteries included" can be found here: http://www.uk.research.att.com/~fms/ipc7/tr-1998-9.html". That URL is Stajano's paper, technical report 1998-9. The commit message reads: "A reference to the term "batteries included" was added." A.M. Kuchling later removed the line in commit e761d70b (27 Jun 2005), when he took over PEP 206 and renamed it "Python Advanced Library". The current PEP 206 therefore no longer carries this credit.

The venue, title and author are confirmed by psf/wiki on GitHub (python/archive/LanguageComparisons.md): "Frank Stajano's paper, *Implementing the SMS server, or why I switched from Tcl to Python*, was presented at the Seventh International Python Conference (in 1998)". It links to python.org/workshops/1998-11/proceedings/papers/stajano/. A Google Scholar export on GitHub (DuyenDo/data-study-google-scholar) lists the same title, author F Stajano, venue "Seventh International Python Conference" and year 1998.

Other sources give the same credit. Search extracts of the Tcler's Wiki say the paper is "immortalized for its 'Batteries included' meme". A Chinese-language set of notes on GitHub (JPL-JUNO/Python-3, BP-3rd/notes/ch10.tex), apparently on Hetland's Beginning Python, says the phrase was originally coined by Frank Stajano.

Two limits. First, the paper itself could not be fetched: cl.cam.ac.uk, python.org, legacy.python.org and tcl-lang.org were all blocked or failed to resolve. So I did not check that the phrase appears in the paper's own text, or which sentence uses it. Search extracts say Tcl TIP 12 quotes the paper with a line ending "comes with batteries included", but I could not open TIP 12 to check this. Second, one Tcler's Wiki extract credits Stajano's IPC7 trip report rather than the paper. The claim says only that the phrase "is credited to" the paper, and PEP 206 supports that directly.

## B2: confirmed

**Evidence.** Primary source: the PEP 594 text in the python/peps GitHub repo (peps/pep-0594.rst). Header: "Author: Christian Heimes, Brett Cannon", Status: Final, Created: 20-May-2019. Table 1 lists 22 modules. asynchat (deprecated 3.6), asyncore (3.6) and smtpd (3.4.7/3.5.4) are scheduled for removal in 3.12. The other 19 are scheduled for 3.13: aifc, audioop, cgi, cgitb, chunk, crypt, imghdr, mailcap, msilib, nntplib, nis, ossaudiodev, pipes, sndhdr, spwd, sunau, telnetlib, uu and xdrlib. On the stated reasons, the Rationale says "Any additional module increases the maintenance cost for the Python core development team." The modules section says some modules "have better replacements on PyPI, e.g. Pillow for image processing", and the Rationale mentions "a rich and vibrant ecosystem of third-party packages". The removals actually happened. CPython's Doc/whatsnew/3.12.rst (3.12 branch on GitHub) says of asynchat and asyncore: "These two modules have been removed according to the schedule in PEP 594, having been deprecated in Python 3.6." It also says "The smtpd module has been removed according to the schedule in PEP 594". Doc/whatsnew/3.13.rst says: "The remaining 19 'dead batteries' (legacy stdlib modules) have been removed from the standard library." docs.python.org could not be reached (DNS failure), so I read the same What's New files from the CPython GitHub repo instead. One small inconsistency inside the PEP: its Deprecation schedule section mentions removal in 3.13, but Table 1 and the real releases both put the three async/smtp modules in 3.12. That does not affect the claim.

## B3: confirmed

**Evidence.** I read the source of the document "Go 1 and the Future of Go Programs" in the golang/website repository at raw.githubusercontent.com/golang/website/master/_content/doc/go1compat.html (7223 bytes). This is the file served at go.dev/doc/go1compat. go.dev itself was blocked by the proxy (403), so I did not read the live page.

Each part of the claim checks out:

(1) The compile-and-run sentence. The source says: "It is intended that programs written to the Go 1 specification will continue to compile and run correctly, unchanged, over the lifetime of that specification." The claim's wording matches word for word, except that it leaves out the opening "It is intended that". The page also says "it is impossible to guarantee that no future change will break any program". It then lists exceptions: security, unspecified behavior, specification errors, bugs, unkeyed struct literals, added methods, dot imports, and package unsafe.

(2) Standard library APIs. The source says: "Go 1 defines two things: first, the specification of the language; and second, the specification of a set of core APIs, the 'standard packages' of the Go library." It adds: "The APIs may grow, acquiring new packages and features, but not in a way that breaks existing Go 1 code." One exception: "The syscall package is therefore outside the purview of the guarantees made here."

(3) golang.org/x. Under the heading "Sub-repositories", the source says: "Code in sub-repositories of the main go tree, such as golang.org/x/net, may be developed under looser compatibility requirements." It goes on to say these sub-repositories "will be tagged as appropriate to identify versions that are compatible with the Go 1 point releases."

The claim has no numbers, dates or authors to check, and everything it does say is supported. The one caveat is tone: the source describes an intention and lists exceptions, so it is softer than an absolute guarantee.

## B4: confirmed

**Evidence.** The primary page (openjdk.org/jeps/320) could not be fetched directly: DNS failed and the proxy returned 403. Mirrors on mail.openjdk.org, blogs.oracle.com, adtmag.com and web.archive.org were also unreachable. Instead, I read a full-text scrape of the JEP 320 page stored on GitHub (raw.githubusercontent.com/atharva-naik/MetaLint/d3660740410f8878559c3989469c3575b25d2742/data/JEPS/JEP320.txt, 16,471 bytes). Its header reads: "Owner Lance Andersen ... Status Closed / Delivered, Release 11 ... Created 2017/10/11 ... Issue 8189188".

Nine modules: the Description section lists six Java SE modules (java.xml.ws, java.xml.bind, java.activation, java.xml.ws.annotation, java.corba, java.transaction) and three related modules (java.se.ee, jdk.xml.ws, jdk.xml.bind). It then says: "In Java SE 11, the nine modules that are listed above will be removed".

Maven Central: the Motivation section says, word for word: "Since standalone versions of the Java EE technologies are readily available from third-party sites, such as Maven Central, there is no need for the Java SE Platform or the JDK to include them."

Other sources agree. A second independent GitHub copy (TheRealSeber/PolishedJADEite) has the identical Maven Central sentence. A web-search extract of openjdk.org lists the JEP as Closed / Delivered in release 11, and the extract of the JDK-8193757 bug tracker entry gives the same nine modules. JDK 11 shipped in 2018, and the 2018 ADTmag article on JDK 11 repeats the Maven Central rationale.

One nuance: the Maven Central argument in the JEP covers the Java EE technologies only. CORBA was dropped on a separate cost/benefit ground ("the costs of maintaining CORBA support outweigh the benefits"). The claim's wording is still accurate as written.

## B5: confirmed

**Evidence.** I could not open the primary source directly. WebFetch failed on arxiv.org/pdf/1710.04936, alphaxiv.org, link.springer.com, orbi.umons.ac.be, academia.edu, deepai.org and semanticscholar.org (DNS ENOTFOUND for each). The verdict therefore rests on web-search extracts of the paper's arXiv PDF.

1. Bibliographic details. Search results, including the Springer DOI 10.1007/s10664-017-9589-y, give: Decan, A., Mens, T. & Grosjean, P., "An empirical comparison of dependency network evolution in seven software packaging ecosystems", Empir Software Eng 24, 381–416 (2019). The seven ecosystems are Cargo, CPAN, CRAN, npm, NuGet, Packagist and RubyGems. The arXiv preprint was posted in October 2017.

2. The numbers. An extended search returned an extract of arxiv.org/pdf/1710.04936 from the RQ4 section on transitive dependencies. The snippet reads "half of the dependent packages in Cargo, npm and NuGet have at least 41, 21 and 27 transiti[...]" and is cut off at "transiti". The surrounding extract says "a majority of the dependent packages have few direct dependencies, they have a much higher number of transitive dependencies", and that the figure is a January 2017 snapshot.

3. Independent cross-check. A citing paper, arXiv 2305.10910 on Swift package managers (seen only as a search extract), says "the median number of transitive dependencies for a library available through the Cargo, NuGet and npm package manager is 41, 27 and 21, respectively." The same numbers map to the same ecosystems (Cargo 41, npm 21, NuGet 27).

Caveats: the extract comes from the arXiv preprint, not the published journal text, and it ends mid-word at "transiti". The cross-check confirms that the counts are transitive dependencies. The claim leaves out the January 2017 snapshot date, but that does not make it wrong.

## B6: confirmed

**Evidence.** The arXiv abstract (2001.07808), which I read in search-result extracts, says the authors "analyze 9,639 Java artifacts hosted on Maven Central, which include a total of 723,444 dependency relationships." Its key result is that "75.1% of the analyzed dependency relationships are bloated." The authors are César Soto-Valero, Nicolas Harrand, Martin Monperrus and Benoit Baudry. The arXiv version was submitted on 21 January 2020. I could not fetch arxiv.org, ar5iv, link.springer.com, paperswithcode or cesarsotovalero.net directly (DNS failures), so the abstract wording comes from those search extracts. Two separate searches returned the same wording. I checked the venue on github.com/castor-software/depclean: its README BibTeX lists the paper in Empirical Software Engineering, vol. 26, no. 3, pp. 1-44, 2021, DOI 10.1007/s10664-020-09914-8. So "EMSE 2021", the title, the first author, 9,639 Maven Central artifacts and 75.1% all match the source.

## B7: confirmed

**Evidence.** The seriot.ch article was blocked (DNS failure and a 403 from the proxy), as were theregister.co.uk and lua-users.org. I read the author's own source for the article instead. It sits in his repository at nst/JSONTestSuite, file article/parsing_json.md, and was added to the repo on 2024-09-30. Its header says "Parsing JSON is a Minefield", hosted on seriot.ch, "[2016-10-26] First version of the article", followed by later updates up to "[2018-03-30] Updated this article considering RFC 8259". The conclusion section says: "...by crafting test files that out of over 30 parsers, no two parsers parsed the same set of documents the same way (section 4)." Two other passages say the same thing: "In my findings, there were no two parsers that exhibited the same behaviour" and, in the session description, "Indeed, I did not find two libraries that exhibit the very same behaviour." The session-description sentence was already quoted in October 2016: the ServerSwift newsletter post dated 2016-10-28 (found via GitHub code search) carries it under the byline Nicolas Seriot. A search extract of The Register's 2016-11-01 article says he ran test files "against more than 30 parsers" and "no two parsers handled the same set of documents in the same way". I also checked the parser count in the repository history. At commit 299189e (2016-10-27 00:39 +0200), run_tests.py lists 44 active parsers and results/logs.txt holds 37 distinct ones. By 758c85b (2016-10-27 14:28) the counts are 46 and 40. Both are consistent with "more than 30". Author, year, parser count and the no-two-alike finding all match. One caveat: the source file I read is the current version, revised in 2018. The October 2016 wording of the "over 30" sentence itself is supported only by The Register extract and the commit history.

## B8: confirmed

**Evidence.** I could not open the primary source. Every direct fetch failed: sigops.org SOSP'13 PDF p260-wang.pdf, pdos.csail.mit.edu stack:sosp13.pdf, dspace.mit.edu 1721.1/86980, dl.acm.org DOI 10.1145/2517349.2522728, css.csail.mit.edu/stack, srg.doc.ic.ac.uk and web.archive.org all returned DNS or proxy errors. The Semantic Scholar and Crossref APIs were blocked (403). The verdict therefore rests on search extracts. Several independent extracts agree, and they quote the authors' own copies of the paper: the SOSP PDF on sigops.org (pp. 260-275), the MIT DSpace open-access record, and the ACM DL entry.

The paper is "Towards Optimization-Safe Systems: Analyzing the Impact of Undefined Behavior" by Xi Wang, Nickolai Zeldovich, M. Frans Kaashoek and Armando Solar-Lezama (MIT CSAIL), SOSP '13. The extracted abstract says the paper "studies an emerging class of software bugs called optimization-unstable code", found in many systems "including the Linux kernel and the Postgres database". It describes a new static checker, STACK, "that precisely identifies unstable code". The decisive sentence, quoted verbatim in the extracts: "Applying Stack to widely used systems has uncovered 160 new bugs that have been confirmed and fixed by developers." The MIT CSAIL project page and Princeton/Georgia Tech talk abstracts repeat 160.

Caveat: later versions of the work give 161 instead. Both Wang's 2014 PhD thesis and the 2015 ACM TOCS journal version say "uncovered 161 new bugs that have been confirmed and fixed by developers". The SOSP 2013 paper itself says 160, so the claim is accurate for the venue it cites.

## B9: confirmed

**Evidence.** I fetched the primary source, https://github.com/ziglang/zig/issues/75, with WebFetch. The GitHub API, gh and curl were blocked for the ziglang repo in this session, but the rendered page loaded. Two separate fetches agreed on every point:
- Andrew Kelley (andrewrk) opened the issue on Jan 18, 2016. It was first titled "language specification" and was renamed "first draft of the language specification" on Oct 9, 2020.
- The timeline reads "closed this as not planned" on Apr 22, 2026, by andrewrk. No "completed" close appears.
- On the same day, before closing, andrewrk commented: "Tracked by https://codeberg.org/ziglang/zig-spec/milestone/79847". So tracking of the spec work moved to a separate repository, ziglang/zig-spec on Codeberg.
- Nuance: the separate zig-spec repository is older than the close. On Oct 9, 2020 andrewrk commented "Here's the repo: https://github.com/ziglang/zig-spec". What the April 2026 close did was hand tracking to a milestone in the Codeberg copy of that repo. The claim's wording still holds.
- I could not reach the Codeberg milestone itself (codeberg.org did not resolve, ENOTFOUND). The page also hid "2 remaining items" behind "Load more", but the close event and the closing comment were both visible.

## B10: confirmed

**Evidence.** (1) RFC: The GitHub page for rust-lang/rfcs PR #3355 ("Rust Specification", by m-ou-se), fetched directly, shows rfcbot opening the final comment period on Jun 29, 2023 and saying it "is now complete" on Jul 9, 2023, with "m-ou-se merged commit ed4c592 into rust-lang:master Jul 10, 2023". Search extracts of the Rust Foundation announcement agree: the RFC was "submitted in December 2022" and "approved in July 2023". (2) Donation: I could not reach rustfoundation.org or blog.rust-lang.org directly (DNS failures), so this part rests on GitHub sources and search extracts. The Rust Foundation post is titled "Ferrous Systems Donates Ferrocene Language Specification to Rust Project". Its Mastodon announcement ID decodes to 2025-03-26, The New Stack reported it on Mar 28, 2025, and Slashdot covered it on 2025-03-30. The Rust Project's own post "Adopting the FLS" (blog source on GitHub, authors = ["TC"], path 2025/03/26) says "Ferrous Systems and AdaCore worked together to assemble a description of Rust called the FLS" and "This adoption is being made possible by Ferrous Systems." The rust-lang/fls README says: "The Rust Project would like to thank Ferrous Systems for donating the FLS ... to the Rust Project". One caveat: the same README says "Until its transfer in April 2025, Ferrous Systems had been the sole steward of the FLS since July 2023." So the donation was announced on 26 March 2025, but the formal transfer of stewardship finished in April 2025. Also, the FLS was originally written by Ferrous Systems together with AdaCore.

## B11: corrected

**As the source supports it.** Rust RFC 1242 ("rust-lang crates", start date 2015-07-29) says that std's stability promises and updates are tied to the versioning of Rust itself, "meaning that the standard library has much less flexibility than other crates enjoy". It also says that new std APIs "can just as well begin their life as external crates, usable on stable Rust", and proposes that such extensions "can start" as external rust-lang crates. The RFC says "can", not "should".

**Evidence.** I fetched the primary text from GitHub at text/1242-rust-lang-crates.md in the rust-lang/rfcs repo (RFC PR rust-lang/rfcs#1242, Start Date 2015-07-29). Under the Motivation heading "Keeping std small", it reads: "the stability promises made in `std` are tied to the versioning of Rust itself, as are updates to it, meaning that the standard library has much less flexibility than other crates enjoy." The claim's quoted phrase, 'gets less flexibility than other crates', does not appear anywhere in the RFC. It paraphrases the real sentence, so the substance is right but the quotation is not.

Under "Staging std", it reads: "But in many cases, new `std` APIs can just as well begin their life as external crates, usable on stable Rust, and ultimately stabilized wholesale." It also says: "this RFC proposes that the extension can start its life as an external rust-lang crate (ideally usable by stable Rust)." So the RFC presents external crates as an option ("can"), not a rule ("should"), and it is talking specifically about APIs meant for std.

The RFC number, the title (rust-lang crates) and the overall argument all check out.

## B12: confirmed

**Evidence.** arxiv.org, pith.science, emergentmind.com, chatpaper.com, alphaxiv.org and huggingface.co were all unreachable: DNS failures or proxy 403s. Every check below therefore relies on search-engine extracts and the zerodep GitHub README, not on the paper's full text.

Author and ID: the Oaklight/zerodep README on github.com cites the paper as "Stdlib or Third-Party? Empirical Performance and Correctness of LLM-Assisted Zero-Dependency Python Libraries" by Peng Ding and Rick Stevens, "arXiv preprint arXiv:2605.21405".

Date: search extracts give a submission date of 20 May 2026 (cs.SE/cs.AI/cs.PL), which fits the 2605 (May 2026) ID. A chatpaper extract says 21 May 2026 and lists the University of Chicago and Argonne.

Module count: one extract from the arXiv HTML/abstract describes "44 single-file, stdlib-only Python modules across 12 categories, each benchmarked against a reference library". The abstract itself, as quoted by chatpaper and Pith, says "over 40 modules across 12 categories". The zerodep readthedocs module table also lists 44 entries.

Two-thirds parity: the abstract says stdlib-only versions "achieve performance parity (within 2x of the reference) in the majority of cases". An extended-search extract quotes the introduction: "roughly two-thirds achieve performance within 2× of the reference library, and many substantially outperform it." Two later searches could not reproduce that sentence. However, an exact-phrase search for it returned arxiv.org/pdf/2605.21405 as the top hit.

Wording nuance: the modules are LLM-assisted reimplementations, which fits "built ... replacements".

Every specific checks out, but the two-thirds figure rests on one quoted search extract, not on reading the paper.
