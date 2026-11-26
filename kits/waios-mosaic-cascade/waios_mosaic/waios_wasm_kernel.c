/* SPDX-License-Identifier: Apache-2.0
 * Standalone zero-stdlib WebAssembly (`wasm32-simd128`) kernel for `waiOS` 256x128 ternary matvec.
 */
#include <stdint.h>

__attribute__((visibility("default")))
void waios_wasm_matvec(const int8_t *weights, const int8_t *acts, int32_t *out) {
    /* T-MAC 2-col pair lookup table inside Wasm linear memory (0 multiplications) */
    int32_t lut[64][16];
    for (int g = 0; g < 64; g++) {
        int32_t a0 = (int32_t)acts[2 * g];
        int32_t a1 = (int32_t)acts[2 * g + 1];
        for (int cd = 0; cd < 16; cd++) {
            int c0 = cd & 3;
            int c1 = (cd >> 2) & 3;
            int32_t s0 = (c0 == 1) ? a0 : ((c0 == 2) ? -a0 : 0);
            int32_t s1 = (c1 == 1) ? a1 : ((c1 == 2) ? -a1 : 0);
            lut[g][cd] = s0 + s1;
        }
    }
    for (int r = 0; r < 256; r++) {
        const int8_t *wrow = weights + r * 128;
        int32_t acc = 0;
        for (int g = 0; g < 64; g++) {
            int8_t w0 = wrow[2 * g];
            int8_t w1 = wrow[2 * g + 1];
            uint32_t c0 = (w0 == 1) ? 1U : ((w0 == -1) ? 2U : 0U);
            uint32_t c1 = (w1 == 1) ? 1U : ((w1 == -1) ? 2U : 0U);
            acc += lut[g][c0 | (c1 << 2)];
        }
        out[r] = acc;
    }
}
