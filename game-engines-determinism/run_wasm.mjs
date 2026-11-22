#!/usr/bin/env node
/**
 * Node.js WebAssembly host runner for `sim_wasm.wasm` (`wasm32-unknown-unknown`).
 */
import crypto from "node:crypto";
import fs from "node:fs";
import readline from "node:readline";

const args = process.argv.slice(2);
function getArg(flag, defVal) {
  const idx = args.indexOf(flag);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defVal;
}
const wasmPath = getArg("--wasm", "sim_wasm.wasm");
const ticks = Number(getArg("--ticks", "100000"));
const stride = Number(getArg("--stride", "1000"));
const loops = Number(getArg("--loops", "1"));
const handshake = args.includes("--handshake");

const wasmBytes = fs.readFileSync(wasmPath);
const { instance } = await WebAssembly.instantiate(wasmBytes, {});
const { memory, run_q32_checkpoints, get_out_ptr } = instance.exports;

// Warmup Wasm JIT
run_q32_checkpoints(500, 500);

function executeOnce() {
  const count = run_q32_checkpoints(ticks, stride);
  const ptr = get_out_ptr();
  const mem = new Uint8Array(memory.buffer);
  const view = new DataView(memory.buffer);
  const checkpoints = {};
  for (let k = 0; k < count; k++) {
    const sliceOff = ptr + k * 732;
    const tickVal = view.getUint32(sliceOff, true);
    const snap = mem.subarray(sliceOff, sliceOff + 732);
    checkpoints[String(tickVal)] = crypto.createHash("sha256").update(snap).digest("hex");
  }
  return checkpoints;
}

if (handshake) {
  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  const iter = rl[Symbol.asyncIterator]();
  process.stdout.write("READY\n");
  await iter.next();
  const t0 = process.hrtime.bigint();
  let ck = {};
  for (let l = 0; l < loops; l++) ck = executeOnce();
  const t1 = process.hrtime.bigint();
  const wallMs = Number(t1 - t0) / 1e6 / loops;
  process.stdout.write("DONE\t" + JSON.stringify({ wall_ms: wallMs, loops, checkpoints: ck }) + "\n");
  await iter.next();
  rl.close();
} else {
  const t0 = process.hrtime.bigint();
  const ck = executeOnce();
  const t1 = process.hrtime.bigint();
  process.stdout.write("DONE\t" + JSON.stringify({ wall_ms: Number(t1 - t0) / 1e6, loops: 1, checkpoints: ck }) + "\n");
}
