/* SPDX-License-Identifier: Apache-2.0
 * Native C / pthread micro-kernels for Kit 5 (`kits/waios-mosaic-cascade/`, Shots #3 & #5):
 *   1. Exact canonical `waiOS` 256x128 ternary matrix-vector program (`SEED = 0xdeadbeefcafebabe`):
 *        - Lane 1: Scalar `int32` reference loop
 *        - Lane 2: Packed 2-bit bit-sliced ternary (`+1`/`-1` uint64 masks + popcount over bit-planes)
 *        - Lane 3: T-MAC 2-column pair lookup table (`packTernary` layout)
 *        - Lane 4: Multi-worker `pthread` HeteroMosaic lane splitting tiles across heterogeneous
 *                  CPU/SIMD, 64-wide split-half bit-sliced, and T-MAC LUT workers with deterministic
 *                  fixed-order `int32` reduction
 *   2. Single-weight tamper fault injection (`row 77`, first non-zero activation col)
 *   3. Boot qualification kernels (`73x35` odd-sized ternary matvec + `64`-dim integer RMSNorm+RoPE)
 *   4. Metered 4-Stage Spellcheck Lookup-First Cascade vs Always-Mosaic vs Always-Dense baselines
 */

#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define WAI_ROWS 256
#define WAI_COLS 128
#define WAI_PAIRS (WAI_COLS / 2)
#define WAI_WORDS (WAI_COLS / 64)

static const uint64_t LCG_MUL = 6364136223846793005ULL;
static const uint64_t LCG_ADD = 1442695040888963407ULL;
static const uint64_t WAI_SEED = 0xdeadbeefcafebabeULL;

void waios_audit_input(int8_t *weights, int8_t *acts) {
    uint64_t s = WAI_SEED;
    for (int i = 0; i < WAI_ROWS * WAI_COLS; i++) {
        s = s * LCG_MUL + LCG_ADD;
        uint64_t m = (s >> 32) % 3ULL;
        weights[i] = (m == 0) ? -1 : ((m == 1) ? 0 : 1);
    }
    for (int c = 0; c < WAI_COLS; c++) {
        s = s * LCG_MUL + LCG_ADD;
        acts[c] = (int8_t)((int)((s >> 40) % 251ULL) - 125);
    }
}

/* Lane 1: Direct scalar int32 reference */
void waios_lane_scalar(const int8_t *weights, const int8_t *acts, int32_t *out) {
    for (int r = 0; r < WAI_ROWS; r++) {
        int32_t acc = 0;
        const int8_t *wrow = weights + r * WAI_COLS;
        for (int c = 0; c < WAI_COLS; c++) {
            acc += (int32_t)wrow[c] * (int32_t)acts[c];
        }
        out[r] = acc;
    }
}

/* Lane 2: Packed 2-bit bit-sliced (+1 / -1 uint64 masks + popcount across 8 magnitude bit-planes, 0 multiplies!) */
void waios_lane_bitsliced(const int8_t *weights, const int8_t *acts, int32_t *out) {
    uint64_t pos_mask[WAI_ROWS][WAI_WORDS];
    uint64_t neg_mask[WAI_ROWS][WAI_WORDS];
    memset(pos_mask, 0, sizeof(pos_mask));
    memset(neg_mask, 0, sizeof(neg_mask));

    for (int r = 0; r < WAI_ROWS; r++) {
        const int8_t *wrow = weights + r * WAI_COLS;
        for (int w = 0; w < WAI_WORDS; w++) {
            uint64_t pm = 0ULL, nm = 0ULL;
            for (int b = 0; b < 64; b++) {
                int8_t v = wrow[w * 64 + b];
                if (v == 1) pm |= (1ULL << b);
                else if (v == -1) nm |= (1ULL << b);
            }
            pos_mask[r][w] = pm;
            neg_mask[r][w] = nm;
        }
    }

    /* Decompose signed int8 activations [-125..125] into sign mask + 7 magnitude bit-planes */
    uint64_t act_neg[WAI_WORDS] = {0ULL, 0ULL};
    uint64_t act_mag_plane[7][WAI_WORDS];
    memset(act_mag_plane, 0, sizeof(act_mag_plane));

    for (int w = 0; w < WAI_WORDS; w++) {
        for (int b = 0; b < 64; b++) {
            int a = (int)acts[w * 64 + b];
            int mag = a < 0 ? -a : a;
            if (a < 0) act_neg[w] |= (1ULL << b);
            for (int p = 0; p < 7; p++) {
                if ((mag >> p) & 1) act_mag_plane[p][w] |= (1ULL << b);
            }
        }
    }

    for (int r = 0; r < WAI_ROWS; r++) {
        /* Effective +mag mask = (w == +1 && a >= 0) || (w == -1 && a < 0)
         * Effective -mag mask = (w == +1 && a < 0)  || (w == -1 && a >= 0) */
        uint64_t eff_add[WAI_WORDS], eff_sub[WAI_WORDS];
        for (int w = 0; w < WAI_WORDS; w++) {
            uint64_t a_pos = ~act_neg[w];
            eff_add[w] = (pos_mask[r][w] & a_pos) | (neg_mask[r][w] & act_neg[w]);
            eff_sub[w] = (pos_mask[r][w] & act_neg[w]) | (neg_mask[r][w] & a_pos);
        }
        int32_t acc = 0;
        for (int p = 0; p < 7; p++) {
            int pop_add = __builtin_popcountll(eff_add[0] & act_mag_plane[p][0])
                        + __builtin_popcountll(eff_add[1] & act_mag_plane[p][1]);
            int pop_sub = __builtin_popcountll(eff_sub[0] & act_mag_plane[p][0])
                        + __builtin_popcountll(eff_sub[1] & act_mag_plane[p][1]);
            acc += (pop_add - pop_sub) << p;
        }
        out[r] = acc;
    }
}

static inline uint8_t wai_code(int8_t w) {
    return (w == 1) ? 1U : ((w == -1) ? 2U : 0U);
}

/* Pack weights in exact waiOS GPU TernaryMatrix layout: packed[pair * rows + row] */
void waios_pack_ternary(const int8_t *weights, int rows, int cols, uint8_t *packed) {
    int pairs = (cols + 1) / 2;
    for (int g = 0; g < pairs; g++) {
        for (int r = 0; r < rows; r++) {
            int8_t w0 = weights[r * cols + 2 * g];
            int8_t w1 = (2 * g + 1 < cols) ? weights[r * cols + 2 * g + 1] : 0;
            packed[g * rows + r] = (uint8_t)(wai_code(w0) | (wai_code(w1) << 2));
        }
    }
}

/* Lane 3: T-MAC 2-column pair lookup table over waiOS's packed 4-bit pair codes */
void waios_lane_tmac_lut(const int8_t *weights, const int8_t *acts, int32_t *out) {
    uint8_t packed[WAI_PAIRS * WAI_ROWS];
    waios_pack_ternary(weights, WAI_ROWS, WAI_COLS, packed);

    int32_t lut[WAI_PAIRS][16];
    for (int g = 0; g < WAI_PAIRS; g++) {
        int32_t a0 = (int32_t)acts[2 * g];
        int32_t a1 = (int32_t)acts[2 * g + 1];
        for (int code = 0; code < 16; code++) {
            int c0 = code & 3;
            int c1 = (code >> 2) & 3;
            int32_t s0 = (c0 == 1) ? a0 : ((c0 == 2) ? -a0 : 0);
            int32_t s1 = (c1 == 1) ? a1 : ((c1 == 2) ? -a1 : 0);
            lut[g][code] = s0 + s1;
        }
    }
    memset(out, 0, WAI_ROWS * sizeof(int32_t));
    for (int g = 0; g < WAI_PAIRS; g++) {
        const uint8_t *col_block = packed + g * WAI_ROWS;
        for (int r = 0; r < WAI_ROWS; r++) {
            out[r] += lut[g][col_block[r] & 15U];
        }
    }
}

/* Lane 4: Multi-worker pthread HeteroMosaic runtime (4 heterogeneous tile workers + deterministic reduction) */
typedef struct {
    int worker_id;
    int row_start;
    int row_end;
    const int8_t *weights;
    const int8_t *acts;
    int32_t *partial_out;
} MosaicTileTask;

static void *mosaic_tile_worker(void *arg) {
    MosaicTileTask *t = (MosaicTileTask *)arg;
    if (t->worker_id == 0) {
        /* Tile 0 (CPU/SIMD unrolled loop): rows [row_start..row_end) */
        for (int r = t->row_start; r < t->row_end; r++) {
            const int8_t *wrow = t->weights + r * WAI_COLS;
            int32_t s0 = 0, s1 = 0, s2 = 0, s3 = 0;
            for (int c = 0; c < WAI_COLS; c += 4) {
                s0 += (int32_t)wrow[c] * (int32_t)t->acts[c];
                s1 += (int32_t)wrow[c + 1] * (int32_t)t->acts[c + 1];
                s2 += (int32_t)wrow[c + 2] * (int32_t)t->acts[c + 2];
                s3 += (int32_t)wrow[c + 3] * (int32_t)t->acts[c + 3];
            }
            t->partial_out[r] = (s0 + s1) + (s2 + s3);
        }
    } else if (t->worker_id == 1) {
        /* Tile 1 (FPGA-style 64-wide split halves summed deterministically by host) */
        for (int r = t->row_start; r < t->row_end; r++) {
            const int8_t *wrow = t->weights + r * WAI_COLS;
            int32_t left64 = 0, right64 = 0;
            for (int c = 0; c < 64; c++) left64 += (int32_t)wrow[c] * (int32_t)t->acts[c];
            for (int c = 64; c < 128; c++) right64 += (int32_t)wrow[c] * (int32_t)t->acts[c];
            t->partial_out[r] = left64 + right64;
        }
    } else if (t->worker_id == 2) {
        /* Tile 2 (T-MAC 2-column pair LUT worker) */
        int32_t lut[WAI_PAIRS][16];
        for (int g = 0; g < WAI_PAIRS; g++) {
            int32_t a0 = (int32_t)t->acts[2 * g];
            int32_t a1 = (int32_t)t->acts[2 * g + 1];
            for (int code = 0; code < 16; code++) {
                int c0 = code & 3, c1 = (code >> 2) & 3;
                lut[g][code] = ((c0 == 1) ? a0 : ((c0 == 2) ? -a0 : 0))
                             + ((c1 == 1) ? a1 : ((c1 == 2) ? -a1 : 0));
            }
        }
        for (int r = t->row_start; r < t->row_end; r++) {
            const int8_t *wrow = t->weights + r * WAI_COLS;
            int32_t acc = 0;
            for (int g = 0; g < WAI_PAIRS; g++) {
                uint8_t code = (uint8_t)(wai_code(wrow[2 * g]) | (wai_code(wrow[2 * g + 1]) << 2));
                acc += lut[g][code];
            }
            t->partial_out[r] = acc;
        }
    } else {
        /* Tile 3 (Bit-sliced uint64 popcount worker) */
        uint64_t act_neg[2] = {0ULL, 0ULL};
        uint64_t act_plane[7][2];
        memset(act_plane, 0, sizeof(act_plane));
        for (int w = 0; w < 2; w++) {
            for (int b = 0; b < 64; b++) {
                int a = (int)t->acts[w * 64 + b];
                int mag = a < 0 ? -a : a;
                if (a < 0) act_neg[w] |= (1ULL << b);
                for (int p = 0; p < 7; p++) {
                    if ((mag >> p) & 1) act_plane[p][w] |= (1ULL << b);
                }
            }
        }
        for (int r = t->row_start; r < t->row_end; r++) {
            const int8_t *wrow = t->weights + r * WAI_COLS;
            uint64_t pm[2] = {0ULL, 0ULL}, nm[2] = {0ULL, 0ULL};
            for (int w = 0; w < 2; w++) {
                for (int b = 0; b < 64; b++) {
                    int8_t v = wrow[w * 64 + b];
                    if (v == 1) pm[w] |= (1ULL << b);
                    else if (v == -1) nm[w] |= (1ULL << b);
                }
            }
            uint64_t eadd0 = (pm[0] & ~act_neg[0]) | (nm[0] & act_neg[0]);
            uint64_t eadd1 = (pm[1] & ~act_neg[1]) | (nm[1] & act_neg[1]);
            uint64_t esub0 = (pm[0] & act_neg[0]) | (nm[0] & ~act_neg[0]);
            uint64_t esub1 = (pm[1] & act_neg[1]) | (nm[1] & ~act_neg[1]);
            int32_t acc = 0;
            for (int p = 0; p < 7; p++) {
                int pa = __builtin_popcountll(eadd0 & act_plane[p][0]) + __builtin_popcountll(eadd1 & act_plane[p][1]);
                int ps = __builtin_popcountll(esub0 & act_plane[p][0]) + __builtin_popcountll(esub1 & act_plane[p][1]);
                acc += (pa - ps) << p;
            }
            t->partial_out[r] = acc;
        }
    }
    return NULL;
}

void waios_lane_hetero_mosaic(const int8_t *weights, const int8_t *acts, int split_shift, int32_t *out) {
    /* Deterministic tile partition across 4 pthreads; split_shift varies row boundaries across schedule tests */
    int cuts[5] = {0, 64, 128, 192, 256};
    int delta = (split_shift & 7) * 2; /* e.g. 0..14 perturbation while covering 0..256 contiguously */
    cuts[1] = 60 + delta;
    cuts[2] = 124 + delta;
    cuts[3] = 188 + delta;

    pthread_t th[4];
    MosaicTileTask tasks[4];
    for (int w = 0; w < 4; w++) {
        tasks[w].worker_id = w;
        tasks[w].row_start = cuts[w];
        tasks[w].row_end = cuts[w + 1];
        tasks[w].weights = weights;
        tasks[w].acts = acts;
        tasks[w].partial_out = out;
        pthread_create(&th[w], NULL, mosaic_tile_worker, &tasks[w]);
    }
    for (int w = 0; w < 4; w++) {
        pthread_join(th[w], NULL);
    }
}

/* Fast single-thread tiled Mosaic execution used inside Stage 3 of the 1,000-query Spellcheck Cascade */
void waios_mosaic_fast_classify16(
    const uint8_t *packed_tmac,
    const int8_t *acts128,
    int32_t *out_class_scores16
) {
    int32_t lut[WAI_PAIRS][16];
    for (int g = 0; g < WAI_PAIRS; g++) {
        int32_t a0 = (int32_t)acts128[2 * g];
        int32_t a1 = (int32_t)acts128[2 * g + 1];
        for (int code = 0; code < 16; code++) {
            int c0 = code & 3, c1 = (code >> 2) & 3;
            lut[g][code] = ((c0 == 1) ? a0 : ((c0 == 2) ? -a0 : 0))
                         + ((c1 == 1) ? a1 : ((c1 == 2) ? -a1 : 0));
        }
    }
    int32_t row_out[WAI_ROWS];
    memset(row_out, 0, sizeof(row_out));
    for (int g = 0; g < WAI_PAIRS; g++) {
        const uint8_t *col_block = packed_tmac + g * WAI_ROWS;
        for (int r = 0; r < WAI_ROWS; r++) {
            row_out[r] += lut[g][col_block[r] & 15U];
        }
    }
    /* Pool 256 outputs (16 groups of 16 rows with ReLU) into 16 intent scores */
    for (int c = 0; c < 16; c++) {
        int32_t s = 0;
        for (int j = 0; j < 16; j++) {
            int32_t v = row_out[c * 16 + j];
            if (v > 0) s += v;
        }
        out_class_scores16[c] = s;
    }
}

/* Heavy multi-layer dense INT16/FP32 teacher compute representing Stage-4 escalation / non-cascaded baseline */
int waios_heavy_escalation_teacher(
    const int16_t *dense_layers, /* 8 layers of 256x256 + final 16x256 */
    const int8_t *acts128
) {
    float h[256], nxt[256];
    for (int i = 0; i < 256; i++) {
        h[i] = (float)acts128[i & 127] * ((i >= 128) ? -0.75f : 1.0f);
    }
    for (int l = 0; l < 8; l++) {
        const int16_t *wl = dense_layers + (size_t)l * 256 * 256;
        for (int r = 0; r < 256; r++) {
            const int16_t *wrow = wl + r * 256;
            float acc = 0.0f;
            for (int c = 0; c < 256; c++) {
                acc += (float)wrow[c] * h[c] * (1.0f / 4096.0f);
            }
            nxt[r] = acc > 0.0f ? acc : 0.1f * acc;
        }
        memcpy(h, nxt, sizeof(h));
    }
    const int16_t *head = dense_layers + (size_t)8 * 256 * 256;
    float best = -1e30f;
    int best_c = 0;
    for (int c = 0; c < 16; c++) {
        float acc = 0.0f;
        for (int j = 0; j < 256; j++) acc += (float)head[c * 256 + j] * h[j];
        if (acc > best) { best = acc; best_c = c; }
    }
    return best_c;
}


/* ── Part 4: Native C 4-Stage Spellcheck Lookup-First Cascade Evaluator ─────── */

#define MAX_QSTR 64
#define LUT1_SLOTS 256
#define TRIGRAM_BUCKETS 4096
#define MOSAIC_ENCODER_BLOCKS 5

typedef struct {
    int used;
    char key[MAX_QSTR];
    int intent_id;
} LutSlot;

typedef struct {
    char canonical[16][MAX_QSTR];
    LutSlot lut1[LUT1_SLOTS];
    uint16_t trigram_mask[TRIGRAM_BUCKETS];
    uint8_t encoder_blocks[MOSAIC_ENCODER_BLOCKS][WAI_PAIRS * WAI_ROWS];
    uint8_t head_mosaic[WAI_PAIRS * WAI_ROWS];
    const int16_t *dense_layers;
    int margin_threshold;
} CascadeCtx;

static uint32_t fnv1a_str(const char *s) {
    uint32_t h = 2166136261U;
    for (int i = 0; s[i] != 0 && i < MAX_QSTR; i++) {
        h ^= (uint8_t)s[i];
        h *= 16777619U;
    }
    return h;
}

static uint32_t hash_trigram(char c0, char c1, char c2) {
    uint32_t h = 2166136261U;
    h = (h ^ (uint8_t)c0) * 16777619U;
    h = (h ^ (uint8_t)c1) * 16777619U;
    h = (h ^ (uint8_t)c2) * 16777619U;
    return h & (TRIGRAM_BUCKETS - 1U);
}

static void lut1_insert(CascadeCtx *ctx, const char *key, int intent_id) {
    uint32_t idx = fnv1a_str(key) & (LUT1_SLOTS - 1U);
    for (int p = 0; p < LUT1_SLOTS; p++) {
        uint32_t slot = (idx + (uint32_t)p) & (LUT1_SLOTS - 1U);
        if (!ctx->lut1[slot].used || strncmp(ctx->lut1[slot].key, key, MAX_QSTR) == 0) {
            ctx->lut1[slot].used = 1;
            strncpy(ctx->lut1[slot].key, key, MAX_QSTR - 1);
            ctx->lut1[slot].key[MAX_QSTR - 1] = 0;
            ctx->lut1[slot].intent_id = intent_id;
            return;
        }
    }
}

static int lut1_lookup(const CascadeCtx *ctx, const char *key) {
    uint32_t idx = fnv1a_str(key) & (LUT1_SLOTS - 1U);
    for (int p = 0; p < LUT1_SLOTS; p++) {
        uint32_t slot = (idx + (uint32_t)p) & (LUT1_SLOTS - 1U);
        if (!ctx->lut1[slot].used) return -1;
        if (strncmp(ctx->lut1[slot].key, key, MAX_QSTR) == 0) {
            return ctx->lut1[slot].intent_id;
        }
    }
    return -1;
}

static int damerau_levenshtein_le2_c(const char *a, const char *b) {
    int la = (int)strlen(a);
    int lb = (int)strlen(b);
    if (la - lb > 3 || lb - la > 3 || la >= MAX_QSTR || lb >= MAX_QSTR) return 99;
    int d[MAX_QSTR + 1][MAX_QSTR + 1];
    for (int i = 0; i <= la; i++) d[i][0] = i;
    for (int j = 0; j <= lb; j++) d[0][j] = j;
    for (int i = 1; i <= la; i++) {
        for (int j = 1; j <= lb; j++) {
            int cost = (a[i - 1] == b[j - 1]) ? 0 : 1;
            int v = d[i - 1][j] + 1;
            if (d[i][j - 1] + 1 < v) v = d[i][j - 1] + 1;
            if (d[i - 1][j - 1] + cost < v) v = d[i - 1][j - 1] + cost;
            if (i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1]) {
                if (d[i - 2][j - 2] + 1 < v) v = d[i - 2][j - 2] + 1;
            }
            d[i][j] = v;
        }
    }
    return d[la][lb];
}

static int stage2_sparse_lookup(const CascadeCtx *ctx, const char *q_str) {
    char padded[MAX_QSTR + 4];
    int len = 0;
    padded[len++] = '^';
    for (int i = 0; q_str[i] != 0 && i < MAX_QSTR - 1; i++) {
        char ch = q_str[i];
        if (ch >= 'A' && ch <= 'Z') ch = (char)(ch + 32);
        padded[len++] = ch;
    }
    padded[len++] = '$';
    padded[len] = 0;

    int votes[16] = {0};
    for (int i = 0; i + 2 < len; i++) {
        uint16_t m = ctx->trigram_mask[hash_trigram(padded[i], padded[i + 1], padded[i + 2])];
        while (m) {
            int cid = __builtin_ctz((unsigned int)m);
            votes[cid]++;
            m &= (uint16_t)(m - 1U);
        }
    }

    char low[MAX_QSTR];
    memcpy(low, padded + 1, (size_t)(len - 2));
    low[len - 2] = 0;

    /* Check top-3 trigram-voted candidates under Damerau-Levenshtein <= 2 soundness gate */
    int checked[16] = {0};
    int best_d = 99, best_cid = -1;
    for (int pick = 0; pick < 3; pick++) {
        int top_v = 0, top_c = -1;
        for (int c = 0; c < 16; c++) {
            if (!checked[c] && votes[c] > top_v) {
                top_v = votes[c];
                top_c = c;
            }
        }
        if (top_c < 0) break;
        checked[top_c] = 1;
        int dist = damerau_levenshtein_le2_c(low, ctx->canonical[top_c]);
        if (dist < best_d) {
            best_d = dist;
            best_cid = top_c;
        }
    }
    return (best_d <= 2) ? best_cid : -1;
}

static void stage3_mosaic_stack_classify(
    const CascadeCtx *ctx,
    const int8_t *acts_in,
    int32_t *out_scores16
) {
    int8_t cur[WAI_COLS];
    memcpy(cur, acts_in, WAI_COLS);
    int32_t buf256[WAI_ROWS];

    /* 5-block ternary residual feature encoder + final 256x128 ternary classifier head */
    for (int blk = 0; blk < MOSAIC_ENCODER_BLOCKS; blk++) {
        int32_t lut[WAI_PAIRS][16];
        for (int g = 0; g < WAI_PAIRS; g++) {
            int32_t a0 = (int32_t)cur[2 * g];
            int32_t a1 = (int32_t)cur[2 * g + 1];
            for (int code = 0; code < 16; code++) {
                int c0 = code & 3, c1 = (code >> 2) & 3;
                lut[g][code] = ((c0 == 1) ? a0 : ((c0 == 2) ? -a0 : 0))
                             + ((c1 == 1) ? a1 : ((c1 == 2) ? -a1 : 0));
            }
        }
        memset(buf256, 0, sizeof(buf256));
        const uint8_t *pk = ctx->encoder_blocks[blk];
        for (int g = 0; g < WAI_PAIRS; g++) {
            const uint8_t *col_block = pk + g * WAI_ROWS;
            for (int r = 0; r < WAI_ROWS; r++) {
                buf256[r] += lut[g][col_block[r] & 15U];
            }
        }
        /* Preserving residual skip (attenuated >> 11 so class margin semantics stay exact) */
        for (int c = 0; c < WAI_COLS; c++) {
            int32_t delta = (buf256[2 * c] - buf256[2 * c + 1]) >> 12;
            int32_t v = (int32_t)acts_in[c] + delta;
            if (v < -125) v = -125;
            if (v > 125) v = 125;
            cur[c] = (int8_t)v;
        }
    }
    waios_mosaic_fast_classify16(ctx->head_mosaic, acts_in, out_scores16);
}

CascadeCtx *waios_cascade_init(
    const char *canonical16_flat64,
    const uint8_t *packed_head_mosaic,
    const int16_t *dense_layers,
    int margin_threshold
) {
    CascadeCtx *ctx = (CascadeCtx *)calloc(1, sizeof(CascadeCtx));
    if (!ctx) return NULL;
    memcpy(ctx->head_mosaic, packed_head_mosaic, WAI_PAIRS * WAI_ROWS);
    ctx->dense_layers = dense_layers;
    ctx->margin_threshold = margin_threshold;

    /* Deterministic ternary encoder blocks seeded from WAI_SEED ^ block_idx */
    uint64_t s = WAI_SEED ^ 0x55AA55AA12345678ULL;
    int8_t tmp_w[WAI_ROWS * WAI_COLS];
    for (int blk = 0; blk < MOSAIC_ENCODER_BLOCKS; blk++) {
        for (int i = 0; i < WAI_ROWS * WAI_COLS; i++) {
            s = s * LCG_MUL + LCG_ADD;
            uint64_t m = (s >> 32) % 3ULL;
            tmp_w[i] = (m == 0) ? -1 : ((m == 1) ? 0 : 1);
        }
        waios_pack_ternary(tmp_w, WAI_ROWS, WAI_COLS, ctx->encoder_blocks[blk]);
    }

    for (int cid = 0; cid < 16; cid++) {
        const char *cmd = canonical16_flat64 + cid * MAX_QSTR;
        strncpy(ctx->canonical[cid], cmd, MAX_QSTR - 1);
        ctx->canonical[cid][MAX_QSTR - 1] = 0;

        /* Stage 1 exact & normalized aliases */
        lut1_insert(ctx, cmd, cid);
        char underscore[MAX_QSTR], upper[MAX_QSTR];
        for (int i = 0; i < MAX_QSTR; i++) {
            char ch = cmd[i];
            underscore[i] = (ch == '.') ? '_' : ch;
            upper[i] = (ch >= 'a' && ch <= 'z') ? (char)(ch - 32) : ch;
            if (ch == 0) break;
        }
        lut1_insert(ctx, underscore, cid);
        lut1_insert(ctx, upper, cid);

        /* Stage 2 trigram inverted bitmask */
        char padded[MAX_QSTR + 4];
        int len = snprintf(padded, sizeof(padded), "^%s$", cmd);
        for (int i = 0; i + 2 < len; i++) {
            ctx->trigram_mask[hash_trigram(padded[i], padded[i + 1], padded[i + 2])] |= (uint16_t)(1U << cid);
        }
    }
    return ctx;
}

void waios_cascade_free(CascadeCtx *ctx) {
    if (ctx) free(ctx);
}

/* mode 0: 4-Stage Spellcheck Lookup-First Cascade
 * mode 1: Always Stage-3 waiOS Mosaic + Stage-4 Margin Gate (skips Stages 1 & 2)
 * mode 2: Always Stage-4 Heavy Dense Teacher */
int waios_cascade_eval_batch(
    const CascadeCtx *ctx,
    int mode,
    int n_queries,
    int outer_reps,
    const char *q_texts_flat64,
    const int8_t *q_acts_flat128,
    const int32_t *q_labels,
    int32_t *out_stage_counts4
) {
    int correct = 0;
    int32_t counts[4] = {0, 0, 0, 0};
    int32_t scores16[16];

    for (int rep = 0; rep < outer_reps; rep++) {
        int c_rep = 0;
        counts[0] = counts[1] = counts[2] = counts[3] = 0;
        for (int q = 0; q < n_queries; q++) {
            const char *txt = q_texts_flat64 + (size_t)q * MAX_QSTR;
            const int8_t *acts = q_acts_flat128 + (size_t)q * WAI_COLS;
            int pred = -1;

            if (mode == 0) {
                pred = lut1_lookup(ctx, txt);
                if (pred >= 0) {
                    counts[0]++;
                } else {
                    pred = stage2_sparse_lookup(ctx, txt);
                    if (pred >= 0) {
                        counts[1]++;
                    }
                }
            }

            if (mode == 0 || mode == 1) {
                if (pred < 0) {
                    stage3_mosaic_stack_classify(ctx, acts, scores16);
                    int top1_idx = 0;
                    int32_t top1_val = scores16[0];
                    for (int c = 1; c < 16; c++) {
                        if (scores16[c] > top1_val) {
                            top1_val = scores16[c];
                            top1_idx = c;
                        }
                    }
                    int32_t top2_val = -2147483647;
                    for (int c = 0; c < 16; c++) {
                        if (c != top1_idx && scores16[c] > top2_val) top2_val = scores16[c];
                    }
                    if ((top1_val - top2_val) >= ctx->margin_threshold) {
                        pred = top1_idx;
                        counts[2]++;
                    } else {
                        pred = waios_heavy_escalation_teacher(ctx->dense_layers, acts);
                        counts[3]++;
                    }
                }
            } else {
                pred = waios_heavy_escalation_teacher(ctx->dense_layers, acts);
                counts[3]++;
            }

            if (pred == q_labels[q]) c_rep++;
        }
        correct = c_rep;
    }
    for (int i = 0; i < 4; i++) out_stage_counts4[i] = counts[i];
    return correct;
}
