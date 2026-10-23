# Relational and SQL engines read against RCEdb

Research conditions (state them so the writer can weigh the notes): the session's web-search budget was exhausted after 12 queries, and direct fetches of primary pages (postgresql.org, sqlite.org, usenix.org, PDFs) were refused by the egress proxy (HTTP 403 on CONNECT). Every "Cited Finding" below is therefore drawn from search-result summaries that quoted the primary page, with the primary URL attached. Claims the researcher knows from background but could not fetch this session are segregated under "Gaps / unverified background" and must not be cited as sourced. Verdicts on RCEdb (adopt / refuse / leave open) are the researcher's judgement unless a source is given.

RCEdb design recap used as the yardstick: host supplies durable append + a Sync result event; every index = pure fold of a prefix of the hash-chained log D, digest-checked per sequence number (HS-7); queries are RCE terms with keyed reads, keyed joins, canonical-order scans, results in canonical order, set/bag in the type, provable termination (HS-8); state at k = fold of D up to k (HS-9); durable mark moves only on a bound Sync event.

---

## KQ1. Write-ahead logs as the source of truth: structure, physical vs logical, derivability, measured cost

### Takeaway
Every mainstream engine keeps a WAL, but in none of them is the log the database: the log is a recovery device that is truncated at checkpoint, carries physical page images (full-page writes / doublewrite) to defend against torn writes, and is not kept long enough to rebuild state. Group commit is the universal answer to fsync cost; measured gains in the PostgreSQL record range from no gain (fast fsync, few clients) to ~4.7x (34 -> 159 TPS, slow-fsync disk, 20 clients, 2012).

### Cited Findings
- PostgreSQL protects against torn pages by writing full-page images to WAL after each checkpoint; a 2011 pgsql-hackers message argues a doublewrite area could replace them ("full_page_writes to the WAL are not needed as long as double-write is used for any pages which would have been written to the WAL", and it "would eliminate those full-page images from the WAL files, making them smaller") — [pgsql-hackers 2011](https://www.postgresql.org/message-id/4EFC449F02000025000441CD@gw.wicourts.gov)
- A 2026 pgsql-hackers proposal to add a doublewrite buffer to PostgreSQL argues "full-page writes and checkpoint frequency are fundamentally at odds" (more checkpoints = more full-page WAL writes); a reply says FPW and DWB are "different techniques implemented to solve the exact same issue: preventing torn pages during a crash"; another reply warns it "would probably mean doing two fsyncs where we only now do one". Proposal status: mailing-list design discussion, not an accepted patch — [pgsql-hackers 2026 proposal thread](https://www.postgresql.org/message-id/CANeUpr_cOYTy_Gg48zrb%3D-jv-y7o_4pFvwYu6%3DuECDPqJuZVfw%40mail.gmail.com); [reply](https://www.postgresql.org/message-id/CAGbZs7grxqvQXrLFZuz4rhRb5jMOnrJ3YG4EHuoHej-UhJwWNg%40mail.gmail.com)
- InnoDB: "Page writes are first sent to the doublewrite buffer, then to their actual location in the data file" — [summary via planet.mysql.com](https://planet.mysql.com/entry/?id=23387) (secondary)
- PostgreSQL ships WAL to standbys, so full-page images cost network bandwidth; a 2010 thread notes "InnoDB is not shipping its logs across the wire, so the choice matters less for it" — [pgsql-hackers 2010](https://www.postgresql.org/message-id/AANLkTi%3DhyctfYdQMsF2bQpsoswB5%3D%2BCSma5gbNKW%3DYoK%40mail.gmail.com)
- SQLite WAL mode vs rollback journal: in WAL mode with synchronous=NORMAL "SQLite syncs the WAL at checkpoints and during most commits does no sync at all"; "FULL synchronous is the default when using a rollback journal but NORMAL synchronous is the default for WAL mode" — [SQLite docsrc](https://www.sqlite.org/docsrc/info/bcf687da9c172292); [SQLite docsrc](https://www.sqlite.org/docsrc/info/cc22fb914a1b7005)
- Group commit numbers (PostgreSQL, 2012, pgbench, slow-fsync disk, Jeff Janes): at 20 clients baseline ~34 TPS, commit_delay ~69 TPS, group-commit patch ~159 TPS — [pgsql-hackers (Janes)](https://www.postgresql.org/message-id/CAMkU=1whmdC+o7RP-Lc3Gd_7OS2LM4S6Ltk5jc2ZrsNjvL4gvg@mail.gmail.com)
- Robert Haas, 2-core laptop with slow fsync: ~1.8x at 80 clients (~50 -> ~90 TPS), no gain at 2 clients; on a POWER7 machine no improvement at all from commit_delay — [pgsql-hackers (Haas)](https://www.postgresql.org/message-id/CA%2BTgmoZ2FsfEi%3DWDzsuT45b%3D11q08ddp0QKjDduKta9VnpMJfw%40mail.gmail.com)
- Consumer SSD (Intel X25-M, Jesper Krogh, 2012): 1,169 TPS baseline vs 1,233 with commit_delay at 1 client; 2,611 vs 3,022 at 5 clients — [pgsql-hackers (Krogh)](https://www.postgresql.org/message-id/4F25A39D.5080801%40krogh.cc)
- Amazon EBS (Noah Misch): commit_delay=500 "showed more loss than gain" — [pgsql-hackers thread](https://postgrespro.com/list/thread-id/1802929)
- Peter Geoghegan: ">80% throughput gains at low client counts" were measured on a "maximally commit-bound workload"; once group commit moved into XLogFlush, commit_delay's effect was "almost entirely eliminated at higher client counts" — [pgsql-hackers (doc patch thread)](https://www.postgresql.org/message-id/CAEYLb_WtKY754jaL%2BSf%3DuYHcHw-dn92kLJCR7OW7EAqpH-FqRQ%40mail.gmail.com)

### Inferences
- The relational engines' logs are physical-or-physiological and checkpoint-truncated because they were designed for recovery of a mutable heap, not as the canonical artifact. RCEdb's log is logical (events), never truncated, and has no heap to protect, so the entire full-page-write / doublewrite apparatus (and its "two fsyncs" cost) is unnecessary. Verdict (judgement): **refuse** physical logging; **adopt** the engines' one real lesson, which is that commit cost is dominated by the fsync and must be amortised. RCEdb's "durable mark moves only on a bound Sync event" is group commit by construction: the host batches appends between Sync events. Recommend that the spec state the batching window explicitly and that the Sync result event carry the durable sequence number so the fold can expose "durable as of k" vs "appended as of k'".
- The torn-write problem does not vanish for RCEdb: an append of event e_k can be torn at power loss. The relational answer (page image + checksum) maps to RCEdb's per-record hash chain: a torn tail is detected because its SHA-256 link fails, and recovery truncates to the last chain-valid record. Verdict: **adopt** explicit tail-truncation-on-invalid-chain as a stated recovery rule (the spec's HS-7 digest covers indexes; make the log tail rule explicit).
- Because the engines never keep the whole log, "what is derivable from the log" is bounded by the last checkpoint; replication (PostgreSQL logical decoding, MySQL binlog) exists precisely to re-derive a logical stream from a physical log, an inversion RCEdb does not need.

### Gaps / unverified background
- Could not fetch postgresql.org wal-intro / wal-reliability pages, the InnoDB redo-log manual, or pg_test_fsync numbers; current (2024-2026) fsync-latency measurements per device class were not obtained. Background (unverified this session): PostgreSQL WAL records are "physiological" (page-addressed, logical within the page) with full-page images after checkpoint; InnoDB redo log is page-oriented and circular; MySQL binlog is a separate logical log; SQLite WAL frames are whole database pages. None of these can be cited from this session.
- No source retrieved for logical decoding / wal_level=logical or for MySQL binlog as an index-rebuild source.

---

## KQ2. Durability in practice: fsync semantics, fsyncgate, power-failure data loss measurements

### Takeaway
Two OSDI 2014 studies showed that every tested database (8/8 in Zheng et al.) and most tested applications (~60 crash vulnerabilities across 11 apps in Pillai et al.) violate their own durability or atomicity claims under power loss, and the 2018 fsyncgate showed PostgreSQL had for years assumed a fsync() contract Linux did not provide. "Durable" in practice means "durable as far as the kernel chose to tell us", and engines now PANIC on fsync failure because there is nothing else safe to do.

### Cited Findings
- fsyncgate: reported by Craig Ringer to pgsql-hackers end of March 2018; LWN "PostgreSQL's fsync() surprise" (Jonathan Corbet, 18 April 2018). PostgreSQL assumed a successful fsync() covered all earlier writes; the checkpointer often opens a file just before fsync, and "even in 4.13 and later kernels, the checkpointer will not see any errors that happened before it opened the file" — [LWN 752063](https://lwn.net/Articles/752063/); [danluu fsyncgate archive](https://danluu.com/fsyncgate/)
- Linux 4.13 attached a 32-bit error-and-sequence value (errseq) to each inode's address_space, fixing error reporting but "does not bring the data back" — [LWN 752063](https://lwn.net/Articles/752063/)
- PostgreSQL's fix: "PostgreSQL will now PANIC on fsync() failure", backpatched to 11, 10, 9.6, 9.5, 9.4; "Similar changes were made in InnoDB/MySQL, WiredTiger/MongoDB and no doubt other software" — [PostgreSQL wiki: Fsync Errors](https://wiki.postgresql.org/wiki/Fsync_Errors); commit dated November 2018 per [thebuild.com](https://thebuild.com/blog/all-your-gucs-in-a-row-datasyncretry/) (secondary; wiki version history differs slightly)
- Zheng, Tucek et al., "Torturing Databases for Fun and Profit", OSDI 2014 pp. 449-464: tested 8 widely used databases "from open-source key-value stores to commercial OLTP servers"; "All 8 databases exhibit erroneous behavior"; for open-source systems root causes were traced, for commercial ones data loss was reproducibly induced; slides state "everything is broken under simulated power faults", with per-DB/FS/workload cells marked D, ACD, CD, Hang — [USENIX abstract](https://www.usenix.org/node/186197); [OSDI slides](https://www.ece.iastate.edu/%7Emai/docs/papers/2014_OSDI_slides.pdf); [paper PDF](https://www.ece.iastate.edu/%7Emai/docs/papers/2014_OSDI_DB.pdf)
- Pillai et al., "All File Systems Are Not Created Equal", OSDI 2014 pp. 433-448: applications' update protocols depend on file-system "persistence properties" (atomicity of appends, ordering) which "differed widely across six popular Linux file systems"; tools BOB and ALICE; ~60 vulnerabilities across 11 applications under unfavourable FS behaviour vs ~10 under favourable behaviour (FAST '17 slides); thesis reports 60 vulnerabilities "which can cause data corruption and loss" — [USENIX](https://www.usenix.org/node/186195); [ADSL page](https://research.cs.wisc.edu/adsl/Publications/alice-osdi14.html); [FAST'17 slides](https://www.usenix.net/sites/default/files/conference/protected-files/fast17_slides_pillai.pdf); [Pillai PhD thesis](https://research.cs.wisc.edu/wind/Publications/thanu-phd.pdf)
- SQLite durability per mode: WAL+NORMAL "WAL mode is always consistent with synchronous=NORMAL, but WAL mode does lose durability" (commits can be undone after power loss, file stays uncorrupted); rollback journal (DELETE) + NORMAL carries "a very small (though non-zero) chance that a power failure at just the wrong time could corrupt the database... on an older filesystem"; transactions are durable across application (process) crashes regardless of journal mode or synchronous setting — [SQLite docsrc](https://www.sqlite.org/docsrc/info/bcf687da9c172292); [SQLite forum](https://sqlite.org/forum/forumpost/9d6f13e346231916?raw); [avi.im sqlite-fsync note 2025](https://avi.im/blag/2025/sqlite-fsync/) (secondary)

### Inferences
- The engines' durability failures have three roots: (a) assuming FS persistence properties (append atomicity, ordering) the FS does not promise (Pillai); (b) assuming fsync reports and retains errors (fsyncgate); (c) trading durability for latency by default (SQLite WAL defaults to NORMAL). RCEdb's division of labour ("host supplies only durable append and a sync-result event") is the right cut for (a) and (b) if, and only if, the spec says what the host must do on fsync error. Verdict (judgement): **adopt** the PostgreSQL post-2018 rule in RCE terms: a Sync event may carry failure, and on failure the durable mark must not advance and the host must treat the tail after the mark as unknown (re-read and chain-verify, or crash). Do not retry fsync silently.
- For (c): RCEdb should **refuse** a NORMAL-style default where the durable mark advances without a completed sync; the spec already does this ("moves only on a bound Sync event"). What is still open: whether the spec should *also* let lambda outputs be gated on the durable mark (so a user-visible acknowledgement is never emitted for an event whose durability is not yet confirmed). That is the same bug class as SQLite's NORMAL, moved one layer up. Verdict: **adopt** an "ack after durable" option, leave the default **open**.
- Zheng's finding that commercial engines lose data reproducibly suggests testing under power fault injection is itself the design input. Verdict: **adopt** a record/replay power-fault harness against RCEdb's host adapters; the fold+digest design makes the oracle trivial (any divergence from refold is a bug), which is an advantage no mutable-heap engine has.

### Gaps / unverified background
- The full Zheng results table (which of the 8 DBs showed D vs ACD violations, which file systems) and the per-application vulnerability list from Pillai (how many hit SQLite WAL vs rollback journal, LevelDB, PostgreSQL, LMDB, ZooKeeper) could not be fetched; the search summary noted the cell codes were not defined in the excerpt.
- O_DIRECT, ext4/xfs barriers, and the specific Linux fsync error-retention semantics beyond errseq were not retrieved.
- Background (unverified this session): PostgreSQL 12 added data_sync_retry; Pillai found SQLite rollback-journal mode depended on an ordering guarantee between journal write and database write that ext4 data=writeback does not give. Not citable from this session.

---

## KQ3. Determinism and reproducibility

### Takeaway
SQL engines are explicitly nondeterministic in result order without ORDER BY (SQLite documents it as "undefined", including ties under ORDER BY), and serializable isolation in PostgreSQL (SSI) guarantees only equivalence to *some* serial order, with the price paid as serialization-failure aborts that must be retried. RCEdb's canonical-order rule and total deterministic step are the thing SQL engines never had; the cost SQL avoids (and RCEdb pays) is that a single total order of events must exist.

### Cited Findings
- SQLite requirements: "the order in which result rows are returned from a SELECT statement is undefined if there is no ORDER BY clause"; and "the order in which two rows for which all ORDER BY expressions evaluate to equal values are returned is undefined" — [SQLite requirements doc](https://svnlliurexnet.gva.es/leia/mods-backports/trunk/sqlite3/www/requirements.html) (mirror of sqlite.org requirements.html); [SQLite docsrc](https://www.sqlite.org/docsrc/info/a7856e4125c57d75)
- SQLite planner source: rowid is "always UNIQUE and NOT NULL so whenever the rowid appears in the ORDER BY clause, the corresponding WhereLoop is automatically order-distinct"; a UNIQUE column may hold several NULLs so UNIQUE alone is not order-distinct — [SQLite source check-in](https://www.sqlite.org/src/info/cf96eb5945a9bab7)
- SQLite sorts NULL "smaller than any other values", overridable with "ASC NULLS LAST"/"DESC NULLS FIRST" — [sqlitetutorial.net](https://www.sqlitetutorial.net/sqlite-order-by/) (secondary, quoting docs)
- CockroachDB AS OF SYSTEM TIME: when selecting over multiple tables the clause "must appear at the very end and applies to the entire SELECT clause"; in v23.1 it "can be used only when the transaction is read-only" — [CockroachDB docs v23.2](https://www.cockroachlabs.com/docs/v23.2/as-of-system-time); [SET TRANSACTION v23.1](https://www.cockroachlabs.com/docs/v23.1/set-transaction)

### Inferences
- The relational engines got order right in the standard (a relation is a set) and wrong in practice (every engine leaks physical order, and applications depend on it; SQLite's own tutorial ecosystem warns that an index change silently reorders results). RCEdb's "results in canonical order, never unspecified" is strictly stronger and removes a whole class of flaky-test and replay-divergence bugs. Verdict: **adopt as already specified**, and add SQLite's two lessons explicitly: (1) ties are a nondeterminism source, so canonical order must be total over the full row (key then remaining columns in schema order), and (2) NULL/absent ordering must be fixed in the type, not a runtime option.
- Serializable isolation in multi-writer engines is a search for *an* order; RCEdb has *the* order (sequence numbers) and so needs no SSI, no predicate locks, no retry loop. The cost moves to ingestion: concurrent clients contend to append, and the spec must say who serialises (one appender per log, or a consensus layer). Verdict: **adopt** single-sequencer semantics explicitly; **leave open** multi-log/merge semantics, which is where CockroachDB and Spanner spend their complexity (TrueTime, hybrid logical clocks) and where RCEdb has no answer yet.
- Floating-point aggregation order: not sourced this session (see Gaps). Judgement: because delta is a pure deterministic step and canonical order is total, RCEdb's float sums are reproducible provided the fold order is the canonical order and no parallel reduction is permitted to reassociate. The spec should say that aggregates fold in canonical key order and that parallel evaluation must produce the same bit pattern (or that float aggregates are refused in favour of decimals).

### Gaps / unverified background
- The PostgreSQL transaction-iso page (SSI wording, "predicate locks", serialization failure retry requirement) and the DuckDB ORDER BY/parallelism docs could not be fetched. Background (unverified): PostgreSQL docs state serializable mode may abort with serialization_failure and applications must retry; PostgreSQL parallel aggregation of float8 sum can differ run to run; DuckDB's parallel execution preserves insertion order only when `preserve_insertion_order` is true. Not citable.
- No source retrieved this session for Spanner TrueTime/external consistency (OSDI 2012) or CockroachDB SIGMOD 2020. Background (unverified): Spanner provides external consistency via TrueTime commit-wait; CockroachDB uses HLC with uncertainty intervals and does not claim linearizability across the whole cluster.

---

## KQ4. Time travel and as-of queries

### Takeaway
As-of reads exist in CockroachDB (AS OF SYSTEM TIME, bounded by the MVCC GC window), Spanner (stale reads), Snowflake/Delta (retention windows) and SQL:2011 system-versioned tables, but every one of them bounds history by a retention/GC setting because the history is stored as versions, not derived. RCEdb's HS-9 makes any k queryable with no retention knob, at the cost of refold time proportional to k unless checkpoints are kept.

### Cited Findings
- CockroachDB: "Historical data is available only within the garbage collection window, which is determined by the `ttlseconds` field in the replication zone configuration" — [CockroachDB as-of-system-time docs](https://cockroachlabs.com/docs/v22.1/as-of-system-time); same text in [v26.1](https://www.cockroachlabs.com/docs/v26.1/as-of-system-time.md)
- A third-party CDC vendor recommends raising gc.ttlseconds to at least 259,200 s (72 h) so paused pipelines do not lose changes (vendor recommendation, not a CockroachDB default) — [Hevo docs](https://mini-docs.hevodata.com/edge/sources/cockroachdb/)

### Inferences
- The engines expose time travel as a bounded window because every retained version costs storage on the hot path and MVCC GC must reclaim it. RCEdb inverts the cost: history is free (the log is already retained) but as-of reads are O(k) refolds. Verdict (judgement): **adopt** HS-9 as specified, and **adopt** the engines' practical device in derived form: periodic snapshots (checkpoints) of the folded state at chosen sequence numbers, themselves digest-checked under HS-7, so an as-of-k query folds from the nearest snapshot at or below k. This keeps "state = fold" as the meaning and makes snapshots a placement choice, exactly like indexes.
- Retention: RCEdb should **refuse** a GC window on the log (it would break HS-9 and the hash chain), but should **leave open** retention of *snapshots* and *secondary indexes for old k*, which are the only things that cost space beyond the log.
- The proposed provenance refinement (creating/retracting event id on every node and edge) is a system-versioned table in SQL:2011 terms, with the period columns replaced by sequence numbers; this makes "as of k" a keyed filter (created <= k < retracted) rather than a refold, which is the engines' trick (version visibility by timestamp) without their GC. Verdict: **adopt** the provenance refinement for this reason, noting it duplicates in the primary index what the log already holds (a space cost, not a meaning cost).

### Gaps / unverified background
- Snowflake time-travel retention/storage-cost docs, Delta Lake VACUUM, SQL:2011 temporal tables (SQL Server / MariaDB system versioning) and Spanner stale-read docs were not retrieved (search budget ended). Background (unverified): Snowflake default retention is 1 day, up to 90 on Enterprise, billed as extra storage; CockroachDB default gc.ttlseconds was 90,000 (25 h) and was lowered to 14,400 (4 h) in v22.2; Spanner allows bounded-staleness reads up to the version GC window (~1 h by default). None citable from this session.

---

## KQ5. Index as derived state: materialized views, IVM, rebuild-from-log

### Takeaway
Materialized views are the engines' only derived-state mechanism; incremental maintenance (pg_ivm, Oracle fast refresh) is restricted in the query language it supports and taxes the write path. No mainstream engine can rebuild all indexes from its WAL alone, because the WAL is truncated at checkpoint and indexes are maintained as mutable physical structures logged alongside the heap.

### Cited Findings
- pg_ivm "enables Incremental View Maintenance (IVM) for PostgreSQL, updating materialized views by applying only incremental changes instead of rebuilding the entire view" — [EDB docs](https://www.enterprisedb.com/docs/pg_extensions/pg_ivm/)
- The core-PostgreSQL IVM proposal's TPC-H evaluation: "can update a materialized view more than 200 times faster than re-computation by REFRESH command" (developer's talk; indicative) — [pgsql-hackers IVM thread, Jan 2021](https://www.postgresql.org/message-id/20210112190308.ee9e98c24080310a487349f3%40sraoss.co.jp); [PGConf.ru 2021](https://pgconf.ru/en/2021/288667)
- Write-path cost and limits (competitor blog, treat as partisan): pg_ivm "maintains a consistent state by blocking writes until the materialized view update is complete... may impact write performance"; limited operator support "notably missing... OUTER JOINs and ORDER BY" — [Epsio blog](https://www.epsio.io/blog/pg-ivm); the PGConf.EU 2026 talk says outer-join support "has since been recently added" and will cover "deferred maintenance approaches that could reduce update overhead" — [PGConf.EU 2026 session](https://www.postgresql.eu/events/pgconfeu2026/sessions/session/8219-pg_ivm-recent-improvements-and-future-directions-in-incremental-view-maintenance/)
- No independent benchmark of pg_ivm's write-path overhead was found — stated as a gap by the search itself.

### Inferences
- The relational engines got the *idea* right (a view is a function of base tables) and the *implementation* wrong by hindsight: maintenance is synchronous on the write path, language support is partial (outer joins, aggregates, recursion), and the view is not digest-checked, so a maintenance bug is silent. RCEdb's HS-7 (every index is a fold with a per-k digest) is IVM done as a specification rather than as an extension. Verdict: **adopt as specified**, with two additions borrowed from the engines' experience: (1) allow *deferred* index maintenance (an index may lag the log; its digest states which k it is at) so the write path never blocks on index work; (2) restrict the index-defining query language to the same total-termination fragment as HS-8 so that every index is both rebuildable and provably finite.
- "Can any engine rebuild every index from its log alone?" Answer by hindsight: no, because logs are truncated and index pages are logged physically; the answer is PITR from a base backup plus WAL, which is a snapshot plus log, not a log. RCEdb's "lost index is refolded" is only true if the log is complete back to genesis or to a digest-checked snapshot; the spec should say so (ties to KQ4 snapshots).
- Foreign stores (SQLite/RocksDB/LMDB holding an index) are consistent with the engines' own practice of pluggable storage; the risk is that the foreign store's durability defaults (SQLite WAL NORMAL) leak in. Verdict: **adopt** foreign stores only as caches whose durability is irrelevant because they are refoldable; the digest at k is the only trust anchor.

### Gaps / unverified background
- Oracle fast refresh / materialized view logs and SQL Server indexed views were not retrieved. Background (unverified): Oracle fast refresh needs a materialized view log on each base table and supports a restricted query class; SQL Server indexed views forbid outer joins, subqueries and non-deterministic functions.

---

## KQ6. The cost model: joules and CPU per transaction, the price of ACID

### Takeaway
Published energy-per-transaction numbers exist only as TPC-Energy full-disclosure reports (2010-2011 era, watts per tps) and a handful of academic measurements; the one quantified "price of durability/replication" found is Schiper, Pedone and van Renesse: the most energy-efficient replication protocol reaches less than 60% of a standalone server's work-per-joule on TPC-C.

### Cited Findings
- TPC-Energy measures transactions per watt (watts/tps reported); first results published by HP in 2010 on TPC-E, TPC-C, TPC-H — [insideHPC 2010](https://insidehpc.com/2010/07/hp-publishes-first-tpc-energy-results/); [eepower](https://eepower.com/news/transaction-processing-performance-council-announces-first-results-for-its-tpc-energy-specification/); [Computerworld](https://www.computerworld.com/article/1449783/hp-breaks-in-new-tpc-power-usage-benchmark.html)
- Computerworld reported HP DL585 G7 at 1,400 TPS with "6.72 watts" and DL580 G7 at 2,001 TPS with "5.84 watts" (these are almost certainly watts-per-ktps or similar normalised units; the search summary flagged them as implausible as raw server wattages; the implied 0.0048 J and 0.0029 J per transaction are the search tool's arithmetic and should be treated as unverified estimates) — [Computerworld](https://www.computerworld.com/article/1540071/hp-first-to-use-new-tpc-energy-power-use-spec.html)
- Primary FDRs with per-system energy: Fujitsu PRIMEQUEST 1800E2 / SQL Server 2008 R2 TPC-E+Energy (2011) — [tpc.org FDR](https://www.tpc.org/results/fdr/tpce/Fujitsu.PQ1800E2.110727.01.fdr.pdf); [Fujitsu RX900 S2 FDR](https://www.tpc.org/results/fdr/tpce/fujitsu.RX900S2.110506.01.fdr.pdf) (not opened this session)
- Schiper, Pedone, van Renesse, "The Energy Efficiency of Database Replication Protocols" (DSN 2014): efficiency defined as useful work per joule; "the most efficient replication protocol achieves less than 60% of the energy efficiency of a stand-alone server on the TPC-C benchmark" — [DSN 2014 PDF](https://www.inf.usi.ch/pedone/Paper/2014/2014DSNb.pdf)
- A 2012 Springer paper argues benchmark results "even in conjunction with TPC-Energy, lead to inadequate assessment decisions because real servers rarely run near peak utilization" — [Springer](https://link.springer.com/doi/10.1007/978-3-642-32627-1_3)
- 2025 arXiv study on effects of logical database design on query performance and energy consumption exists (not read) — [arXiv 2501.07449](https://arxiv.org/pdf/2501.07449)

### Inferences
- No source gives a decomposition of joules per transaction into log-write, index-maintenance, and query-execution shares, so "the price of ACID" in joules is not quotable from the literature retrieved. Judgement: the dominant measurable cost in the engines is the synchronous fsync (KQ1) and, in replicated settings, the replication round-trips (Schiper: >40% efficiency loss). RCEdb pays the fsync cost once per Sync event (amortised) and pays index cost lazily; its unique extra cost is SHA-256 per event and refold on cold start. Verdict: **adopt** the TPC-Energy framing (work per joule at the Sync-event granularity) as the metric RCEdb reports, and **leave open** any claim of advantage until measured; mark any projected joules-per-event figure as an estimate.
- The Springer critique (idle-dominated real servers) favours a design whose idle cost is near zero; a fold-on-demand database with no background vacuum/checkpointer has a structural idle advantage, but that is a hypothesis, not a measurement.

### Gaps / unverified background
- Tsirogiannis/Harizopoulos/Shah "Analyzing the Energy Efficiency of a Database Server" (SIGMOD 2010; finding often summarised as "the most energy-efficient configuration is typically the highest performing one") was not retrieved this session; cite only after fetching. SPECpower has no database workload (background, unverified). The TPC-Energy specification text and current result list were not opened.

---

## KQ7. Query termination and totality

### Takeaway
No SQL engine proves termination; SQL Server caps recursion at 100 levels by default (max 32,767), PostgreSQL 14+ offers SEARCH/CYCLE clauses that mark cycles and otherwise relies on the user to test with LIMIT, and all engines fall back on statement timeouts. RCEdb's HS-8 (every query provably terminates) is the thing none of them have, bought by restricting the query language.

### Cited Findings
- SQL Server: "The default value for MAXRECURSION is 100"; exceeding it raises an error after producing rows (a deliberately infinite CTE produced 101 rows before failing); per-query override via OPTION (MAXRECURSION n); bound MAXRECURSION <= 32767 — [Database Journal](https://www.databasejournal.com/ms-sql/tips-for-using-common-table-expressions/); [SQLAuthority 2008](https://blog.sqlauthority.com/2008/07/29/sql-server-sql-server-simple-example-of-recursive-cte-part-2-maxrecursion-prevent-cte-infinite-loop/); [Codidact](https://software.codidact.com/posts/281415/281456)
- PostgreSQL 14+ and the SQL standard offer a CYCLE clause (`CYCLE id SET is_cycle USING cycle_path`) that automates path checking — [coddykit tutorial](https://www.coddykit.com/nl/courses/interview_prep/avoiding-infinite-recursion-9993983) (secondary; the official queries-with.html page could not be fetched)

### Inferences
- The engines' instruments are all extrinsic (depth caps, timeouts, cycle markers) because SQL recursion is Turing-complete enough that termination is undecidable in general. RCEdb refuses the general case by typing: HS-8 is a language restriction (structural recursion over finite state), which is what Datalog-style systems do. Verdict: **adopt** HS-8 as specified, and **adopt** two engine devices as *additional* safety rails, not as the termination argument: a resource bound per query (rows produced / steps) expressed in the type or the host, and cycle detection built into the graph-walk primitives of the proposed property-graph index (so that transitive closure over a cyclic graph is still total by construction, since the node set is finite and visited-set semantics are part of the term).
- Judgement on cost: proven termination forbids unbounded fixpoints over data introduced *during* the query; every recursive query must be bounded by the size of state as of k, which is finite. This is sufficient for reachability, ancestry and closure, which is what SQL recursive CTEs are used for in practice.

### Gaps / unverified background
- Official PostgreSQL queries-with.html text ("test with LIMIT... LIMIT does not reliably stop evaluation") and SQLite's recursive CTE documentation were not retrieved; DuckDB and Oracle CONNECT BY behaviour not retrieved.

---

## KQ8. Lessons the engines' own designers state

### Takeaway
SQLite documents its own quirks (undefined order, flexible typing) and durability trade-offs candidly; the PostgreSQL community turned fsyncgate into a PANIC rule; Stonebraker and Pavlo's 2024 survey exists and Stonebraker still recommends it in late 2025, but its text could not be retrieved this session, so its verdicts on graph and blockchain databases (the two most relevant to RCEdb's property-graph refinement and hash-chained log) cannot be quoted here.

### Cited Findings
- Stonebraker and Pavlo, "What Goes Around Comes Around... And Around...", SIGMOD Record, listed 30 June 2024 (Surveys section); an earlier 2023 arXiv/CoRR version exists — [SIGMOD Record](https://sigmodrecord.org/2024/06/30/what-goes-around-comes-around-and-around); Stonebraker recommended the paper in a December 2025 DBOS webcast — [DBOS webcast](https://dbos.dev/webcast-2025-in-review-with-mike-stonebraker-and-andy-pavlo)
- SQLite's documented quirks relevant here: undefined result order without ORDER BY and undefined tie order (KQ3 sources); durability defaults by journal mode (KQ2 sources) — [SQLite docsrc](https://www.sqlite.org/docsrc/info/a7856e4125c57d75); [SQLite docsrc](https://www.sqlite.org/docsrc/info/bcf687da9c172292)
- PostgreSQL wiki "Fsync Errors" is the community's own post-mortem: PANIC on fsync failure, propagated to InnoDB and WiredTiger — [PostgreSQL wiki](https://wiki.postgresql.org/wiki/Fsync_Errors)
- The 2026 doublewrite-buffer thread shows PostgreSQL designers still debating the FPW/checkpoint tension fifteen years after the 2010-2011 threads — [2026 thread](https://www.postgresql.org/message-id/CANeUpr_cOYTy_Gg48zrb%3D-jv-y7o_4pFvwYu6%3DuECDPqJuZVfw%40mail.gmail.com)

### Inferences
- Background knowledge of the 2024 Stonebraker/Pavlo paper (UNVERIFIED this session; do not cite without fetching the CMU PDF at https://db.cs.cmu.edu/papers/2024/whatgoesaround-sigmodrec2024.pdf): the authors argue the relational model and SQL have absorbed every challenger (document, graph, key-value, array, text) by adding features, judge graph DBMSs as unlikely to displace RDBMSs since RDBMSs can add graph query languages (SQL/PGQ) and get comparable performance, and judge blockchain databases as having no legitimate use case because a trusted party is cheaper than consensus and hash-chaining buys nothing for a single-operator database. If that reading is confirmed by fetching the paper, the implications for RCEdb are direct: (1) the property-graph refinement should be a *view/index* over relational state with a typed query algebra, not a replacement data model (which the survey's history says loses); (2) the hash chain in D must be justified as an integrity/replay-verification device (torn-tail detection, digest-per-k, tamper evidence against the host), not as a trust or consensus device. Verdict (judgement, conditional on the paper): **adopt** the graph as a derived index; **leave open** and justify narrowly the hash chain's purpose; **refuse** any framing of RCEdb as a blockchain database.
- SQLite's lesson is honesty about defaults: RCEdb's spec should publish an equivalent "quirks" page (what the durable mark means, what canonical order is, which float semantics apply) rather than let readers assume SQL semantics.

### Gaps / unverified background
- PostgreSQL wiki "Todo" and "Don't Do This" pages, SQLite "Quirks" page itself (only its ordering sections surfaced through the requirements mirror and docsrc), the DuckDB SIGMOD 2019 paper, the CockroachDB SIGMOD 2020 paper, the Spanner OSDI 2012 paper, and Stonebraker's original 2005 "What Goes Around Comes Around" were not retrieved. Follow-up: fetch the CMU PDF and the two wiki pages; they are short and will supply the designers' numbered lessons.

---

## Summary table of verdicts (all judgements unless noted)

| Engine practice | Evidence | RCEdb verdict | Reason |
|---|---|---|---|
| Physical/page-image WAL, doublewrite, checkpoint truncation | KQ1 sources | Refuse | No mutable heap to protect; logical hash-chained log suffices; truncation breaks HS-9 |
| Group commit / batching before fsync | Janes 34->159 TPS (2012) | Adopt (already implicit in Sync event) | fsync dominates commit cost; make batching window explicit |
| PANIC on fsync error; never advance durable point on error | PostgreSQL wiki Fsync Errors | Adopt | fsyncgate |
| Durability-for-latency default (SQLite WAL NORMAL) | sqlite docsrc | Refuse; keep "mark moves only on Sync" | Zheng/Pillai: defaults lose data |
| Ack-before-durable outputs | — | Adopt opt-in gating of lambda on durable mark; default open | Same bug class one layer up |
| Power-fault record/replay test harness | Zheng OSDI 2014 | Adopt | Refold gives a free oracle |
| Undefined result order / tie order | SQLite requirements | Refuse; canonical total order incl. ties and NULL placement | Reproducibility |
| SSI / predicate locks / retry | PostgreSQL (not fetched) | Refuse; single sequencer | Order is given, not searched |
| Multi-writer / multi-log ordering (TrueTime, HLC) | not fetched | Leave open | RCEdb has no stated answer |
| Bounded time-travel window (gc.ttlseconds, retention days) | CockroachDB docs | Refuse on the log; open for snapshots/old indexes | HS-9 |
| Version visibility by timestamp (temporal tables) | — | Adopt via provenance (created/retracted seq) in property-graph index | Makes as-of-k a keyed filter |
| Snapshots/checkpoints of folded state | engines' PITR practice | Adopt as digest-checked placement artifacts | Bounds refold cost without changing meaning |
| Synchronous IVM on write path, partial language | pg_ivm sources | Refuse sync; adopt deferred, digest-at-k indexes; restrict index language to HS-8 fragment | Write path never blocks; silent-bug risk removed |
| Foreign store for an index | — | Adopt as refoldable cache only | Foreign durability defaults are irrelevant |
| MAXRECURSION / CYCLE / timeouts | SQL Server, PostgreSQL 14 | Adopt as rails only; termination by typing (HS-8) | Extrinsic caps are not proofs |
| Work-per-joule metric at commit granularity | TPC-Energy, Schiper 2014 | Adopt as reporting metric; claims open until measured | No decomposition exists in literature found |
| Graph as data model vs as index | Stonebraker/Pavlo 2024 (not fetched) | Adopt graph as derived index with typed algebra | Survey's history (unverified) says new models lose |
| Hash chain as trust device | same | Narrow to integrity/replay verification; refuse blockchain framing | Single operator; consensus buys nothing |
