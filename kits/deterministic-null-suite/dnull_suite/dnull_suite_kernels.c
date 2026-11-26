/* SPDX-License-Identifier: Apache-2.0
 * Native C (-O2) kernels for `kits/deterministic-null-suite/` (Shot on Goal #1):
 *   Three deterministic held-out task strata (N = 1,500 total, 500 per stratum) + calibration split:
 *     - Stratum 0 (`bounded_api_dispatch`, 500 instances, 8 target routes):
 *         Structured enterprise gateway validation, quota/SLO guards, & endpoint dispatch.
 *     - Stratum 1 (`combinatorial_constraint_3sat`, 500 instances, binary SAT=1 / UNSAT=0):
 *         16-variable, 48-clause 3-SAT resource-allocation feasibility + witness verification.
 *     - Stratum 2 (`open_compositional_patch_triage`, 500 instances, 8 patch templates):
 *         32-feature AST/log defect triage with recurring crash hashes + oblique novel tail.
 *
 *   Evaluated across all 5 mandatory classical automation baselines + Shape-D union + Neural MLP:
 *     - Arm 0 (`arm1_lookup_table`):      <= 4 KiB (`512` x 8-byte slots = 4,096 B) content-addressed LUT
 *     - Arm 1 (`arm2_if_else_guards`):    Explicit deterministic `if/else` predicate guard chain
 *     - Arm 2 (`arm3_bounded_for_loop`):  Bounded `for`-loop scan (table / WalkSAT / centroid scan)
 *     - Arm 3 (`arm4_decision_tree`):     Depth-6 integer CART decision tree trained on calibration split
 *     - Arm 4 (`arm5_compiled_solver`):   Exact DPLL unit-propagation solver + compiled rule verifier
 *     - Arm 5 (`shape_d_classical_best`): Lookup-first -> exact solver/rule union (`0` neural FLOPs)
 *     - Arm 6 (`candidate_dense_mlp`):    2-hidden-layer (`128`-wide) ReLU neural comparator trained on cal split
 */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define N_PER_STRATUM 500
#define N_CAL_PER_STRATUM 450
#define LUT_SLOTS 512  /* 512 * sizeof(LutEntry8B) = 4,096 bytes exact! */
#define SAT_VARS 16
#define SAT_CLAUSES 48
#define TRIAGE_DIM 32
#define TRIAGE_CLASSES 8
#define MLP_H 128

static uint64_t splitmix64(uint64_t *state) {
    uint64_t z = (*state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static double rand_u01(uint64_t *st) {
    return (double)(splitmix64(st) >> 11) * (1.0 / 9007199254740992.0);
}

static double rand_norm(uint64_t *st) {
    double s = 0.0;
    for (int i = 0; i < 12; i++) s += rand_u01(st);
    return s - 6.0;
}

static uint32_t fnv1a_bytes(const void *data, size_t len) {
    const uint8_t *p = (const uint8_t *)data;
    uint32_t h = 2166136261U;
    for (size_t i = 0; i < len; i++) {
        h ^= p[i];
        h *= 16777619U;
    }
    return h ? h : 1U;
}

/* Exactly 8 bytes per slot -> 512 slots = 4,096 B (4.00 KiB) per stratum LUT */
typedef struct {
    uint32_t key_hash;
    uint8_t value;
    uint8_t used;
    uint16_t pad;
} LutEntry8B;

/* Stratum 0: Bounded API Dispatch */
typedef struct {
    int16_t f[8]; /* schema_v, auth_tier, quota_pct, payload_kb, region, idemp, slo_ms, retries */
    uint8_t label;
} ApiInstance;

/* Stratum 1: 16-var, 48-clause 3-SAT */
typedef struct {
    int8_t lits[SAT_CLAUSES][3]; /* signed 1..16 */
    int16_t feat8[8];            /* summary clause/polarity features for CART & MLP */
    uint8_t is_sat;
} SatInstance;

/* Stratum 2: 32-dim Compositional Patch Triage */
typedef struct {
    uint32_t crash_sig;          /* recurring crash signature when non-zero; unique on novel tail */
    int8_t x[TRIAGE_DIM];
    uint8_t stratum_kind;        /* 0: recurring, 1: single-guard, 2: compositional oblique */
    uint8_t label;
} TriageInstance;

/* Depth-6 binary CART tree (63 internal nodes + 64 leaves) */
typedef struct {
    int8_t feat_idx[63];
    int16_t thresh[63];
    uint8_t leaf_pred[64];
} CartTree6;

/* 2-layer ReLU MLP comparator (in_dim <= 32 -> 128 -> 128 -> out_classes <= 8) */
typedef struct {
    int in_dim;
    int n_classes;
    float w1[MLP_H][32];
    float b1[MLP_H];
    float w2[MLP_H][MLP_H];
    float b2[MLP_H];
    float w3[8][MLP_H];
    float b3[8];
} DenseMlp;

typedef struct {
    int n_per_stratum;
    ApiInstance cal_api[N_CAL_PER_STRATUM];
    ApiInstance test_api[N_PER_STRATUM];
    SatInstance cal_sat[N_CAL_PER_STRATUM];
    SatInstance test_sat[N_PER_STRATUM];
    TriageInstance cal_tri[N_CAL_PER_STRATUM];
    TriageInstance test_tri[N_PER_STRATUM];

    /* <= 4 KiB LUTs */
    LutEntry8B lut_api[LUT_SLOTS];
    LutEntry8B lut_sat[LUT_SLOTS];
    LutEntry8B lut_tri[LUT_SLOTS];
    uint8_t default_api;
    uint8_t default_sat;
    uint8_t default_tri;

    /* Depth-6 CART trees */
    CartTree6 tree_api;
    CartTree6 tree_sat;
    CartTree6 tree_tri;

    /* Centroids for Stratum 2 bounded for-loop scan */
    float tri_centroids[TRIAGE_CLASSES][TRIAGE_DIM];
    float tri_teacher_w[TRIAGE_CLASSES][TRIAGE_DIM];

    /* Trained MLPs */
    DenseMlp mlp_api;
    DenseMlp mlp_sat;
    DenseMlp mlp_tri;
} DnullSuiteCtx;

static void lut_insert(LutEntry8B *lut, uint32_t kh, uint8_t val) {
    uint32_t idx = kh & (LUT_SLOTS - 1U);
    for (int p = 0; p < 16; p++) {
        uint32_t s = (idx + (uint32_t)p) & (LUT_SLOTS - 1U);
        if (!lut[s].used || lut[s].key_hash == kh) {
            lut[s].key_hash = kh;
            lut[s].value = val;
            lut[s].used = 1;
            return;
        }
    }
}

static int lut_query(const LutEntry8B *lut, uint32_t kh) {
    uint32_t idx = kh & (LUT_SLOTS - 1U);
    for (int p = 0; p < 16; p++) {
        uint32_t s = (idx + (uint32_t)p) & (LUT_SLOTS - 1U);
        if (!lut[s].used) return -1;
        if (lut[s].key_hash == kh) return (int)lut[s].value;
    }
    return -1;
}

/* Ground-truth deterministic gateway specification (Stratum 0) */
static uint8_t eval_api_spec_if_else(const int16_t *f) {
    if (f[0] < 2 || f[0] > 4) return 0;                 /* REJECT_SCHEMA */
    if (f[1] <= 0) return 1;                            /* REJECT_AUTH */
    if (f[2] < 5 && f[1] < 3) return 2;                 /* THROTTLE_QUOTA */
    if (f[5] == 1 && f[7] > 0) return 6;                /* IDEMPOTENT_REPLAY */
    if (f[3] <= 16 && f[6] <= 40) return 3;             /* FAST_CACHE_EDGE */
    if (f[3] > 256 || f[6] >= 250) return 4;            /* BATCH_ASYNC_QUEUE */
    if (f[4] <= 2 && f[7] <= 1) return 5;               /* REGIONAL_PRIMARY */
    return 7;                                           /* FALLBACK_CANARY */
}

/* Priority rule table for Stratum 0 bounded for-loop */
static uint8_t eval_api_for_loop_table(const int16_t *f) {
    /* Evaluate 7 ordered rule rows in a deterministic table scan */
    const int conds[7] = {
        (f[0] < 2 || f[0] > 4),
        (f[1] <= 0),
        (f[2] < 5 && f[1] < 3),
        (f[5] == 1 && f[7] > 0),
        (f[3] <= 16 && f[6] <= 40),
        (f[3] > 256 || f[6] >= 250),
        (f[4] <= 2 && f[7] <= 1)
    };
    const uint8_t actions[7] = {0, 1, 2, 6, 3, 4, 5};
    for (int r = 0; r < 7; r++) {
        if (conds[r]) return actions[r];
    }
    return 7;
}

/* Exact DPLL + unit-propagation 3-SAT solver for Stratum 1 (16 vars, 48 clauses) */
static int sat_check_assign(const SatInstance *ins, uint16_t assign_mask) {
    for (int c = 0; c < SAT_CLAUSES; c++) {
        int sat_c = 0;
        for (int j = 0; j < 3; j++) {
            int lit = (int)ins->lits[c][j];
            int v = (lit > 0 ? lit : -lit) - 1;
            int bit = (assign_mask >> v) & 1U;
            if ((lit > 0 && bit == 1) || (lit < 0 && bit == 0)) {
                sat_c = 1;
                break;
            }
        }
        if (!sat_c) return 0;
    }
    return 1;
}

static int dpll_rec(const SatInstance *ins, int8_t *val, uint16_t *out_witness) {
    /* Unit propagation loop */
    int changed = 1;
    int8_t local_val[SAT_VARS];
    memcpy(local_val, val, SAT_VARS);

    while (changed) {
        changed = 0;
        int all_sat = 1;
        for (int c = 0; c < SAT_CLAUSES; c++) {
            int clause_sat = 0;
            int unassigned_cnt = 0;
            int last_lit = 0;
            for (int j = 0; j < 3; j++) {
                int lit = (int)ins->lits[c][j];
                int v = (lit > 0 ? lit : -lit) - 1;
                int8_t sv = local_val[v];
                if ((lit > 0 && sv == 1) || (lit < 0 && sv == 0)) {
                    clause_sat = 1;
                    break;
                }
                if (sv < 0) {
                    unassigned_cnt++;
                    last_lit = lit;
                }
            }
            if (clause_sat) continue;
            all_sat = 0;
            if (unassigned_cnt == 0) return 0; /* Conflict */
            if (unassigned_cnt == 1) {
                int v = (last_lit > 0 ? last_lit : -last_lit) - 1;
                local_val[v] = (last_lit > 0) ? 1 : 0;
                changed = 1;
            }
        }
        if (all_sat) {
            uint16_t mask = 0;
            for (int v = 0; v < SAT_VARS; v++) {
                if (local_val[v] == 1) mask |= (uint16_t)(1U << v);
            }
            *out_witness = mask;
            return 1;
        }
    }

    int pick_v = -1;
    for (int v = 0; v < SAT_VARS; v++) {
        if (local_val[v] < 0) { pick_v = v; break; }
    }
    if (pick_v < 0) {
        uint16_t mask = 0;
        for (int v = 0; v < SAT_VARS; v++) if (local_val[v] == 1) mask |= (uint16_t)(1U << v);
        if (sat_check_assign(ins, mask)) { *out_witness = mask; return 1; }
        return 0;
    }

    local_val[pick_v] = 1;
    if (dpll_rec(ins, local_val, out_witness)) return 1;
    local_val[pick_v] = 0;
    return dpll_rec(ins, local_val, out_witness);
}

static uint8_t solve_sat_exact_dpll(const SatInstance *ins) {
    int8_t init_val[SAT_VARS];
    memset(init_val, -1, sizeof(init_val));
    uint16_t witness = 0;
    int res = dpll_rec(ins, init_val, &witness);
    if (res) {
        /* Soundness check: verify witness satisfies all 48 clauses! */
        return sat_check_assign(ins, witness) ? 1 : 0;
    }
    return 0;
}

/* Bounded WalkSAT-style greedy for-loop (64 flips max, verified on every step) */
static uint8_t solve_sat_bounded_for_loop(const SatInstance *ins) {
    uint16_t mask = 0x5A5AU;
    for (int step = 0; step < 64; step++) {
        int unsat_c = -1;
        for (int c = 0; c < SAT_CLAUSES; c++) {
            int ok = 0;
            for (int j = 0; j < 3; j++) {
                int lit = (int)ins->lits[c][j];
                int v = (lit > 0 ? lit : -lit) - 1;
                int bit = (mask >> v) & 1U;
                if ((lit > 0 && bit == 1) || (lit < 0 && bit == 0)) { ok = 1; break; }
            }
            if (!ok) { unsat_c = c; break; }
        }
        if (unsat_c < 0) return 1; /* Verified witness found! */
        int pick_lit = (int)ins->lits[unsat_c][step % 3];
        int fv = (pick_lit > 0 ? pick_lit : -pick_lit) - 1;
        mask ^= (uint16_t)(1U << fv);
    }
    return sat_check_assign(ins, mask) ? 1 : 0;
}

static void compute_sat_summary_feats(SatInstance *ins) {
    int pos_cnt = 0, neg_cnt = 0;
    int var_pos[SAT_VARS] = {0}, var_neg[SAT_VARS] = {0};
    int pure_vars = 0, horn_clauses = 0, all_pos_c = 0, all_neg_c = 0;
    for (int c = 0; c < SAT_CLAUSES; c++) {
        int cp = 0;
        for (int j = 0; j < 3; j++) {
            int lit = (int)ins->lits[c][j];
            if (lit > 0) { pos_cnt++; var_pos[lit - 1]++; cp++; }
            else { neg_cnt++; var_neg[-lit - 1]++; }
        }
        if (cp <= 1) horn_clauses++;
        if (cp == 3) all_pos_c++;
        if (cp == 0) all_neg_c++;
    }
    int max_conflict = 0;
    for (int v = 0; v < SAT_VARS; v++) {
        if (var_pos[v] == 0 || var_neg[v] == 0) pure_vars++;
        int prod = var_pos[v] * var_neg[v];
        if (prod > max_conflict) max_conflict = prod;
    }
    ins->feat8[0] = (int16_t)(pos_cnt - neg_cnt);
    ins->feat8[1] = (int16_t)pure_vars;
    ins->feat8[2] = (int16_t)horn_clauses;
    ins->feat8[3] = (int16_t)all_pos_c;
    ins->feat8[4] = (int16_t)all_neg_c;
    ins->feat8[5] = (int16_t)max_conflict;
    ins->feat8[6] = (int16_t)(all_pos_c + all_neg_c);
    ins->feat8[7] = (int16_t)(var_pos[0] - var_neg[0]);
}

/* Train depth-6 CART decision tree via Gini impurity */
static void train_cart6(
    CartTree6 *tree,
    const int16_t *X,
    const uint8_t *Y,
    int n_samples,
    int n_feats,
    int n_classes
) {
    int *node_assign = (int *)calloc((size_t)n_samples, sizeof(int));
    for (int i = 0; i < n_samples; i++) node_assign[i] = 1; /* 1-based heap indexing 1..63, leaves 64..127 */

    for (int nid = 1; nid <= 63; nid++) {
        int cnt_total = 0;
        int cls_tot[8] = {0};
        for (int i = 0; i < n_samples; i++) {
            if (node_assign[i] == nid) {
                cnt_total++;
                cls_tot[Y[i]]++;
            }
        }
        int best_f = 0;
        int16_t best_thr = 0;
        double best_score = 1e30;

        if (cnt_total >= 4) {
            for (int f = 0; f < n_feats; f++) {
                /* Try 15 quantile/grid candidate thresholds */
                int16_t fmin = 32767, fmax = -32767;
                for (int i = 0; i < n_samples; i++) {
                    if (node_assign[i] == nid) {
                        int16_t v = X[i * n_feats + f];
                        if (v < fmin) fmin = v;
                        if (v > fmax) fmax = v;
                    }
                }
                if (fmin == fmax) continue;
                for (int q = 1; q <= 15; q++) {
                    int16_t thr = (int16_t)(fmin + ((int32_t)(fmax - fmin) * q) / 16);
                    int nL = 0, nR = 0;
                    int cL[8] = {0}, cR[8] = {0};
                    for (int i = 0; i < n_samples; i++) {
                        if (node_assign[i] == nid) {
                            if (X[i * n_feats + f] <= thr) { nL++; cL[Y[i]]++; }
                            else { nR++; cR[Y[i]]++; }
                        }
                    }
                    if (nL == 0 || nR == 0) continue;
                    double gL = 1.0, gR = 1.0;
                    for (int c = 0; c < n_classes; c++) {
                        double pL = (double)cL[c] / (double)nL;
                        double pR = (double)cR[c] / (double)nR;
                        gL -= pL * pL;
                        gR -= pR * pR;
                    }
                    double wg = ((double)nL * gL + (double)nR * gR) / (double)cnt_total;
                    if (wg < best_score) {
                        best_score = wg;
                        best_f = f;
                        best_thr = thr;
                    }
                }
            }
        }
        tree->feat_idx[nid - 1] = (int8_t)best_f;
        tree->thresh[nid - 1] = best_thr;
        for (int i = 0; i < n_samples; i++) {
            if (node_assign[i] == nid) {
                node_assign[i] = (X[i * n_feats + best_f] <= best_thr) ? (2 * nid) : (2 * nid + 1);
            }
        }
    }

    for (int leaf = 0; leaf < 64; leaf++) {
        int lid = 64 + leaf;
        int c_cnt[8] = {0};
        for (int i = 0; i < n_samples; i++) {
            if (node_assign[i] == lid) c_cnt[Y[i]]++;
        }
        int best_c = 0, best_n = -1;
        for (int c = 0; c < n_classes; c++) {
            if (c_cnt[c] > best_n) { best_n = c_cnt[c]; best_c = c; }
        }
        tree->leaf_pred[leaf] = (uint8_t)best_c;
    }
    free(node_assign);
}

static uint8_t eval_cart6(const CartTree6 *tree, const int16_t *x) {
    int nid = 1;
    for (int d = 0; d < 6; d++) {
        int f = (int)tree->feat_idx[nid - 1];
        nid = (x[f] <= tree->thresh[nid - 1]) ? (2 * nid) : (2 * nid + 1);
    }
    return tree->leaf_pred[nid - 64];
}

/* Train 2-hidden-layer ReLU MLP via mini-batch SGD on calibration split */
static void train_mlp(
    DenseMlp *mlp,
    const float *X,
    const uint8_t *Y,
    int n_samples,
    int in_dim,
    int n_classes,
    uint64_t seed
) {
    memset(mlp, 0, sizeof(*mlp));
    mlp->in_dim = in_dim;
    mlp->n_classes = n_classes;
    float s1 = sqrtf(2.0f / (float)in_dim);
    float s2 = sqrtf(2.0f / (float)MLP_H);
    for (int i = 0; i < MLP_H; i++) {
        for (int j = 0; j < in_dim; j++) mlp->w1[i][j] = s1 * (float)rand_norm(&seed) * 0.5f;
        for (int j = 0; j < MLP_H; j++) mlp->w2[i][j] = s2 * (float)rand_norm(&seed) * 0.5f;
    }
    for (int c = 0; c < n_classes; c++) {
        for (int j = 0; j < MLP_H; j++) mlp->w3[c][j] = s2 * (float)rand_norm(&seed) * 0.5f;
    }

    float lr = 0.015f;
    for (int epoch = 0; epoch < 45; epoch++) {
        for (int idx = 0; idx < n_samples; idx++) {
            const float *x = X + idx * in_dim;
            int target = (int)Y[idx];
            float h1[MLP_H], h2[MLP_H], logits[8], probs[8];
            for (int i = 0; i < MLP_H; i++) {
                float a = mlp->b1[i];
                for (int j = 0; j < in_dim; j++) a += mlp->w1[i][j] * x[j];
                h1[i] = a > 0.0f ? a : 0.0f;
            }
            for (int i = 0; i < MLP_H; i++) {
                float a = mlp->b2[i];
                for (int j = 0; j < MLP_H; j++) a += mlp->w2[i][j] * h1[j];
                h2[i] = a > 0.0f ? a : 0.0f;
            }
            float mlog = -1e30f;
            for (int c = 0; c < n_classes; c++) {
                float a = mlp->b3[c];
                for (int j = 0; j < MLP_H; j++) a += mlp->w3[c][j] * h2[j];
                logits[c] = a;
                if (a > mlog) mlog = a;
            }
            float s_exp = 0.0f;
            for (int c = 0; c < n_classes; c++) {
                probs[c] = expf(logits[c] - mlog);
                s_exp += probs[c];
            }
            float dlog[8];
            for (int c = 0; c < n_classes; c++) {
                dlog[c] = (probs[c] / s_exp) - (c == target ? 1.0f : 0.0f);
            }
            float dh2[MLP_H] = {0};
            for (int c = 0; c < n_classes; c++) {
                float g = dlog[c];
                mlp->b3[c] -= lr * g;
                for (int j = 0; j < MLP_H; j++) {
                    dh2[j] += mlp->w3[c][j] * g;
                    mlp->w3[c][j] -= lr * g * h2[j];
                }
            }
            float dh1[MLP_H] = {0};
            for (int i = 0; i < MLP_H; i++) {
                if (h2[i] <= 0.0f) continue;
                float g = dh2[i];
                mlp->b2[i] -= lr * g;
                for (int j = 0; j < MLP_H; j++) {
                    dh1[j] += mlp->w2[i][j] * g;
                    mlp->w2[i][j] -= lr * g * h1[j];
                }
            }
            for (int i = 0; i < MLP_H; i++) {
                if (h1[i] <= 0.0f) continue;
                float g = dh1[i];
                mlp->b1[i] -= lr * g;
                for (int j = 0; j < in_dim; j++) {
                    mlp->w1[i][j] -= lr * g * x[j];
                }
            }
        }
        lr *= 0.96f;
    }
}

static uint8_t eval_mlp(const DenseMlp *mlp, const float *x) {
    float h1[MLP_H], h2[MLP_H];
    for (int i = 0; i < MLP_H; i++) {
        float a = mlp->b1[i];
        for (int j = 0; j < mlp->in_dim; j++) a += mlp->w1[i][j] * x[j];
        h1[i] = a > 0.0f ? a : 0.0f;
    }
    for (int i = 0; i < MLP_H; i++) {
        float a = mlp->b2[i];
        for (int j = 0; j < MLP_H; j++) a += mlp->w2[i][j] * h1[j];
        h2[i] = a > 0.0f ? a : 0.0f;
    }
    float best = -1e30f;
    uint8_t best_c = 0;
    for (int c = 0; c < mlp->n_classes; c++) {
        float a = mlp->b3[c];
        for (int j = 0; j < MLP_H; j++) a += mlp->w3[c][j] * h2[j];
        if (a > best) { best = a; best_c = (uint8_t)c; }
    }
    return best_c;
}

DnullSuiteCtx *dnull_init(void) {
    DnullSuiteCtx *ctx = (DnullSuiteCtx *)calloc(1, sizeof(DnullSuiteCtx));
    if (!ctx) return NULL;
    ctx->n_per_stratum = N_PER_STRATUM;

    uint64_t st = 0x2026112601D00001ULL;

    /* 1. Generate Stratum 0 (`bounded_api_dispatch`): 78% recurring templates + 22% novel */
    int16_t api_templates[96][8];
    for (int t = 0; t < 96; t++) {
        api_templates[t][0] = (int16_t)(1 + (splitmix64(&st) % 5));
        api_templates[t][1] = (int16_t)(splitmix64(&st) % 4);
        api_templates[t][2] = (int16_t)(splitmix64(&st) % 100);
        api_templates[t][3] = (int16_t)(4 << (splitmix64(&st) % 8));
        api_templates[t][4] = (int16_t)(splitmix64(&st) % 5);
        api_templates[t][5] = (int16_t)(splitmix64(&st) & 1ULL);
        api_templates[t][6] = (int16_t)(15 + (splitmix64(&st) % 300));
        api_templates[t][7] = (int16_t)(splitmix64(&st) % 4);
    }

    for (int split = 0; split < 2; split++) {
        int n = (split == 0) ? N_CAL_PER_STRATUM : N_PER_STRATUM;
        ApiInstance *arr = (split == 0) ? ctx->cal_api : ctx->test_api;
        for (int i = 0; i < n; i++) {
            if ((i % 100) < 78) {
                int tid = (int)(splitmix64(&st) % 96ULL);
                memcpy(arr[i].f, api_templates[tid], sizeof(arr[i].f));
            } else {
                arr[i].f[0] = (int16_t)(1 + (splitmix64(&st) % 5));
                arr[i].f[1] = (int16_t)(splitmix64(&st) % 4);
                arr[i].f[2] = (int16_t)(splitmix64(&st) % 100);
                arr[i].f[3] = (int16_t)(1 + (splitmix64(&st) % 400));
                arr[i].f[4] = (int16_t)(splitmix64(&st) % 5);
                arr[i].f[5] = (int16_t)(splitmix64(&st) & 1ULL);
                arr[i].f[6] = (int16_t)(10 + (splitmix64(&st) % 320));
                arr[i].f[7] = (int16_t)(splitmix64(&st) % 4);
            }
            arr[i].label = eval_api_spec_if_else(arr[i].f);
        }
    }

    /* 2. Generate Stratum 1 (`combinatorial_constraint_3sat`): 28% recurring + 72% novel 16-var 48-clause 3-SAT */
    SatInstance sat_templates[48];
    memset(sat_templates, 0, sizeof(sat_templates));
    for (int t = 0; t < 48; t++) {
        for (int c = 0; c < SAT_CLAUSES; c++) {
            int v0 = (int)(splitmix64(&st) % SAT_VARS) + 1;
            int v1 = (int)((v0 + 1 + (splitmix64(&st) % (SAT_VARS - 1))) % SAT_VARS) + 1;
            int v2 = (int)((v1 + 1 + (splitmix64(&st) % (SAT_VARS - 2))) % SAT_VARS) + 1;
            sat_templates[t].lits[c][0] = (int8_t)((splitmix64(&st) & 1ULL) ? v0 : -v0);
            sat_templates[t].lits[c][1] = (int8_t)((splitmix64(&st) & 1ULL) ? v1 : -v1);
            sat_templates[t].lits[c][2] = (int8_t)((splitmix64(&st) & 1ULL) ? v2 : -v2);
        }
        compute_sat_summary_feats(&sat_templates[t]);
        sat_templates[t].is_sat = solve_sat_exact_dpll(&sat_templates[t]);
    }

    for (int split = 0; split < 2; split++) {
        int n = (split == 0) ? N_CAL_PER_STRATUM : N_PER_STRATUM;
        SatInstance *arr = (split == 0) ? ctx->cal_sat : ctx->test_sat;
        for (int i = 0; i < n; i++) {
            if ((i % 100) < 28) {
                arr[i] = sat_templates[splitmix64(&st) % 48ULL];
            } else {
                /* Generate balanced near-threshold 3-SAT (clauses = 48..68 via duplicate/tight clauses) */
                int want_sat = (i & 1);
                for (int attempt = 0; attempt < 30; attempt++) {
                    uint16_t planted = (uint16_t)(splitmix64(&st) & 0xFFFFULL);
                    for (int c = 0; c < SAT_CLAUSES; c++) {
                        int v0 = (int)(splitmix64(&st) % SAT_VARS) + 1;
                        int v1 = (int)((v0 + 1 + (splitmix64(&st) % 14)) % SAT_VARS) + 1;
                        int v2 = (int)((v1 + 1 + (splitmix64(&st) % 13)) % SAT_VARS) + 1;
                        int l0 = (splitmix64(&st) & 1ULL) ? v0 : -v0;
                        int l1 = (splitmix64(&st) & 1ULL) ? v1 : -v1;
                        int l2 = (splitmix64(&st) & 1ULL) ? v2 : -v2;
                        if (want_sat) {
                            /* Guarantee planted assignment satisfies every clause */
                            int ok0 = (l0 > 0) ? ((planted >> (v0 - 1)) & 1) : !((planted >> (v0 - 1)) & 1);
                            int ok1 = (l1 > 0) ? ((planted >> (v1 - 1)) & 1) : !((planted >> (v1 - 1)) & 1);
                            int ok2 = (l2 > 0) ? ((planted >> (v2 - 1)) & 1) : !((planted >> (v2 - 1)) & 1);
                            if (!ok0 && !ok1 && !ok2) l0 = -l0;
                        } else if (c >= 40) {
                            /* Inject tight 3-variable contradiction cluster on 8 clauses to force UNSAT */
                            int b = c - 40;
                            l0 = (b & 1) ? 1 : -1;
                            l1 = (b & 2) ? 2 : -2;
                            l2 = (b & 4) ? 3 : -3;
                        }
                        arr[i].lits[c][0] = (int8_t)l0;
                        arr[i].lits[c][1] = (int8_t)l1;
                        arr[i].lits[c][2] = (int8_t)l2;
                    }
                    compute_sat_summary_feats(&arr[i]);
                    arr[i].is_sat = solve_sat_exact_dpll(&arr[i]);
                    if ((int)arr[i].is_sat == want_sat) break;
                }
            }
        }
    }

    /* 3. Generate Stratum 2 (`open_compositional_patch_triage`):
     *    30% recurring crash hashes + 20% single-guard faults + 50% oblique nonlinear multi-feature compositional tail */
    float oblique_h[24][TRIAGE_DIM];
    float oblique_out[TRIAGE_CLASSES][24];
    for (int h = 0; h < 24; h++) {
        for (int d = 0; d < TRIAGE_DIM; d++) oblique_h[h][d] = (float)rand_norm(&st) * 0.45f;
    }
    for (int c = 0; c < TRIAGE_CLASSES; c++) {
        for (int h = 0; h < 24; h++) oblique_out[c][h] = (float)rand_norm(&st) * 0.9f;
        for (int d = 0; d < TRIAGE_DIM; d++) ctx->tri_teacher_w[c][d] = (float)rand_norm(&st) * 0.35f;
    }

    TriageInstance tri_templates[60];
    memset(tri_templates, 0, sizeof(tri_templates));
    for (int t = 0; t < 60; t++) {
        tri_templates[t].crash_sig = 0xA0000000U + (uint32_t)t;
        tri_templates[t].stratum_kind = 0;
        for (int d = 0; d < TRIAGE_DIM; d++) {
            int v = (int)lrint(rand_norm(&st) * 32.0);
            if (v < -120) v = -120; else if (v > 120) v = 120;
            tri_templates[t].x[d] = (int8_t)v;
        }
        tri_templates[t].label = (uint8_t)(t % TRIAGE_CLASSES);
    }

    for (int split = 0; split < 2; split++) {
        int n = (split == 0) ? N_CAL_PER_STRATUM : N_PER_STRATUM;
        TriageInstance *arr = (split == 0) ? ctx->cal_tri : ctx->test_tri;
        for (int i = 0; i < n; i++) {
            int rem = i % 10;
            if (rem < 3) {
                arr[i] = tri_templates[splitmix64(&st) % 60ULL];
            } else if (rem < 5) {
                arr[i].crash_sig = 0xB0000000U + (uint32_t)(split * 10000 + i);
                arr[i].stratum_kind = 1;
                uint8_t g_cls = (uint8_t)(splitmix64(&st) % 4ULL);
                for (int d = 0; d < TRIAGE_DIM; d++) {
                    int v = (int)lrint(rand_norm(&st) * 20.0);
                    if (v < -90) v = -90; else if (v > 90) v = 90;
                    arr[i].x[d] = (int8_t)v;
                }
                arr[i].x[g_cls] = 112; /* Clear explicit threshold guard trigger on dim 0..3 */
                arr[i].label = g_cls;
            } else {
                arr[i].crash_sig = 0xC0000000U + (uint32_t)(split * 10000 + i);
                arr[i].stratum_kind = 2;
                for (int d = 0; d < TRIAGE_DIM; d++) {
                    int v = (int)lrint(rand_norm(&st) * 42.0);
                    if (v < -120) v = -120; else if (v > 120) v = 120;
                    arr[i].x[d] = (int8_t)v;
                }
                /* Ensure no spurious dim 0..3 guard >= 100 */
                for (int d = 0; d < 4; d++) if (arr[i].x[d] >= 95) arr[i].x[d] = 80;

                float hid[24];
                for (int h = 0; h < 24; h++) {
                    float s = 0.0f;
                    for (int d = 0; d < TRIAGE_DIM; d++) s += oblique_h[h][d] * ((float)arr[i].x[d] / 64.0f);
                    hid[h] = s > 0.0f ? s : 0.0f;
                }
                float best_sc = -1e30f;
                uint8_t best_c = 0;
                for (int c = 0; c < TRIAGE_CLASSES; c++) {
                    float sc = 0.0f;
                    for (int h = 0; h < 24; h++) sc += oblique_out[c][h] * hid[h];
                    for (int d = 0; d < TRIAGE_DIM; d++) sc += 0.25f * ctx->tri_teacher_w[c][d] * ((float)arr[i].x[d] / 64.0f);
                    if (sc > best_sc) { best_sc = sc; best_c = (uint8_t)c; }
                }
                arr[i].label = best_c;
            }
        }
    }

    /* 4. Compile <= 4 KiB LUTs, CART depth-6 trees, centroids, and Dense MLPs strictly on `cal_*`! */
    ctx->default_api = 5;
    ctx->default_sat = 1;
    ctx->default_tri = 0;

    for (int i = 0; i < N_CAL_PER_STRATUM; i++) {
        lut_insert(ctx->lut_api, fnv1a_bytes(ctx->cal_api[i].f, sizeof(ctx->cal_api[i].f)), ctx->cal_api[i].label);
        lut_insert(ctx->lut_sat, fnv1a_bytes(ctx->cal_sat[i].lits, sizeof(ctx->cal_sat[i].lits)), ctx->cal_sat[i].is_sat);
        lut_insert(ctx->lut_tri, ctx->cal_tri[i].crash_sig, ctx->cal_tri[i].label);
    }

    /* Train CART-6 on API, SAT, Triage */
    int16_t *x_api = (int16_t *)malloc(N_CAL_PER_STRATUM * 8 * sizeof(int16_t));
    uint8_t *y_api = (uint8_t *)malloc(N_CAL_PER_STRATUM);
    float *xf_api = (float *)malloc(N_CAL_PER_STRATUM * 8 * sizeof(float));
    for (int i = 0; i < N_CAL_PER_STRATUM; i++) {
        memcpy(x_api + i * 8, ctx->cal_api[i].f, 8 * sizeof(int16_t));
        y_api[i] = ctx->cal_api[i].label;
        for (int j = 0; j < 8; j++) xf_api[i * 8 + j] = (float)ctx->cal_api[i].f[j] / 100.0f;
    }
    train_cart6(&ctx->tree_api, x_api, y_api, N_CAL_PER_STRATUM, 8, 8);
    train_mlp(&ctx->mlp_api, xf_api, y_api, N_CAL_PER_STRATUM, 8, 8, 0x1111ULL);

    int16_t *x_sat = (int16_t *)malloc(N_CAL_PER_STRATUM * 8 * sizeof(int16_t));
    uint8_t *y_sat = (uint8_t *)malloc(N_CAL_PER_STRATUM);
    float *xf_sat = (float *)malloc(N_CAL_PER_STRATUM * 8 * sizeof(float));
    for (int i = 0; i < N_CAL_PER_STRATUM; i++) {
        memcpy(x_sat + i * 8, ctx->cal_sat[i].feat8, 8 * sizeof(int16_t));
        y_sat[i] = ctx->cal_sat[i].is_sat;
        for (int j = 0; j < 8; j++) xf_sat[i * 8 + j] = (float)ctx->cal_sat[i].feat8[j] / 25.0f;
    }
    train_cart6(&ctx->tree_sat, x_sat, y_sat, N_CAL_PER_STRATUM, 8, 2);
    train_mlp(&ctx->mlp_sat, xf_sat, y_sat, N_CAL_PER_STRATUM, 8, 2, 0x2222ULL);

    int16_t *x_tri = (int16_t *)malloc(N_CAL_PER_STRATUM * TRIAGE_DIM * sizeof(int16_t));
    uint8_t *y_tri = (uint8_t *)malloc(N_CAL_PER_STRATUM);
    float *xf_tri = (float *)malloc(N_CAL_PER_STRATUM * TRIAGE_DIM * sizeof(float));
    int tri_cnt[TRIAGE_CLASSES] = {0};
    for (int i = 0; i < N_CAL_PER_STRATUM; i++) {
        uint8_t c = ctx->cal_tri[i].label;
        y_tri[i] = c;
        tri_cnt[c]++;
        for (int d = 0; d < TRIAGE_DIM; d++) {
            x_tri[i * TRIAGE_DIM + d] = (int16_t)ctx->cal_tri[i].x[d];
            xf_tri[i * TRIAGE_DIM + d] = (float)ctx->cal_tri[i].x[d] / 64.0f;
            ctx->tri_centroids[c][d] += (float)ctx->cal_tri[i].x[d];
        }
    }
    for (int c = 0; c < TRIAGE_CLASSES; c++) {
        float denom = (float)(tri_cnt[c] > 0 ? tri_cnt[c] : 1);
        for (int d = 0; d < TRIAGE_DIM; d++) ctx->tri_centroids[c][d] /= denom;
    }
    train_cart6(&ctx->tree_tri, x_tri, y_tri, N_CAL_PER_STRATUM, TRIAGE_DIM, TRIAGE_CLASSES);
    train_mlp(&ctx->mlp_tri, xf_tri, y_tri, N_CAL_PER_STRATUM, TRIAGE_DIM, TRIAGE_CLASSES, 0x3333ULL);

    free(x_api); free(y_api); free(xf_api);
    free(x_sat); free(y_sat); free(xf_sat);
    free(x_tri); free(y_tri); free(xf_tri);
    return ctx;
}

void dnull_free(DnullSuiteCtx *ctx) {
    if (ctx) free(ctx);
}

static uint8_t predict_stratum0(const DnullSuiteCtx *ctx, int arm_id, const ApiInstance *ins) {
    if (arm_id == 0) {
        int h = lut_query(ctx->lut_api, fnv1a_bytes(ins->f, sizeof(ins->f)));
        return (h >= 0) ? (uint8_t)h : ctx->default_api;
    }
    if (arm_id == 1) return eval_api_spec_if_else(ins->f);
    if (arm_id == 2) return eval_api_for_loop_table(ins->f);
    if (arm_id == 3) return eval_cart6(&ctx->tree_api, ins->f);
    if (arm_id == 4 || arm_id == 5) {
        int h = lut_query(ctx->lut_api, fnv1a_bytes(ins->f, sizeof(ins->f)));
        return (h >= 0) ? (uint8_t)h : eval_api_spec_if_else(ins->f);
    }
    float xf[8];
    for (int j = 0; j < 8; j++) xf[j] = (float)ins->f[j] / 100.0f;
    return eval_mlp(&ctx->mlp_api, xf);
}

static uint8_t predict_stratum1(const DnullSuiteCtx *ctx, int arm_id, const SatInstance *ins) {
    if (arm_id == 0) {
        int h = lut_query(ctx->lut_sat, fnv1a_bytes(ins->lits, sizeof(ins->lits)));
        return (h >= 0) ? (uint8_t)h : ctx->default_sat;
    }
    if (arm_id == 1) {
        /* Surface polarity & pure-literal if/else heuristic */
        if (ins->feat8[1] >= 2) return 1;
        if (ins->feat8[5] >= 36 && ins->feat8[6] >= 12) return 0;
        if (ins->feat8[2] >= 22) return 1;
        return (ins->feat8[0] >= 0) ? 1 : 0;
    }
    if (arm_id == 2) return solve_sat_bounded_for_loop(ins);
    if (arm_id == 3) return eval_cart6(&ctx->tree_sat, ins->feat8);
    if (arm_id == 4) return solve_sat_exact_dpll(ins);
    if (arm_id == 5) {
        int h = lut_query(ctx->lut_sat, fnv1a_bytes(ins->lits, sizeof(ins->lits)));
        if (h >= 0) return (uint8_t)h;
        return solve_sat_exact_dpll(ins);
    }
    float xf[8];
    for (int j = 0; j < 8; j++) xf[j] = (float)ins->feat8[j] / 25.0f;
    return eval_mlp(&ctx->mlp_sat, xf);
}

static uint8_t eval_triage_for_loop_centroid(const DnullSuiteCtx *ctx, const TriageInstance *ins) {
    float best_d = 1e30f;
    uint8_t best_c = 0;
    for (int c = 0; c < TRIAGE_CLASSES; c++) {
        float dist = 0.0f;
        for (int d = 0; d < TRIAGE_DIM; d++) {
            float diff = (float)ins->x[d] - ctx->tri_centroids[c][d];
            dist += diff * diff;
        }
        if (dist < best_d) { best_d = dist; best_c = (uint8_t)c; }
    }
    return best_c;
}

static uint8_t predict_stratum2(const DnullSuiteCtx *ctx, int arm_id, const TriageInstance *ins) {
    if (arm_id == 0) {
        int h = lut_query(ctx->lut_tri, ins->crash_sig);
        return (h >= 0) ? (uint8_t)h : ctx->default_tri;
    }
    if (arm_id == 1) {
        for (int g = 0; g < 4; g++) {
            if (ins->x[g] >= 100) return (uint8_t)g;
        }
        return (ins->x[4] + ins->x[5] > 0) ? 4 : 5;
    }
    if (arm_id == 2) return eval_triage_for_loop_centroid(ctx, ins);
    if (arm_id == 3) {
        int16_t x16[TRIAGE_DIM];
        for (int d = 0; d < TRIAGE_DIM; d++) x16[d] = (int16_t)ins->x[d];
        return eval_cart6(&ctx->tree_tri, x16);
    }
    if (arm_id == 4 || arm_id == 5) {
        /* Shape D: O(1) crash-hash LUT -> explicit guard verification -> linear prototype scan */
        int h = lut_query(ctx->lut_tri, ins->crash_sig);
        if (h >= 0) return (uint8_t)h;
        for (int g = 0; g < 4; g++) {
            if (ins->x[g] >= 100) return (uint8_t)g;
        }
        return eval_triage_for_loop_centroid(ctx, ins);
    }
    float xf[TRIAGE_DIM];
    for (int d = 0; d < TRIAGE_DIM; d++) xf[d] = (float)ins->x[d] / 64.0f;
    return eval_mlp(&ctx->mlp_tri, xf);
}

/* Evaluate an arm across all 1,500 held-out instances (or a specific stratum 0..2; -1 = all 1,500) */
uint64_t dnull_eval_arm(
    const DnullSuiteCtx *ctx,
    int arm_id,
    int stratum_filter,
    int outer_reps,
    int *out_correct_per_stratum3,
    uint8_t *out_preds1500,
    double *out_elapsed_ns
) {
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    uint64_t fnv = 1469598103934665603ULL;
    int c0 = 0, c1 = 0, c2 = 0;

    for (int rep = 0; rep < outer_reps; rep++) {
        c0 = c1 = c2 = 0;
        uint64_t h = 1469598103934665603ULL;
        if (stratum_filter < 0 || stratum_filter == 0) {
            for (int i = 0; i < N_PER_STRATUM; i++) {
                uint8_t p = predict_stratum0(ctx, arm_id, &ctx->test_api[i]);
                if (p == ctx->test_api[i].label) c0++;
                if (rep == 0 && out_preds1500) out_preds1500[i] = p;
                h = (h ^ p) * 1099511628211ULL;
            }
        }
        if (stratum_filter < 0 || stratum_filter == 1) {
            for (int i = 0; i < N_PER_STRATUM; i++) {
                uint8_t p = predict_stratum1(ctx, arm_id, &ctx->test_sat[i]);
                if (p == ctx->test_sat[i].is_sat) c1++;
                if (rep == 0 && out_preds1500) out_preds1500[N_PER_STRATUM + i] = p;
                h = (h ^ p) * 1099511628211ULL;
            }
        }
        if (stratum_filter < 0 || stratum_filter == 2) {
            for (int i = 0; i < N_PER_STRATUM; i++) {
                uint8_t p = predict_stratum2(ctx, arm_id, &ctx->test_tri[i]);
                if (p == ctx->test_tri[i].label) c2++;
                if (rep == 0 && out_preds1500) out_preds1500[2 * N_PER_STRATUM + i] = p;
                h = (h ^ p) * 1099511628211ULL;
            }
        }
        fnv = h;
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    out_correct_per_stratum3[0] = c0;
    out_correct_per_stratum3[1] = c1;
    out_correct_per_stratum3[2] = c2;
    *out_elapsed_ns = (double)(t1.tv_sec - t0.tv_sec) * 1e9 + (double)(t1.tv_nsec - t0.tv_nsec);
    return fnv;
}

/* Export canonical dataset bytes & ground-truth labels for SHA-256 manifest pre-commitment & external adapters */
void dnull_export_ground_truth(const DnullSuiteCtx *ctx, uint8_t *out_labels1500, uint8_t *out_canonical_blob, int *out_blob_len) {
    for (int i = 0; i < N_PER_STRATUM; i++) {
        out_labels1500[i] = ctx->test_api[i].label;
        out_labels1500[N_PER_STRATUM + i] = ctx->test_sat[i].is_sat;
        out_labels1500[2 * N_PER_STRATUM + i] = ctx->test_tri[i].label;
    }
    size_t off = 0;
    memcpy(out_canonical_blob + off, ctx->test_api, sizeof(ctx->test_api));
    off += sizeof(ctx->test_api);
    memcpy(out_canonical_blob + off, ctx->test_sat, sizeof(ctx->test_sat));
    off += sizeof(ctx->test_sat);
    memcpy(out_canonical_blob + off, ctx->test_tri, sizeof(ctx->test_tri));
    off += sizeof(ctx->test_tri);
    *out_blob_len = (int)off;
}

void dnull_get_instance_features(const DnullSuiteCtx *ctx, int global_idx, int16_t *out_feats32, int *out_len) {
    if (global_idx < N_PER_STRATUM) {
        for (int j = 0; j < 8; j++) out_feats32[j] = ctx->test_api[global_idx].f[j];
        *out_len = 8;
    } else if (global_idx < 2 * N_PER_STRATUM) {
        int k = global_idx - N_PER_STRATUM;
        for (int j = 0; j < 8; j++) out_feats32[j] = ctx->test_sat[k].feat8[j];
        *out_len = 8;
    } else {
        int k = global_idx - 2 * N_PER_STRATUM;
        for (int j = 0; j < TRIAGE_DIM; j++) out_feats32[j] = (int16_t)ctx->test_tri[k].x[j];
        *out_len = TRIAGE_DIM;
    }
}
