/* SPDX-License-Identifier: Apache-2.0
 * Hardware-metered C micro-kernels for Kit 4 (`littlebit-joule`):
 *   - Fast Walsh-Hadamard internal rotation (O(D log D) in-place butterfly)
 *   - Deflated SVD + LittleBit binary latent sign factorization up to rank r <= 48
 *   - 6 decision regimes evaluated via ctypes in-process (zero fork/setup noise):
 *       0: deterministic_null_lut       (4 KiB compiled threshold/table control, 0 neural FLOPs)
 *       1: dense_int8_baseline          (8.00 bpw, 256 KiB dense INT8 matvec + ReLU + pool)
 *       2: subbit_naive_float_unpack    (rank-r unpacked to FP32 at runtime: impedance tax)
 *       3: littlebit_joule_packed_int   (rank-r packed uint64 XNOR+popcount + integer FWHT)
 *       4: ternary_2bpw                 (2.00 bpw T-MAC 2-col pair LUT ternary baseline)
 *       5: int4_4bpw                    (4.00 bpw packed symmetric nibble INT4 baseline)
 */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define D_IN 512
#define M_OUT 512
#define N_CLASSES 8
#define GROUP_SZ (M_OUT / N_CLASSES)
#define DEFAULT_RANK_R 22
#define MAX_RANK_R 48
#define WORDS_D (D_IN / 64)
#define PAIRS_D (D_IN / 2)
#define X_PLANES 5
#define LUT_BINS 4096

static uint64_t splitmix64(uint64_t *state) {
    uint64_t z = (*state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static double rand_norm_approx(uint64_t *st) {
    double s = 0.0;
    for (int i = 0; i < 12; i++) {
        s += (double)(splitmix64(st) & 0xFFFFFFFFULL) / 4294967296.0;
    }
    return s - 6.0;
}

void lb_fwht_f32(float *v, int n) {
    for (int len = 1; len < n; len <<= 1) {
        int step = len << 1;
        for (int i = 0; i < n; i += step) {
            for (int j = 0; j < len; j++) {
                float a = v[i + j];
                float b = v[i + j + len];
                v[i + j] = a + b;
                v[i + j + len] = a - b;
            }
        }
    }
}

void lb_fwht_i32(int32_t *v, int n) {
    for (int len = 1; len < n; len <<= 1) {
        int step = len << 1;
        for (int i = 0; i < n; i += step) {
            for (int j = 0; j < len; j++) {
                int32_t a = v[i + j];
                int32_t b = v[i + j + len];
                v[i + j] = a + b;
                v[i + j + len] = a - b;
            }
        }
    }
}

typedef struct {
    int8_t w_int8[M_OUT * D_IN];
    float w_scale_int8;
    uint8_t w_ternary_tmac[PAIRS_D * M_OUT];
    uint8_t w_int4_packed[(M_OUT * D_IN) / 2];

    uint64_t u_sign_mask[M_OUT];
    uint64_t v_sign_words[MAX_RANK_R][WORDS_D];
    int16_t row_scale_q12[M_OUT];
    int16_t col_pre_scale_q12[D_IN];
    uint64_t rad_sign_words[WORDS_D];
    int16_t sigma_q10[MAX_RANK_R];
    float row_scale_f32[M_OUT];
    float sigma_f32[MAX_RANK_R];

    uint8_t dnull_lut[LUT_BINS];
    int16_t dnull_band_weights[N_CLASSES][4];

    double raw_kurtosis_max_over_rms;
    double rotated_kurtosis_max_over_rms;

    int n_dev;
    int n_test;
    int8_t *x_dev;
    uint8_t *y_dev;
    int8_t *x_test;
    uint8_t *y_test;
} LbContext;

static inline int get_rad_sign(const uint64_t *rad_words, int j) {
    return ((rad_words[j >> 6] >> (j & 63)) & 1ULL) ? 1 : -1;
}

static inline uint8_t tern_code(int v) {
    return (v > 0) ? 1U : ((v < 0) ? 2U : 0U);
}

static uint32_t compute_dnull_feature_bin(const int8_t *x) {
    uint32_t idx = 0;
    for (int q = 0; q < 4; q++) {
        int32_t s = 0;
        const int8_t *seg = x + q * 128;
        for (int i = 0; i < 128; i++) s += seg[i];
        int bin = (s + 2400) / 600;
        if (bin < 0) bin = 0;
        if (bin > 7) bin = 7;
        idx = (idx << 3) | (uint32_t)bin;
    }
    return idx;
}

LbContext *lb_init(int n_dev, int n_test) {
    LbContext *mb = (LbContext *)calloc(1, sizeof(LbContext));
    if (!mb) return NULL;
    mb->n_dev = n_dev;
    mb->n_test = n_test;
    mb->x_dev = (int8_t *)malloc((size_t)n_dev * D_IN);
    mb->y_dev = (uint8_t *)malloc((size_t)n_dev);
    mb->x_test = (int8_t *)malloc((size_t)n_test * D_IN);
    mb->y_test = (uint8_t *)malloc((size_t)n_test);

    uint64_t st = 0x2026112500C0FFEEULL;
    for (int w = 0; w < WORDS_D; w++) {
        mb->rad_sign_words[w] = splitmix64(&st);
    }

    const int gt_rank = 18;
    float basis[18][D_IN];
    for (int k = 0; k < gt_rank; k++) {
        double nrm = 0.0;
        for (int j = 0; j < D_IN; j++) {
            double val = 0.35 * rand_norm_approx(&st);
            if (k < 4 && (j / 128) == k) val += 1.15;
            if ((j % 32) == (k % 32)) val += 2.8 * ((k & 1) ? 1.0 : -1.0);
            basis[k][j] = (float)val;
            nrm += val * val;
        }
        float inv = (float)(1.0 / sqrt(nrm));
        for (int j = 0; j < D_IN; j++) basis[k][j] *= inv;
    }

    float class_loadings[N_CLASSES][18];
    for (int c = 0; c < N_CLASSES; c++) {
        for (int k = 0; k < gt_rank; k++) {
            double v = 0.0;
            if (k < 4) {
                v = ((c % 4) == k) ? 2.4 : -0.65;
                if (c >= 4 && ((c + 1) % 4) == k) v += 1.35;
            } else {
                v = (((c * 7 + k * 3) % 5) == 0) ? 1.85 : -0.42;
                if (((c + k) % 3) == 0) v += 0.75;
            }
            class_loadings[c][k] = (float)v;
        }
    }

    float *w_fp32 = (float *)calloc(M_OUT * D_IN, sizeof(float));
    for (int c = 0; c < N_CLASSES; c++) {
        for (int g = 0; g < GROUP_SZ; g++) {
            int row = c * GROUP_SZ + g;
            uint64_t rst = 0xABCDEF00ULL + (uint64_t)row * 131ULL;
            for (int k = 0; k < gt_rank; k++) {
                float jitter = 1.0f + 0.18f * (float)rand_norm_approx(&rst);
                float coeff = class_loadings[c][k] * jitter;
                for (int j = 0; j < D_IN; j++) {
                    w_fp32[row * D_IN + j] += coeff * basis[k][j];
                }
            }
        }
    }

    double raw_max = 0.0, raw_sq = 0.0;
    for (int idx = 0; idx < M_OUT * D_IN; idx++) {
        double a = fabs((double)w_fp32[idx]);
        if (a > raw_max) raw_max = a;
        raw_sq += a * a;
    }
    double raw_rms = sqrt(raw_sq / (double)(M_OUT * D_IN));
    mb->raw_kurtosis_max_over_rms = raw_max / raw_rms;

    mb->w_scale_int8 = (float)(raw_max / 127.0);
    for (int idx = 0; idx < M_OUT * D_IN; idx++) {
        int q = (int)lrintf(w_fp32[idx] / mb->w_scale_int8);
        if (q < -127) q = -127;
        if (q > 127) q = 127;
        mb->w_int8[idx] = (int8_t)q;
    }

    /* Pack 2-bpw ternary (T-MAC 2-col pair layout) & 4-bpw symmetric INT4 */
    float tern_thr = (float)(0.68 * raw_rms);
    for (int g = 0; g < PAIRS_D; g++) {
        for (int r = 0; r < M_OUT; r++) {
            float f0 = w_fp32[r * D_IN + 2 * g];
            float f1 = w_fp32[r * D_IN + 2 * g + 1];
            int t0 = (f0 > tern_thr) ? 1 : ((f0 < -tern_thr) ? -1 : 0);
            int t1 = (f1 > tern_thr) ? 1 : ((f1 < -tern_thr) ? -1 : 0);
            mb->w_ternary_tmac[g * M_OUT + r] = (uint8_t)(tern_code(t0) | (tern_code(t1) << 2));
        }
    }
    float int4_scale = (float)(raw_max / 7.0);
    for (int idx = 0; idx < (M_OUT * D_IN) / 2; idx++) {
        int q0 = (int)lrintf(w_fp32[2 * idx] / int4_scale);
        int q1 = (int)lrintf(w_fp32[2 * idx + 1] / int4_scale);
        if (q0 < -7) q0 = -7; else if (q0 > 7) q0 = 7;
        if (q1 < -7) q1 = -7; else if (q1 > 7) q1 = 7;
        mb->w_int4_packed[idx] = (uint8_t)((uint8_t)(q0 + 8) | ((uint8_t)(q1 + 8) << 4));
    }

    /* Dataset generation BEFORE SVD loop so dataset RNG state `st` is 100% invariant to MAX_RANK_R! */
    for (int split = 0; split < 2; split++) {
        int n = (split == 0) ? n_dev : n_test;
        int8_t *xs = (split == 0) ? mb->x_dev : mb->x_test;
        uint8_t *ys = (split == 0) ? mb->y_dev : mb->y_test;
        for (int idx = 0; idx < n; idx++) {
            int cls = (int)(splitmix64(&st) % N_CLASSES);
            ys[idx] = (uint8_t)cls;
            float xf[D_IN];
            memset(xf, 0, sizeof(xf));
            for (int k = 0; k < gt_rank; k++) {
                float amp = class_loadings[cls][k] * 14.0f + 4.2f * (float)rand_norm_approx(&st);
                for (int j = 0; j < D_IN; j++) xf[j] += amp * basis[k][j];
            }
            for (int j = 0; j < D_IN; j++) {
                float v = xf[j] * 18.0f + 9.5f * (float)rand_norm_approx(&st);
                int qi = (int)lrintf(v);
                if (qi < -127) qi = -127;
                if (qi > 127) qi = 127;
                xs[idx * D_IN + j] = (int8_t)qi;
            }
        }
    }

    float *w_rot = (float *)malloc(M_OUT * D_IN * sizeof(float));
    const float inv_sqrt_d = 1.0f / sqrtf((float)D_IN);
    double rot_max = 0.0, rot_sq = 0.0;
    for (int i = 0; i < M_OUT; i++) {
        float tmp[D_IN];
        for (int j = 0; j < D_IN; j++) {
            tmp[j] = w_fp32[i * D_IN + j] * (float)get_rad_sign(mb->rad_sign_words, j);
            mb->col_pre_scale_q12[j] = 4096;
        }
        lb_fwht_f32(tmp, D_IN);
        double row_sq = 0.0;
        for (int j = 0; j < D_IN; j++) {
            tmp[j] *= inv_sqrt_d;
            double a = fabs((double)tmp[j]);
            if (a > rot_max) rot_max = a;
            rot_sq += a * a;
            row_sq += (double)tmp[j] * (double)tmp[j];
        }
        float rscale = (float)sqrt(row_sq / (double)D_IN);
        if (rscale < 1e-6f) rscale = 1e-6f;
        mb->row_scale_f32[i] = rscale;
        int rq = (int)lrintf(rscale * 4096.0f);
        if (rq > 32767) rq = 32767;
        mb->row_scale_q12[i] = (int16_t)rq;
        for (int j = 0; j < D_IN; j++) {
            w_rot[i * D_IN + j] = tmp[j] / rscale;
        }
    }
    mb->rotated_kurtosis_max_over_rms = rot_max / sqrt(rot_sq / (double)(M_OUT * D_IN));

    float *resid = (float *)malloc(M_OUT * D_IN * sizeof(float));
    memcpy(resid, w_rot, M_OUT * D_IN * sizeof(float));

    for (int k = 0; k < MAX_RANK_R; k++) {
        float v[D_IN], u[M_OUT];
        uint64_t pst = 0x12345678ULL + (uint64_t)k * 997ULL;
        for (int j = 0; j < D_IN; j++) v[j] = (float)rand_norm_approx(&pst);
        for (int it = 0; it < 35; it++) {
            double un = 0.0;
            for (int i = 0; i < M_OUT; i++) {
                const float *rrow = resid + i * D_IN;
                float s = 0.0f;
                for (int j = 0; j < D_IN; j++) s += rrow[j] * v[j];
                u[i] = s;
                un += (double)s * (double)s;
            }
            float inv_u = (float)(1.0 / sqrt(un + 1e-12));
            for (int i = 0; i < M_OUT; i++) u[i] *= inv_u;

            memset(v, 0, sizeof(v));
            for (int i = 0; i < M_OUT; i++) {
                float ui = u[i];
                const float *rrow = resid + i * D_IN;
                for (int j = 0; j < D_IN; j++) v[j] += ui * rrow[j];
            }
            double vn = 0.0;
            for (int j = 0; j < D_IN; j++) vn += (double)v[j] * (double)v[j];
            float inv_v = (float)(1.0 / sqrt(vn + 1e-12));
            for (int j = 0; j < D_IN; j++) v[j] *= inv_v;
        }

        int8_t us[M_OUT], vs[D_IN];
        for (int i = 0; i < M_OUT; i++) us[i] = (u[i] >= 0.0f) ? 1 : -1;
        for (int j = 0; j < D_IN; j++) vs[j] = (v[j] >= 0.0f) ? 1 : -1;
        for (int sw = 0; sw < 3; sw++) {
            for (int i = 0; i < M_OUT; i++) {
                const float *rrow = resid + i * D_IN;
                float s = 0.0f;
                for (int j = 0; j < D_IN; j++) s += rrow[j] * (float)vs[j];
                us[i] = (s >= 0.0f) ? 1 : -1;
            }
            for (int j = 0; j < D_IN; j++) {
                float s = 0.0f;
                for (int i = 0; i < M_OUT; i++) s += resid[i * D_IN + j] * (float)us[i];
                vs[j] = (s >= 0.0f) ? 1 : -1;
            }
        }
        double num = 0.0;
        for (int i = 0; i < M_OUT; i++) {
            const float *rrow = resid + i * D_IN;
            double rs = 0.0;
            for (int j = 0; j < D_IN; j++) rs += (double)rrow[j] * (double)vs[j];
            num += (double)us[i] * rs;
        }
        float gamma = (float)(num / (double)(M_OUT * D_IN));
        if (gamma < 0.0f) {
            gamma = -gamma;
            for (int i = 0; i < M_OUT; i++) us[i] = -us[i];
        }
        mb->sigma_f32[k] = gamma;
        int gq = (int)lrintf(gamma * 4096.0f);
        if (gq > 32767) gq = 32767;
        mb->sigma_q10[k] = (int16_t)gq;

        for (int i = 0; i < M_OUT; i++) {
            if (us[i] > 0) mb->u_sign_mask[i] |= (1ULL << k);
        }
        for (int w = 0; w < WORDS_D; w++) {
            uint64_t word = 0ULL;
            for (int b = 0; b < 64; b++) {
                if (vs[w * 64 + b] > 0) word |= (1ULL << b);
            }
            mb->v_sign_words[k][w] = word;
        }
        for (int i = 0; i < M_OUT; i++) {
            float g_u = gamma * (float)us[i];
            float *rrow = resid + i * D_IN;
            for (int j = 0; j < D_IN; j++) rrow[j] -= g_u * (float)vs[j];
        }
    }

    uint16_t counts[LUT_BINS][N_CLASSES];
    double band_sum[N_CLASSES][4];
    int cls_cnt[N_CLASSES] = {0};
    memset(counts, 0, sizeof(counts));
    memset(band_sum, 0, sizeof(band_sum));

    for (int idx = 0; idx < n_dev; idx++) {
        const int8_t *x = mb->x_dev + idx * D_IN;
        uint8_t c = mb->y_dev[idx];
        uint32_t bin = compute_dnull_feature_bin(x);
        counts[bin][c]++;
        cls_cnt[c]++;
        for (int q = 0; q < 4; q++) {
            int32_t s = 0;
            for (int i = 0; i < 128; i++) s += x[q * 128 + i];
            band_sum[c][q] += (double)s;
        }
    }
    for (int c = 0; c < N_CLASSES; c++) {
        for (int q = 0; q < 4; q++) {
            double mean = band_sum[c][q] / (double)(cls_cnt[c] > 0 ? cls_cnt[c] : 1);
            mb->dnull_band_weights[c][q] = (int16_t)lrint(mean / 8.0);
        }
    }
    for (uint32_t bin = 0; bin < LUT_BINS; bin++) {
        uint16_t best_n = 0;
        int best_c = -1;
        for (int c = 0; c < N_CLASSES; c++) {
            if (counts[bin][c] > best_n) {
                best_n = counts[bin][c];
                best_c = c;
            }
        }
        if (best_c >= 0) {
            mb->dnull_lut[bin] = (uint8_t)best_c;
        } else {
            int q_centers[4];
            for (int q = 0; q < 4; q++) {
                int b3 = (int)((bin >> (3 * (3 - q))) & 7U);
                q_centers[q] = b3 * 600 - 2100;
            }
            int64_t best_sc = -((int64_t)1 << 60);
            int fb_c = 0;
            for (int c = 0; c < N_CLASSES; c++) {
                int64_t sc = 0;
                for (int q = 0; q < 4; q++) sc += (int64_t)mb->dnull_band_weights[c][q] * (int64_t)q_centers[q];
                if (sc > best_sc) { best_sc = sc; fb_c = c; }
            }
            mb->dnull_lut[bin] = (uint8_t)fb_c;
        }
    }

    free(resid);
    free(w_rot);
    free(w_fp32);
    return mb;
}

void lb_free(LbContext *mb) {
    if (!mb) return;
    free(mb->x_dev);
    free(mb->y_dev);
    free(mb->x_test);
    free(mb->y_test);
    free(mb);
}

void lb_get_kurtosis(const LbContext *mb, double *raw_out, double *rot_out) {
    *raw_out = mb->raw_kurtosis_max_over_rms;
    *rot_out = mb->rotated_kurtosis_max_over_rms;
}

static uint8_t predict_dnull_lut(const LbContext *mb, const int8_t *x) {
    return mb->dnull_lut[compute_dnull_feature_bin(x)];
}

static uint8_t predict_dense_int8(const LbContext *mb, const int8_t *x) {
    int64_t best_score = -((int64_t)1 << 60);
    uint8_t best_c = 0;
    for (int c = 0; c < N_CLASSES; c++) {
        int64_t c_sum = 0;
        for (int g = 0; g < GROUP_SZ; g++) {
            int row = c * GROUP_SZ + g;
            const int8_t *wrow = mb->w_int8 + row * D_IN;
            int32_t acc = 0;
            for (int j = 0; j < D_IN; j++) acc += (int32_t)wrow[j] * (int32_t)x[j];
            if (acc > 0) c_sum += acc;
        }
        if (c_sum > best_score) {
            best_score = c_sum;
            best_c = (uint8_t)c;
        }
    }
    return best_c;
}

static uint8_t predict_ternary_2bpw(const LbContext *mb, const int8_t *x) {
    int32_t lut[PAIRS_D][16];
    for (int g = 0; g < PAIRS_D; g++) {
        int32_t a0 = (int32_t)x[2 * g];
        int32_t a1 = (int32_t)x[2 * g + 1];
        for (int code = 0; code < 16; code++) {
            int c0 = code & 3, c1 = (code >> 2) & 3;
            lut[g][code] = ((c0 == 1) ? a0 : ((c0 == 2) ? -a0 : 0))
                         + ((c1 == 1) ? a1 : ((c1 == 2) ? -a1 : 0));
        }
    }
    int32_t row_out[M_OUT];
    memset(row_out, 0, sizeof(row_out));
    for (int g = 0; g < PAIRS_D; g++) {
        const uint8_t *col_blk = mb->w_ternary_tmac + g * M_OUT;
        for (int r = 0; r < M_OUT; r++) {
            row_out[r] += lut[g][col_blk[r] & 15U];
        }
    }
    int64_t best_score = -((int64_t)1 << 60);
    uint8_t best_c = 0;
    for (int c = 0; c < N_CLASSES; c++) {
        int64_t c_sum = 0;
        for (int g = 0; g < GROUP_SZ; g++) {
            int32_t v = row_out[c * GROUP_SZ + g];
            if (v > 0) c_sum += v;
        }
        if (c_sum > best_score) { best_score = c_sum; best_c = (uint8_t)c; }
    }
    return best_c;
}

static uint8_t predict_int4_4bpw(const LbContext *mb, const int8_t *x) {
    int64_t best_score = -((int64_t)1 << 60);
    uint8_t best_c = 0;
    for (int c = 0; c < N_CLASSES; c++) {
        int64_t c_sum = 0;
        for (int g = 0; g < GROUP_SZ; g++) {
            int row = c * GROUP_SZ + g;
            const uint8_t *w4 = mb->w_int4_packed + row * (D_IN / 2);
            int32_t acc = 0;
            for (int j = 0; j < D_IN / 2; j++) {
                uint8_t pk = w4[j];
                int32_t q0 = (int32_t)(pk & 15U) - 8;
                int32_t q1 = (int32_t)(pk >> 4) - 8;
                acc += q0 * (int32_t)x[2 * j] + q1 * (int32_t)x[2 * j + 1];
            }
            if (acc > 0) c_sum += acc;
        }
        if (c_sum > best_score) { best_score = c_sum; best_c = (uint8_t)c; }
    }
    return best_c;
}

static uint8_t predict_subbit_naive_float_rank(const LbContext *mb, const int8_t *x, int rank_r) {
    const float inv_sqrt_d = 1.0f / sqrtf((float)D_IN);
    float v_unpacked[MAX_RANK_R][D_IN];
    for (int k = 0; k < rank_r; k++) {
        for (int w = 0; w < WORDS_D; w++) {
            uint64_t vw = mb->v_sign_words[k][w];
            for (int b = 0; b < 64; b++) {
                v_unpacked[k][w * 64 + b] = ((vw >> b) & 1ULL) ? mb->sigma_f32[k] : -mb->sigma_f32[k];
            }
        }
        lb_fwht_f32(v_unpacked[k], D_IN);
        for (int j = 0; j < D_IN; j++) {
            v_unpacked[k][j] *= inv_sqrt_d * (float)get_rad_sign(mb->rad_sign_words, j);
        }
    }

    float best_score = -1e30f;
    uint8_t best_c = 0;
    for (int c = 0; c < N_CLASSES; c++) {
        float c_sum = 0.0f;
        for (int g = 0; g < GROUP_SZ; g++) {
            int row = c * GROUP_SZ + g;
            uint64_t um = mb->u_sign_mask[row];
            float w_row_fp32[D_IN];
            memset(w_row_fp32, 0, sizeof(w_row_fp32));
            for (int k = 0; k < rank_r; k++) {
                float sgn = ((um >> k) & 1ULL) ? 1.0f : -1.0f;
                for (int j = 0; j < D_IN; j++) {
                    w_row_fp32[j] += sgn * v_unpacked[k][j];
                }
            }
            float dot = 0.0f;
            float rscale = mb->row_scale_f32[row];
            for (int j = 0; j < D_IN; j++) {
                dot += (w_row_fp32[j] * rscale) * (float)x[j];
            }
            if (dot > 0.0f) c_sum += dot;
        }
        if (c_sum > best_score) {
            best_score = c_sum;
            best_c = (uint8_t)c;
        }
    }
    return best_c;
}

static uint8_t predict_littlebit_packed_int_rank(const LbContext *mb, const int8_t *x, int rank_r) {
    int32_t xr[D_IN];
    for (int w = 0; w < WORDS_D; w++) {
        uint64_t rw = mb->rad_sign_words[w];
        int32_t *dst = xr + w * 64;
        const int8_t *src_x = x + w * 64;
        for (int b = 0; b < 64; b++) {
            int32_t sgn = (int32_t)(((rw >> b) & 1ULL) << 1) - 1;
            dst[b] = (int32_t)src_x[b] * sgn;
        }
    }
    lb_fwht_i32(xr, D_IN);

    int32_t max_abs = 1;
    for (int j = 0; j < D_IN; j++) {
        int32_t a = xr[j] >= 0 ? xr[j] : -xr[j];
        if (a > max_abs) max_abs = a;
    }
    int32_t recip_q16 = (15 << 16) / max_abs;
    uint64_t x_planes[X_PLANES][WORDS_D];
    for (int w = 0; w < WORDS_D; w++) {
        uint64_t p0 = 0ULL, p1 = 0ULL, p2 = 0ULL, p3 = 0ULL, p4 = 0ULL;
        const int32_t *seg = xr + w * 64;
        for (int b = 0; b < 64; b++) {
            int u = ((seg[b] * recip_q16) >> 16) + 16;
            if (u < 0) u = 0;
            if (u > 31) u = 31;
            uint64_t bit = 1ULL << b;
            if (u & 1)  p0 |= bit;
            if (u & 2)  p1 |= bit;
            if (u & 4)  p2 |= bit;
            if (u & 8)  p3 |= bit;
            if (u & 16) p4 |= bit;
        }
        x_planes[0][w] = p0;
        x_planes[1][w] = p1;
        x_planes[2][w] = p2;
        x_planes[3][w] = p3;
        x_planes[4][w] = p4;
    }

    int32_t z_pad[MAX_RANK_R + 4];
    memset(z_pad, 0, sizeof(z_pad));
    for (int k = 0; k < rank_r; k++) {
        const uint64_t *vw = mb->v_sign_words[k];
        int32_t dot_bipolar = 0;
        for (int p = 0; p < X_PLANES; p++) {
            const uint64_t *xp = x_planes[p];
            int pop = __builtin_popcountll(~(vw[0] ^ xp[0]))
                    + __builtin_popcountll(~(vw[1] ^ xp[1]))
                    + __builtin_popcountll(~(vw[2] ^ xp[2]))
                    + __builtin_popcountll(~(vw[3] ^ xp[3]))
                    + __builtin_popcountll(~(vw[4] ^ xp[4]))
                    + __builtin_popcountll(~(vw[5] ^ xp[5]))
                    + __builtin_popcountll(~(vw[6] ^ xp[6]))
                    + __builtin_popcountll(~(vw[7] ^ xp[7]));
            dot_bipolar += ((2 * pop) - D_IN) << p;
        }
        z_pad[k] = (dot_bipolar * (int32_t)mb->sigma_q10[k]) >> 8;
    }

    int n_nibbles = (rank_r + 3) / 4;
    int32_t lut[12][16];
    for (int g = 0; g < n_nibbles; g++) {
        int32_t z0 = z_pad[4 * g + 0];
        int32_t z1 = z_pad[4 * g + 1];
        int32_t z2 = z_pad[4 * g + 2];
        int32_t z3 = z_pad[4 * g + 3];
        for (int m = 0; m < 16; m++) {
            lut[g][m] = ((m & 1) ? z0 : -z0)
                      + ((m & 2) ? z1 : -z1)
                      + ((m & 4) ? z2 : -z2)
                      + ((m & 8) ? z3 : -z3);
        }
    }

    int64_t best_score = -((int64_t)1 << 60);
    uint8_t best_c = 0;
    for (int c = 0; c < N_CLASSES; c++) {
        int64_t c_sum = 0;
        const uint64_t *um_ptr = mb->u_sign_mask + c * GROUP_SZ;
        const int16_t *rs_ptr = mb->row_scale_q12 + c * GROUP_SZ;
        for (int g = 0; g < GROUP_SZ; g++) {
            uint64_t um = um_ptr[g];
            int32_t h = 0;
            for (int nb = 0; nb < n_nibbles; nb++) {
                h += lut[nb][(um >> (4 * nb)) & 15ULL];
            }
            if (h > 0) {
                c_sum += ((int64_t)h * (int64_t)rs_ptr[g]) >> 8;
            }
        }
        if (c_sum > best_score) {
            best_score = c_sum;
            best_c = (uint8_t)c;
        }
    }
    return best_c;
}

uint64_t lb_eval_regime_rank(
    const LbContext *mb,
    int regime_id,
    int rank_r,
    int outer_reps,
    int *out_correct,
    double *out_elapsed_ns
) {
    if (rank_r < 1) rank_r = 1;
    if (rank_r > MAX_RANK_R) rank_r = MAX_RANK_R;
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    uint64_t fnv = 1469598103934665603ULL;
    int correct = 0;
    for (int rep = 0; rep < outer_reps; rep++) {
        int c_rep = 0;
        uint64_t h_rep = 1469598103934665603ULL;
        for (int i = 0; i < mb->n_test; i++) {
            const int8_t *x = mb->x_test + i * D_IN;
            uint8_t p = 0;
            if (regime_id == 0) p = predict_dnull_lut(mb, x);
            else if (regime_id == 1) p = predict_dense_int8(mb, x);
            else if (regime_id == 2) p = predict_subbit_naive_float_rank(mb, x, rank_r);
            else if (regime_id == 3) p = predict_littlebit_packed_int_rank(mb, x, rank_r);
            else if (regime_id == 4) p = predict_ternary_2bpw(mb, x);
            else p = predict_int4_4bpw(mb, x);
            if (p == mb->y_test[i]) c_rep++;
            h_rep ^= (uint64_t)p;
            h_rep *= 1099511628211ULL;
        }
        correct = c_rep;
        fnv = h_rep;
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    *out_correct = correct;
    *out_elapsed_ns = (double)(t1.tv_sec - t0.tv_sec) * 1e9 + (double)(t1.tv_nsec - t0.tv_nsec);
    return fnv;
}

uint64_t lb_eval_regime(
    const LbContext *mb,
    int regime_id,
    int outer_reps,
    int *out_correct,
    double *out_elapsed_ns
) {
    return lb_eval_regime_rank(mb, regime_id, DEFAULT_RANK_R, outer_reps, out_correct, out_elapsed_ns);
}

int32_t lb_bipolar_dot_xnor512(const uint64_t *a_words, const uint64_t *b_words) {
    int pop = 0;
    for (int w = 0; w < WORDS_D; w++) {
        pop += __builtin_popcountll(~(a_words[w] ^ b_words[w]));
    }
    return 2 * pop - D_IN;
}
