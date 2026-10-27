// Node v22.22.0, node:wasi: SIGSEGV on the println after the Vec of 1,000,000 elements
// (rustc --target wasm32-wasip1 -O; node node-wasi-host.mjs node-wasi-segv.wasm);
// with node --no-turbo-fast-api-calls every line prints.
#[allow(dead_code)]
#[derive(Clone)]
enum V { A(i128, &'static str), B(String), C(Vec<V>) }
fn main() {
    for n in [1000usize, 1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000] {
        let x = V::A(0, "i64");
        let v = vec![x; n];
        let w = V::C(v);
        let l = match &w { V::C(v) => v.len(), _ => 0 };
        println!("{n} {l} {}", std::mem::size_of::<V>());
        let w2 = w.clone();
        drop(w2);
    }
}
