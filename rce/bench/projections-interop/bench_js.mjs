// M3 for JavaScript: per-call cost at the boundary (PREREG.json, "boundary_cost").
// Usage: node bench_js.mjs RCE_TREE EMITTED_DIR STREAMS_DIR PASSES REPS > results/bench-js.json
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [TREE, EMITTED, STREAMS, PASSES, REPS] = process.argv.slice(2);
const host = await import(pathToFileURL(path.join(TREE, "examples/interop/js/rce_host.mjs")).href);
const { PROGRAMS, Kept } = await import(pathToFileURL(path.join(TREE, "examples/interop/hand/js/programs.mjs")).href);
const NAMES = ["counter", "bank", "multi_region", "traffic_light", "door", "inventory", "rcedb", "float_keys"];
const ns = () => process.hrtime.bigint();
const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s[(s.length - 1) >> 1]; };

async function emitted(name, texts) {
  const m = await import(pathToFileURL(path.join(EMITTED, "js", name + ".mjs")).href);
  let d = 0n, s = 0n, e = 0n, c = 0;
  for (let i = 0; i < +PASSES; i++) {
    const p = new host.Program(m);
    for (const t of texts) {
      const t0 = ns(); const ev = p.event(host.decode(t)); const t1 = ns(); p.step(ev); const t2 = ns(); p.stateJson(); const t3 = ns();
      d += t1 - t0; s += t2 - t1; e += t3 - t2; c++;
    }
  }
  return [Number(d) / c, Number(s) / c, Number(e) / c];
}

// the hand encode is JSON of the state (BigInt as digits, Maps as pairs)
const handJson = (st) => JSON.stringify(st, (k, x) => (typeof x === "bigint" ? JSON.rawJSON(x.toString()) : x instanceof Map ? [...x.entries()] : x));
function hand(name, texts) {
  const p = PROGRAMS[name];
  let d = 0n, s = 0n, e = 0n, c = 0;
  for (let i = 0; i < +PASSES; i++) {
    let st = p.init();
    for (const t of texts) {
      const t0 = ns(); const ev = host.decode(t); const t1 = ns();
      try { st = p.step(st, ev)[0]; } catch (x) { if (!(x instanceof Kept)) throw x; }
      const t2 = ns(); handJson(st); const t3 = ns();
      d += t1 - t0; s += t2 - t1; e += t3 - t2; c++;
    }
  }
  return [Number(d) / c, Number(s) / c, Number(e) / c];
}

const out = { emitted: {}, hand: {} };
for (const n of NAMES) {
  const texts = JSON.parse(readFileSync(path.join(STREAMS, n + ".0.json"), "utf8")).map((e) => JSON.stringify(e, (k, x) => (Object.is(x, -0) ? JSON.rawJSON("-0.0") : x)));
  for (const [kind, f] of [["emitted", emitted], ["hand", hand]]) {
    const runs = [];
    for (let r = 0; r < +REPS; r++) runs.push(await f(n, texts));
    out[kind][n] = Object.fromEntries(["decode_ns", "step_ns", "encode_ns"].map((k, i) => [k, Math.round(median(runs.map((x) => x[i])))]));
  }
}
process.stdout.write(JSON.stringify({ lang: "js", version: process.version, passes: +PASSES, reps: +REPS, results: out }, null, 1) + "\n");
