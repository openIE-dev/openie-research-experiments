;; SPDX-License-Identifier: Apache-2.0
;; Kit #9 (`kits/standards-bridge/wasm/fuel_kernels.wat`)
;;
;; Demonstrates BOTH halves of the OpenIE WebAssembly thesis:
;;   1. Wasm linear-memory isolation + deterministic instruction fuel (`wasmtime -W fuel=F`)
;;      is the ideal Apache-2.0 front-door sandbox.
;;   2. Instruction fuel != physical Joules: `l1_alu_loop_10m` and `dram_thrash_64mib_10m`
;;      execute the EXACT SAME number of WebAssembly instructions across `10,000,000` loop
;;      iterations (identical `wasmtime` fuel cutoff `F`, trapping at `F - 1` and succeeding
;;      at `F`), while `dram_thrash_64mib_10m` misses L1/L2/L3 across a 64 MiB (`1,024` pages)
;;      linear-memory arena and consumes an order of magnitude more wall-time & RAPL `reported_j`.

(module
  ;; 1,024 Wasm pages * 64 KiB/page = 64 MiB (67,108,864 bytes) bounded linear memory
  (memory (export "memory") 1024 1024)

  ;; Pre-touch all 16,384 physical 4 KiB pages once outside the timed/RAPL steady-state window
  ;; so steady-state runs measure pure cache-hierarchy vs DRAM row-buffer physics, not OS CoW faults.
  (func (export "touch_64mib_pages") (result i32)
    (local $off i32)
    (local $cnt i32)
    (block $done
      (loop $lp
        (br_if $done (i32.ge_u (local.get $off) (i32.const 67108864)))
        (i32.store (local.get $off) (i32.xor (local.get $off) (i32.const 0x5A5AA5A5)))
        (local.set $off (i32.add (local.get $off) (i32.const 4096)))
        (local.set $cnt (i32.add (local.get $cnt) (i32.const 1)))
        (br $lp)
      )
    )
    (local.get $cnt)
  )

  ;; Kernel A: `l1_alu_register_10m` — 10,000,000 loop iterations in CPU registers + L1 hot slot.
  ;; Consumes the EXACT SAME Wasm instruction count (and exact `wasmtime` fuel `F`) as Kernel B!
  (func (export "l1_alu_register_10m") (result i32)
    (local $i i32)
    (local $state i32)
    (local $addr i32)
    (local $val i32)
    (local $acc i32)
    (local.set $state (i32.const 0x12345678))
    (block $exit
      (loop $lp
        (br_if $exit (i32.ge_u (local.get $i) (i32.const 10000000)))
        (local.set $state
          (i32.add (i32.mul (local.get $state) (i32.const 1664525)) (i32.const 1013904223)))
        ;; Mask `0x0000003C` keeps all loads/stores inside a single 64-byte L1-resident cache line!
        (local.set $addr
          (i32.and (i32.shr_u (local.get $state) (i32.const 6)) (i32.const 0x0000003C)))
        (local.set $val
          (i32.xor (i32.load (local.get $addr)) (local.get $state)))
        (i32.store (local.get $addr) (local.get $val))
        (local.set $acc (i32.add (local.get $acc) (local.get $val)))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $lp)
      )
    )
    (local.get $acc)
  )

  ;; Kernel B: `dram_thrash_64mib_10m` — 10,000,000 loop iterations with IDENTICAL opcodes & fuel,
  ;; except mask `0x03FFFFFC` pseudo-randomly strides across all 1,048,576 cache lines of 64 MiB!
  (func (export "dram_thrash_64mib_10m") (result i32)
    (local $i i32)
    (local $state i32)
    (local $addr i32)
    (local $val i32)
    (local $acc i32)
    (local.set $state (i32.const 0x12345678))
    (block $exit
      (loop $lp
        (br_if $exit (i32.ge_u (local.get $i) (i32.const 10000000)))
        (local.set $state
          (i32.add (i32.mul (local.get $state) (i32.const 1664525)) (i32.const 1013904223)))
        ;; Mask `0x03FFFFFC` spans full 64 MiB (exceeding 32 KiB L1, 1 MiB L2, & 32 MiB L3 caches!)
        (local.set $addr
          (i32.and (i32.shr_u (local.get $state) (i32.const 6)) (i32.const 0x03FFFFFC)))
        (local.set $val
          (i32.xor (i32.load (local.get $addr)) (local.get $state)))
        (i32.store (local.get $addr) (local.get $val))
        (local.set $acc (i32.add (local.get $acc) (local.get $val)))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $lp)
      )
    )
    (local.get $acc)
  )
)
