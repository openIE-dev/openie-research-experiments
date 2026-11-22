#!/usr/bin/env node
/**
 * JavaScript (Node.js ES2024 BigInt) target for `game-engines` (`GE-H1` Q32.32 & `GE-H2` V8 f64/Math.sin).
 */
import crypto from "node:crypto";
import readline from "node:readline";

const N_BODIES = 16;
const N_PICKUPS = 4;
const ONE = 1n << 32n;
const BOUND = 62n * ONE;
const MAX_V = 48n * ONE;
const DT_Q = 1n << 26n;
const DRAG_IDLE = 4273492459n;
const DRAG_DASH = 4286377361n;
const REST_WALL = 3865470566n;
const ONE_PLUS_E = 7945689498n;
const MIN_DIST = 4n * ONE;
const MIN_DIST_SQ = MIN_DIST * MIN_DIST;
const PICKUP_DIST = 5n * ONE;
const PICKUP_DIST_SQ = PICKUP_DIST * PICKUP_DIST;
const DIAG = 3037000500n;

const DIR_X = [ONE, DIAG, 0n, -DIAG, -ONE, -DIAG, 0n, DIAG];
const DIR_Y = [0n, DIAG, ONE, DIAG, 0n, -DIAG, -ONE, -DIAG];
const ONE_F = 4294967296.0;
const DIR_FX = DIR_X.map((v) => Number(v) / ONE_F);
const DIR_FY = DIR_Y.map((v) => Number(v) / ONE_F);

const INITIAL_SEED = 2316557121413006641n;
const MASK64 = (1n << 64n) - 1n;
const MASK32 = 0xffffffffn;
const HALF32 = 2147483648n;
const SM_C0 = 11400714819323198485n;
const SM_C1 = 13787848793156543929n;
const SM_C2 = 10723151780598845931n;

function splitmix64Next(state) {
  const s = (state + SM_C0) & MASK64;
  let z = s;
  z = ((z ^ (z >> 30n)) * SM_C1) & MASK64;
  z = ((z ^ (z >> 27n)) * SM_C2) & MASK64;
  const out = (z ^ (z >> 31n)) & MASK64;
  return [s, out];
}

function isqrt128(n) {
  if (n === 0n) return 0n;
  let bits = 0n;
  let tmp = n;
  while (tmp > 0n) {
    bits += 1n;
    tmp >>= 1n;
  }
  let x = 1n << ((bits + 1n) >> 1n);
  while (true) {
    const y = (x + n / x) >> 1n;
    if (y >= x) return x;
    x = y;
  }
}

function truncDiv128(num, den) {
  return num / den; // JS BigInt `/` truncates toward zero
}

function initQ32State() {
  let rng = INITIAL_SEED;
  const bx = new BigInt64Array(N_BODIES);
  const by = new BigInt64Array(N_BODIES);
  const bvx = new BigInt64Array(N_BODIES);
  const bvy = new BigInt64Array(N_BODIES);
  const bmass = new BigInt64Array(N_BODIES);
  const bfsm = new Uint8Array(N_BODIES);
  const btimer = new Uint16Array(N_BODIES);
  const bscore = new Uint32Array(N_BODIES);

  for (let i = 0; i < N_BODIES; i++) {
    const gx = BigInt((i & 3) * 30 - 45) * ONE;
    const gy = BigInt((i >> 2) * 30 - 45) * ONE;
    let r1, r2;
    [rng, r1] = splitmix64Next(rng);
    [rng, r2] = splitmix64Next(rng);
    const jx = (r1 & MASK32) - HALF32;
    const jy = ((r1 >> 32n) & MASK32) - HALF32;
    bx[i] = gx + jx;
    by[i] = gy + jy;
    bvx[i] = ((r2 & MASK32) - HALF32) * 24n;
    bvy[i] = (((r2 >> 32n) & MASK32) - HALF32) * 24n;
    bmass[i] = BigInt(4 + (i & 3)) << 30n;
  }

  const px = new BigInt64Array(N_PICKUPS);
  const py = new BigInt64Array(N_PICKUPS);
  const pactive = new Uint8Array(N_PICKUPS);
  const prespawn = new Uint16Array(N_PICKUPS);
  for (let p = 0; p < N_PICKUPS; p++) {
    px[p] = (p & 1) === 0 ? -20n * ONE : 20n * ONE;
    py[p] = (p >> 1) === 0 ? -20n * ONE : 20n * ONE;
    pactive[p] = 1;
    prespawn[p] = 0;
  }
  return { tick: 0, rng, bx, by, bvx, bvy, bmass, bfsm, btimer, bscore, px, py, pactive, prespawn };
}

function serializeQ32State(st, buf, view) {
  let off = 0;
  view.setUint32(off, st.tick, true); off += 4;
  view.setBigUint64(off, st.rng, true); off += 8;
  for (let i = 0; i < N_BODIES; i++) {
    view.setBigInt64(off, st.bx[i], true); off += 8;
    view.setBigInt64(off, st.by[i], true); off += 8;
    view.setBigInt64(off, st.bvx[i], true); off += 8;
    view.setBigInt64(off, st.bvy[i], true); off += 8;
    view.setUint32(off, st.bscore[i], true); off += 4;
    view.setUint16(off, st.btimer[i], true); off += 2;
    view.setUint8(off, st.bfsm[i]); off += 1;
    view.setUint8(off, 0); off += 1;
  }
  for (let p = 0; p < N_PICKUPS; p++) {
    view.setBigInt64(off, st.px[p], true); off += 8;
    view.setBigInt64(off, st.py[p], true); off += 8;
    view.setUint16(off, st.prespawn[p], true); off += 2;
    view.setUint8(off, st.pactive[p]); off += 1;
    view.setUint8(off, 0); off += 1;
  }
  return buf;
}

function runQ32Sim(ticks, stride) {
  const st = initQ32State();
  const { bx, by, bvx, bvy, bmass, bfsm, btimer, bscore, px, py, pactive, prespawn } = st;
  let rng = st.rng;
  let tick = 0;
  const buf = Buffer.alloc(732);
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const checkpoints = {};
  const deact = new Uint8Array(N_PICKUPS);
  const resp = new Uint8Array(N_PICKUPS);

  for (let step = 0; step < ticks; step++) {
    let ev;
    [rng, ev] = splitmix64Next(rng);
    const actor = Number(ev & 15n);
    const d = Number((ev >> 4n) & 7n);
    const wantDash = ((ev >> 7n) & 3n) === 0n;
    if (wantDash && bfsm[actor] === 0) {
      bfsm[actor] = 1;
      btimer[actor] = 12;
      bvx[actor] += 6n * DIR_X[d];
      bvy[actor] += 6n * DIR_Y[d];
    } else {
      bvx[actor] += 2n * DIR_X[d];
      bvy[actor] += 2n * DIR_Y[d];
    }

    for (let i = 0; i < N_BODIES; i++) {
      if (bfsm[i] === 1) {
        btimer[i] -= 1;
        if (btimer[i] === 0) {
          bfsm[i] = 2;
          btimer[i] = 40;
        }
      } else if (bfsm[i] === 2) {
        btimer[i] -= 1;
        if (btimer[i] === 0) {
          bfsm[i] = 0;
        }
      }
      const drag = bfsm[i] === 1 ? DRAG_DASH : DRAG_IDLE;
      let vx = (bvx[i] * drag) >> 32n;
      let vy = (bvy[i] * drag) >> 32n;
      if (vx > MAX_V) vx = MAX_V;
      else if (vx < -MAX_V) vx = -MAX_V;
      if (vy > MAX_V) vy = MAX_V;
      else if (vy < -MAX_V) vy = -MAX_V;

      let x = bx[i] + ((vx * DT_Q) >> 32n);
      let y = by[i] + ((vy * DT_Q) >> 32n);
      if (x > BOUND) {
        x = 2n * BOUND - x;
        vx = -((vx * REST_WALL) >> 32n);
      } else if (x < -BOUND) {
        x = -2n * BOUND - x;
        vx = -((vx * REST_WALL) >> 32n);
      }
      if (y > BOUND) {
        y = 2n * BOUND - y;
        vy = -((vy * REST_WALL) >> 32n);
      } else if (y < -BOUND) {
        y = -2n * BOUND - y;
        vy = -((vy * REST_WALL) >> 32n);
      }
      bx[i] = x;
      by[i] = y;
      bvx[i] = vx;
      bvy[i] = vy;
    }

    for (let i = 0; i < N_BODIES; i++) {
      for (let j = i + 1; j < N_BODIES; j++) {
        const dx = bx[j] - bx[i];
        const dy = by[j] - by[i];
        const distSq = dx * dx + dy * dy;
        if (distSq > 0n && distSq < MIN_DIST_SQ) {
          const dist = isqrt128(distSq);
          const nx = truncDiv128(dx * ONE, dist);
          const ny = truncDiv128(dy * ONE, dist);
          const sep = (MIN_DIST - dist) >> 1n;
          const cx = (sep * nx) >> 32n;
          const cy = (sep * ny) >> 32n;
          bx[i] -= cx;
          by[i] -= cy;
          bx[j] += cx;
          by[j] += cy;

          const rvx = bvx[j] - bvx[i];
          const rvy = bvy[j] - bvy[i];
          const vn = ((rvx * nx) >> 32n) + ((rvy * ny) >> 32n);
          if (vn < 0n) {
            const jBase = ((-vn) * ONE_PLUS_E) >> 32n;
            const msum = bmass[i] + bmass[j];
            const dvi = truncDiv128(jBase * bmass[j], msum);
            const dvj = truncDiv128(jBase * bmass[i], msum);
            bvx[i] -= (dvi * nx) >> 32n;
            bvy[i] -= (dvi * ny) >> 32n;
            bvx[j] += (dvj * nx) >> 32n;
            bvy[j] += (dvj * ny) >> 32n;
          }
        }
      }
    }

    deact.fill(0);
    resp.fill(0);
    for (let p = 0; p < N_PICKUPS; p++) {
      if (pactive[p] === 1) {
        const pxp = px[p];
        const pyp = py[p];
        for (let i = 0; i < N_BODIES; i++) {
          const pdx = bx[i] - pxp;
          const pdy = by[i] - pyp;
          if (pdx * pdx + pdy * pdy <= PICKUP_DIST_SQ) {
            bscore[i] += 1;
            deact[p] = 1;
            break;
          }
        }
      } else {
        prespawn[p] -= 1;
        if (prespawn[p] === 0) resp[p] = 1;
      }
    }
    for (let p = 0; p < N_PICKUPS; p++) {
      if (deact[p] === 1) {
        pactive[p] = 0;
        prespawn[p] = 75;
      }
      if (resp[p] === 1) {
        let rp;
        [rng, rp] = splitmix64Next(rng);
        px[p] = ((rp & MASK32) - HALF32) * 80n;
        py[p] = (((rp >> 32n) & MASK32) - HALF32) * 80n;
        pactive[p] = 1;
      }
    }

    tick += 1;
    if (stride > 0 && (tick % stride === 0 || tick === ticks)) {
      st.tick = tick;
      st.rng = rng;
      serializeQ32State(st, buf, view);
      checkpoints[String(tick)] = crypto.createHash("sha256").update(buf).digest("hex");
    }
  }
  return checkpoints;
}

function canonF64(v) {
  return v === 0 ? 0.0 : v;
}

function runFloatTrace(ticks, useTrig) {
  const stQ = initQ32State();
  let rng = stQ.rng;
  const bx = Float64Array.from(stQ.bx, (v) => Number(v) / ONE_F);
  const by = Float64Array.from(stQ.by, (v) => Number(v) / ONE_F);
  const bvx = Float64Array.from(stQ.bvx, (v) => Number(v) / ONE_F);
  const bvy = Float64Array.from(stQ.bvy, (v) => Number(v) / ONE_F);
  const bmass = Float64Array.from(stQ.bmass, (v) => Number(v) / ONE_F);
  const bfsm = new Uint8Array(stQ.bfsm);
  const btimer = new Uint16Array(stQ.btimer);
  const bscore = new Uint32Array(stQ.bscore);
  const px = Float64Array.from(stQ.px, (v) => Number(v) / ONE_F);
  const py = Float64Array.from(stQ.py, (v) => Number(v) / ONE_F);
  const pactive = new Uint8Array(stQ.pactive);
  const prespawn = new Uint16Array(stQ.prespawn);

  const dtF = 1.0 / 64.0;
  const dragIdleF = Number(DRAG_IDLE) / ONE_F;
  const dragDashF = Number(DRAG_DASH) / ONE_F;
  const restWallF = Number(REST_WALL) / ONE_F;
  const onePlusEF = Number(ONE_PLUS_E) / ONE_F;

  const ieeeBuf = Buffer.alloc(732);
  const ieeeView = new DataView(ieeeBuf.buffer, ieeeBuf.byteOffset, ieeeBuf.byteLength);
  const mmBuf = Buffer.alloc(4 + N_BODIES * 23);
  const mmView = new DataView(mmBuf.buffer, mmBuf.byteOffset, mmBuf.byteLength);
  const gpBuf = Buffer.alloc(4 + N_BODIES * 6 + N_PICKUPS);
  const gpView = new DataView(gpBuf.buffer, gpBuf.byteOffset, gpBuf.byteLength);

  const out = [];
  let tick = 0;
  for (let step = 0; step < ticks; step++) {
    let ev;
    [rng, ev] = splitmix64Next(rng);
    const actor = Number(ev & 15n);
    const d = Number((ev >> 4n) & 7n);
    const wantDash = ((ev >> 7n) & 3n) === 0n;
    let ux, uy;
    if (useTrig) {
      const theta = 0.017453292519943295 * (tick + 1) + 0.7853981633974483 * d;
      ux = Math.cos(theta);
      uy = Math.sin(theta);
    } else {
      ux = DIR_FX[d];
      uy = DIR_FY[d];
    }
    if (wantDash && bfsm[actor] === 0) {
      bfsm[actor] = 1;
      btimer[actor] = 12;
      bvx[actor] = bvx[actor] + 6.0 * ux;
      bvy[actor] = bvy[actor] + 6.0 * uy;
    } else {
      bvx[actor] = bvx[actor] + 2.0 * ux;
      bvy[actor] = bvy[actor] + 2.0 * uy;
    }

    for (let i = 0; i < N_BODIES; i++) {
      if (bfsm[i] === 1) {
        btimer[i] -= 1;
        if (btimer[i] === 0) {
          bfsm[i] = 2;
          btimer[i] = 40;
        }
      } else if (bfsm[i] === 2) {
        btimer[i] -= 1;
        if (btimer[i] === 0) bfsm[i] = 0;
      }
      const drag = bfsm[i] === 1 ? dragDashF : dragIdleF;
      let vx = bvx[i] * drag;
      let vy = bvy[i] * drag;
      if (vx > 48.0) vx = 48.0;
      else if (vx < -48.0) vx = -48.0;
      if (vy > 48.0) vy = 48.0;
      else if (vy < -48.0) vy = -48.0;
      let x = bx[i] + vx * dtF;
      let y = by[i] + vy * dtF;
      if (x > 62.0) {
        x = 124.0 - x;
        vx = -(vx * restWallF);
      } else if (x < -62.0) {
        x = -124.0 - x;
        vx = -(vx * restWallF);
      }
      if (y > 62.0) {
        y = 124.0 - y;
        vy = -(vy * restWallF);
      } else if (y < -62.0) {
        y = -124.0 - y;
        vy = -(vy * restWallF);
      }
      bx[i] = x;
      by[i] = y;
      bvx[i] = vx;
      bvy[i] = vy;
    }

    for (let i = 0; i < N_BODIES; i++) {
      for (let j = i + 1; j < N_BODIES; j++) {
        const dx = bx[j] - bx[i];
        const dy = by[j] - by[i];
        const distSq = dx * dx + dy * dy;
        if (distSq > 0.0 && distSq < 16.0) {
          const dist = Math.sqrt(distSq);
          const nx = dx / dist;
          const ny = dy / dist;
          const sep = 0.5 * (4.0 - dist);
          bx[i] = bx[i] - sep * nx;
          by[i] = by[i] - sep * ny;
          bx[j] = bx[j] + sep * nx;
          by[j] = by[j] + sep * ny;
          const rvx = bvx[j] - bvx[i];
          const rvy = bvy[j] - bvy[i];
          const vn = rvx * nx + rvy * ny;
          if (vn < 0.0) {
            const jBase = (-vn) * onePlusEF;
            const msum = bmass[i] + bmass[j];
            const dvi = (jBase * bmass[j]) / msum;
            const dvj = (jBase * bmass[i]) / msum;
            bvx[i] = bvx[i] - dvi * nx;
            bvy[i] = bvy[i] - dvi * ny;
            bvx[j] = bvx[j] + dvj * nx;
            bvy[j] = bvy[j] + dvj * ny;
          }
        }
      }
    }

    const deact = [0, 0, 0, 0];
    const resp = [0, 0, 0, 0];
    for (let p = 0; p < N_PICKUPS; p++) {
      if (pactive[p] === 1) {
        for (let i = 0; i < N_BODIES; i++) {
          const pdx = bx[i] - px[p];
          const pdy = by[i] - py[p];
          if (pdx * pdx + pdy * pdy <= 25.0) {
            bscore[i] += 1;
            deact[p] = 1;
            break;
          }
        }
      } else {
        prespawn[p] -= 1;
        if (prespawn[p] === 0) resp[p] = 1;
      }
    }
    for (let p = 0; p < N_PICKUPS; p++) {
      if (deact[p] === 1) {
        pactive[p] = 0;
        prespawn[p] = 75;
      }
      if (resp[p] === 1) {
        let rp;
        [rng, rp] = splitmix64Next(rng);
        px[p] = Number(((rp & MASK32) - HALF32) * 80n) / ONE_F;
        py[p] = Number((((rp >> 32n) & MASK32) - HALF32) * 80n) / ONE_F;
        pactive[p] = 1;
      }
    }

    tick += 1;
    let o1 = 0, o2 = 0, o3 = 0;
    ieeeView.setUint32(o1, tick, true); o1 += 4;
    ieeeView.setBigUint64(o1, rng, true); o1 += 8;
    mmView.setUint32(o2, tick, true); o2 += 4;
    gpView.setUint32(o3, tick, true); o3 += 4;
    for (let i = 0; i < N_BODIES; i++) {
      ieeeView.setFloat64(o1, canonF64(bx[i]), true); o1 += 8;
      ieeeView.setFloat64(o1, canonF64(by[i]), true); o1 += 8;
      ieeeView.setFloat64(o1, canonF64(bvx[i]), true); o1 += 8;
      ieeeView.setFloat64(o1, canonF64(bvy[i]), true); o1 += 8;
      ieeeView.setUint32(o1, bscore[i], true); o1 += 4;
      ieeeView.setUint16(o1, btimer[i], true); o1 += 2;
      ieeeView.setUint8(o1, bfsm[i]); o1 += 1;
      ieeeView.setUint8(o1, 0); o1 += 1;

      mmView.setBigInt64(o2, BigInt(Math.floor(bx[i] * 1000.0)), true); o2 += 8;
      mmView.setBigInt64(o2, BigInt(Math.floor(by[i] * 1000.0)), true); o2 += 8;
      mmView.setUint32(o2, bscore[i], true); o2 += 4;
      mmView.setUint16(o2, btimer[i], true); o2 += 2;
      mmView.setUint8(o2, bfsm[i]); o2 += 1;

      const quad = (bx[i] >= 0.0 ? 1 : 0) | (by[i] >= 0.0 ? 2 : 0);
      gpView.setUint32(o3, bscore[i], true); o3 += 4;
      gpView.setUint8(o3, bfsm[i]); o3 += 1;
      gpView.setUint8(o3, quad); o3 += 1;
    }
    for (let p = 0; p < N_PICKUPS; p++) {
      ieeeView.setFloat64(o1, canonF64(px[p]), true); o1 += 8;
      ieeeView.setFloat64(o1, canonF64(py[p]), true); o1 += 8;
      ieeeView.setUint16(o1, prespawn[p], true); o1 += 2;
      ieeeView.setUint8(o1, pactive[p]); o1 += 1;
      ieeeView.setUint8(o1, 0); o1 += 1;
      gpView.setUint8(o3, pactive[p]); o3 += 1;
    }
    out.push([
      crypto.createHash("sha256").update(ieeeBuf).digest("hex").slice(0, 16),
      crypto.createHash("sha256").update(mmBuf).digest("hex").slice(0, 16),
      crypto.createHash("sha256").update(gpBuf).digest("hex").slice(0, 16),
    ]);
  }
  return out;
}

const args = process.argv.slice(2);
function getArg(flag, defVal) {
  const idx = args.indexOf(flag);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defVal;
}
const mode = getArg("--mode", "q32");
const ticks = Number(getArg("--ticks", "100000"));
const stride = Number(getArg("--stride", "1000"));
const loops = Number(getArg("--loops", "1"));
const handshake = args.includes("--handshake");

if (mode === "q32") {
  runQ32Sim(500, 500); // V8 JIT warmup
  if (handshake) {
    const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
    const iter = rl[Symbol.asyncIterator]();
    process.stdout.write("READY\n");
    await iter.next();
    const t0 = process.hrtime.bigint();
    let ck = {};
    for (let l = 0; l < loops; l++) ck = runQ32Sim(ticks, stride);
    const t1 = process.hrtime.bigint();
    const wallMs = Number(t1 - t0) / 1e6 / loops;
    process.stdout.write("DONE\t" + JSON.stringify({ wall_ms: wallMs, loops, checkpoints: ck }) + "\n");
    await iter.next();
    rl.close();
  } else {
    const t0 = process.hrtime.bigint();
    const ck = runQ32Sim(ticks, stride);
    const t1 = process.hrtime.bigint();
    process.stdout.write("DONE\t" + JSON.stringify({ wall_ms: Number(t1 - t0) / 1e6, loops: 1, checkpoints: ck }) + "\n");
  }
} else {
  const trace = runFloatTrace(ticks, mode === "f64_trig");
  process.stdout.write(JSON.stringify({ trace }) + "\n");
}
