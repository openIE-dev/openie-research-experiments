import { readFileSync } from 'node:fs';
import { WASI } from 'node:wasi';
const [file, ...args] = process.argv.slice(2);
const wasi = new WASI({ version: 'preview1', args: [file, ...args], env: {}, returnOnExit: true });
const m = await WebAssembly.compile(readFileSync(file));
const i = await WebAssembly.instantiate(m, wasi.getImportObject());
process.exitCode = wasi.start(i);
