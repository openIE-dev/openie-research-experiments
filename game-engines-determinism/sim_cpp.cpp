// C++20 target for `game-engines` (`GE-H1` Q32.32 & `GE-H2` strict f64 / fast-math FMA / f32).
// Compiled via:
//   Strict:    clang++ -std=c++20 -O3 -ffp-contract=off -fno-fast-math sim_cpp.cpp -o sim_cpp_strict
//   Fast-math: clang++ -std=c++20 -O3 -ffast-math -ffp-contract=fast sim_cpp.cpp -o sim_cpp_fastmath

#include <CommonCrypto/CommonDigest.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

static std::string sha256_hex(const uint8_t* data, size_t len) {
    uint8_t md[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data, static_cast<CC_LONG>(len), md);
    char hex[65];
    for (int i = 0; i < 32; ++i) {
        std::snprintf(hex + i * 2, 3, "%02x", md[i]);
    }
    hex[64] = '\0';
    return std::string(hex);
}

static constexpr size_t N_BODIES = 16;
static constexpr size_t N_PICKUPS = 4;
static constexpr int64_t ONE = int64_t(1) << 32;
static constexpr int64_t BOUND = 62 * ONE;
static constexpr int64_t MAX_V = 48 * ONE;
static constexpr int64_t DT_Q = int64_t(1) << 26;
static constexpr int64_t DRAG_IDLE = 4273492459LL;
static constexpr int64_t DRAG_DASH = 4286377361LL;
static constexpr int64_t REST_WALL = 3865470566LL;
static constexpr int64_t ONE_PLUS_E = 7945689498LL;
static constexpr int64_t MIN_DIST = 4 * ONE;
static constexpr __int128 MIN_DIST_SQ = static_cast<__int128>(MIN_DIST) * static_cast<__int128>(MIN_DIST);
static constexpr int64_t PICKUP_DIST = 5 * ONE;
static constexpr __int128 PICKUP_DIST_SQ = static_cast<__int128>(PICKUP_DIST) * static_cast<__int128>(PICKUP_DIST);
static constexpr int64_t DIAG = 3037000500LL;

static constexpr std::array<int64_t, 8> DIR_X = {ONE, DIAG, 0, -DIAG, -ONE, -DIAG, 0, DIAG};
static constexpr std::array<int64_t, 8> DIR_Y = {0, DIAG, ONE, DIAG, 0, -DIAG, -ONE, -DIAG};

static constexpr uint64_t INITIAL_SEED = 2316557121413006641ULL;
static constexpr uint64_t SM_C0 = 11400714819323198485ULL;
static constexpr uint64_t SM_C1 = 13787848793156543929ULL;
static constexpr uint64_t SM_C2 = 10723151780598845931ULL;

static inline std::pair<uint64_t, uint64_t> splitmix64_next(uint64_t state) {
    uint64_t s = state + SM_C0;
    uint64_t z = s;
    z = (z ^ (z >> 30)) * SM_C1;
    z = (z ^ (z >> 27)) * SM_C2;
    uint64_t out = z ^ (z >> 31);
    return {s, out};
}

static inline int64_t qmul(int64_t a, int64_t b) {
    return static_cast<int64_t>((static_cast<__int128>(a) * static_cast<__int128>(b)) >> 32);
}

static inline int64_t trunc_div128(__int128 num, __int128 den) {
    unsigned __int128 d = static_cast<unsigned __int128>(den);
    if (num >= 0) {
        return static_cast<int64_t>(static_cast<unsigned __int128>(num) / d);
    }
    unsigned __int128 mag = static_cast<unsigned __int128>(-num);
    return -static_cast<int64_t>(mag / d);
}

static inline int64_t isqrt_u128(unsigned __int128 n) {
    if (n == 0) return 0;
    uint32_t bits = 0;
    unsigned __int128 tmp = n;
    while (tmp > 0) {
        ++bits;
        tmp >>= 1;
    }
    unsigned __int128 x = static_cast<unsigned __int128>(1) << ((bits + 1) >> 1);
    while (true) {
        unsigned __int128 y = (x + n / x) >> 1;
        if (y >= x) return static_cast<int64_t>(x);
        x = y;
    }
}

template <typename T>
static inline void put_le(uint8_t* dst, size_t& off, T val) {
    std::memcpy(dst + off, &val, sizeof(T));
    off += sizeof(T);
}

static std::vector<std::pair<uint32_t, std::string>> run_q32_sim(uint32_t ticks, uint32_t stride) {
    uint64_t rng = INITIAL_SEED;
    std::array<int64_t, N_BODIES> bx{}, by{}, bvx{}, bvy{}, bmass{};
    std::array<uint8_t, N_BODIES> bfsm{};
    std::array<uint16_t, N_BODIES> btimer{};
    std::array<uint32_t, N_BODIES> bscore{};

    for (size_t i = 0; i < N_BODIES; ++i) {
        int64_t gx = ((static_cast<int64_t>(i & 3) * 30) - 45) * ONE;
        int64_t gy = ((static_cast<int64_t>(i >> 2) * 30) - 45) * ONE;
        auto [r_n1, r1] = splitmix64_next(rng);
        auto [r_n2, r2] = splitmix64_next(r_n1);
        rng = r_n2;
        int64_t jx = static_cast<int64_t>(r1 & 0xFFFFFFFFULL) - 2147483648LL;
        int64_t jy = static_cast<int64_t>((r1 >> 32) & 0xFFFFFFFFULL) - 2147483648LL;
        bx[i] = gx + jx;
        by[i] = gy + jy;
        bvx[i] = (static_cast<int64_t>(r2 & 0xFFFFFFFFULL) - 2147483648LL) * 24;
        bvy[i] = (static_cast<int64_t>((r2 >> 32) & 0xFFFFFFFFULL) - 2147483648LL) * 24;
        bmass[i] = (4 + static_cast<int64_t>(i & 3)) << 30;
    }

    std::array<int64_t, N_PICKUPS> px{}, py{};
    std::array<uint8_t, N_PICKUPS> pactive{};
    std::array<uint16_t, N_PICKUPS> prespawn{};
    for (size_t p = 0; p < N_PICKUPS; ++p) {
        px[p] = ((p & 1) == 0) ? (-20 * ONE) : (20 * ONE);
        py[p] = ((p >> 1) == 0) ? (-20 * ONE) : (20 * ONE);
        pactive[p] = 1;
        prespawn[p] = 0;
    }

    std::vector<std::pair<uint32_t, std::string>> checkpoints;
    uint8_t buf[732];
    uint32_t tick = 0;

    for (uint32_t step = 0; step < ticks; ++step) {
        auto [rng2, ev] = splitmix64_next(rng);
        rng = rng2;
        size_t actor = static_cast<size_t>(ev & 15ULL);
        size_t d = static_cast<size_t>((ev >> 4) & 7ULL);
        bool want_dash = ((ev >> 7) & 3ULL) == 0ULL;
        if (want_dash && bfsm[actor] == 0) {
            bfsm[actor] = 1;
            btimer[actor] = 12;
            bvx[actor] += 6 * DIR_X[d];
            bvy[actor] += 6 * DIR_Y[d];
        } else {
            bvx[actor] += 2 * DIR_X[d];
            bvy[actor] += 2 * DIR_Y[d];
        }

        for (size_t i = 0; i < N_BODIES; ++i) {
            if (bfsm[i] == 1) {
                btimer[i] -= 1;
                if (btimer[i] == 0) {
                    bfsm[i] = 2;
                    btimer[i] = 40;
                }
            } else if (bfsm[i] == 2) {
                btimer[i] -= 1;
                if (btimer[i] == 0) {
                    bfsm[i] = 0;
                }
            }
            int64_t drag = (bfsm[i] == 1) ? DRAG_DASH : DRAG_IDLE;
            int64_t vx = std::clamp(qmul(bvx[i], drag), -MAX_V, MAX_V);
            int64_t vy = std::clamp(qmul(bvy[i], drag), -MAX_V, MAX_V);
            int64_t x = bx[i] + qmul(vx, DT_Q);
            int64_t y = by[i] + qmul(vy, DT_Q);
            if (x > BOUND) {
                x = 2 * BOUND - x;
                vx = -qmul(vx, REST_WALL);
            } else if (x < -BOUND) {
                x = -2 * BOUND - x;
                vx = -qmul(vx, REST_WALL);
            }
            if (y > BOUND) {
                y = 2 * BOUND - y;
                vy = -qmul(vy, REST_WALL);
            } else if (y < -BOUND) {
                y = -2 * BOUND - y;
                vy = -qmul(vy, REST_WALL);
            }
            bx[i] = x;
            by[i] = y;
            bvx[i] = vx;
            bvy[i] = vy;
        }

        for (size_t i = 0; i < N_BODIES; ++i) {
            for (size_t j = i + 1; j < N_BODIES; ++j) {
                int64_t dx = bx[j] - bx[i];
                int64_t dy = by[j] - by[i];
                __int128 dist_sq = static_cast<__int128>(dx) * static_cast<__int128>(dx) +
                                   static_cast<__int128>(dy) * static_cast<__int128>(dy);
                if (dist_sq > 0 && dist_sq < MIN_DIST_SQ) {
                    int64_t dist = isqrt_u128(static_cast<unsigned __int128>(dist_sq));
                    int64_t nx = trunc_div128(static_cast<__int128>(dx) * static_cast<__int128>(ONE), dist);
                    int64_t ny = trunc_div128(static_cast<__int128>(dy) * static_cast<__int128>(ONE), dist);
                    int64_t sep = (MIN_DIST - dist) >> 1;
                    int64_t cx = qmul(sep, nx);
                    int64_t cy = qmul(sep, ny);
                    bx[i] -= cx;
                    by[i] -= cy;
                    bx[j] += cx;
                    by[j] += cy;

                    int64_t rvx = bvx[j] - bvx[i];
                    int64_t rvy = bvy[j] - bvy[i];
                    int64_t vn = qmul(rvx, nx) + qmul(rvy, ny);
                    if (vn < 0) {
                        int64_t j_base = qmul(-vn, ONE_PLUS_E);
                        int64_t msum = bmass[i] + bmass[j];
                        int64_t dvi = trunc_div128(static_cast<__int128>(j_base) * static_cast<__int128>(bmass[j]), msum);
                        int64_t dvj = trunc_div128(static_cast<__int128>(j_base) * static_cast<__int128>(bmass[i]), msum);
                        bvx[i] -= qmul(dvi, nx);
                        bvy[i] -= qmul(dvi, ny);
                        bvx[j] += qmul(dvj, nx);
                        bvy[j] += qmul(dvj, ny);
                    }
                }
            }
        }

        std::array<uint8_t, N_PICKUPS> deact{}, resp{};
        for (size_t p = 0; p < N_PICKUPS; ++p) {
            if (pactive[p] == 1) {
                for (size_t i = 0; i < N_BODIES; ++i) {
                    int64_t pdx = bx[i] - px[p];
                    int64_t pdy = by[i] - py[p];
                    if (static_cast<__int128>(pdx) * static_cast<__int128>(pdx) +
                        static_cast<__int128>(pdy) * static_cast<__int128>(pdy) <= PICKUP_DIST_SQ) {
                        bscore[i] += 1;
                        deact[p] = 1;
                        break;
                    }
                }
            } else {
                prespawn[p] -= 1;
                if (prespawn[p] == 0) resp[p] = 1;
            }
        }
        for (size_t p = 0; p < N_PICKUPS; ++p) {
            if (deact[p] == 1) {
                pactive[p] = 0;
                prespawn[p] = 75;
            }
            if (resp[p] == 1) {
                auto [rng3, rp] = splitmix64_next(rng);
                rng = rng3;
                px[p] = (static_cast<int64_t>(rp & 0xFFFFFFFFULL) - 2147483648LL) * 80;
                py[p] = (static_cast<int64_t>((rp >> 32) & 0xFFFFFFFFULL) - 2147483648LL) * 80;
                pactive[p] = 1;
            }
        }

        ++tick;
        if (stride > 0 && (tick % stride == 0 || tick == ticks)) {
            size_t o = 0;
            put_le(buf, o, tick);
            put_le(buf, o, rng);
            for (size_t i = 0; i < N_BODIES; ++i) {
                put_le(buf, o, bx[i]);
                put_le(buf, o, by[i]);
                put_le(buf, o, bvx[i]);
                put_le(buf, o, bvy[i]);
                put_le(buf, o, bscore[i]);
                put_le(buf, o, btimer[i]);
                put_le(buf, o, bfsm[i]);
                put_le(buf, o, uint8_t(0));
            }
            for (size_t p = 0; p < N_PICKUPS; ++p) {
                put_le(buf, o, px[p]);
                put_le(buf, o, py[p]);
                put_le(buf, o, prespawn[p]);
                put_le(buf, o, pactive[p]);
                put_le(buf, o, uint8_t(0));
            }
            checkpoints.emplace_back(tick, sha256_hex(buf, 732));
        }
    }
    return checkpoints;
}

static inline uint64_t canon_f64_bits(double v) {
    uint64_t bits = 0;
    std::memcpy(&bits, &v, 8);
    if ((bits & 0x7FFFFFFFFFFFFFFFULL) == 0ULL) return 0ULL; // -0.0 -> +0.0 without fast-math folding
    return bits;
}

template <typename Real>
static void run_float_trace(uint32_t ticks, bool use_trig) {
    const double one_f = static_cast<double>(ONE);
    std::array<Real, 8> dir_fx{}, dir_fy{};
    for (size_t k = 0; k < 8; ++k) {
        dir_fx[k] = static_cast<Real>(static_cast<double>(DIR_X[k]) / one_f);
        dir_fy[k] = static_cast<Real>(static_cast<double>(DIR_Y[k]) / one_f);
    }

    uint64_t rng = INITIAL_SEED;
    std::array<Real, N_BODIES> bx{}, by{}, bvx{}, bvy{}, bmass{};
    std::array<uint8_t, N_BODIES> bfsm{};
    std::array<uint16_t, N_BODIES> btimer{};
    std::array<uint32_t, N_BODIES> bscore{};

    for (size_t i = 0; i < N_BODIES; ++i) {
        int64_t gx = ((static_cast<int64_t>(i & 3) * 30) - 45) * ONE;
        int64_t gy = ((static_cast<int64_t>(i >> 2) * 30) - 45) * ONE;
        auto [r_n1, r1] = splitmix64_next(rng);
        auto [r_n2, r2] = splitmix64_next(r_n1);
        rng = r_n2;
        int64_t jx = static_cast<int64_t>(r1 & 0xFFFFFFFFULL) - 2147483648LL;
        int64_t jy = static_cast<int64_t>((r1 >> 32) & 0xFFFFFFFFULL) - 2147483648LL;
        bx[i] = static_cast<Real>(static_cast<double>(gx + jx) / one_f);
        by[i] = static_cast<Real>(static_cast<double>(gy + jy) / one_f);
        bvx[i] = static_cast<Real>(static_cast<double>((static_cast<int64_t>(r2 & 0xFFFFFFFFULL) - 2147483648LL) * 24) / one_f);
        bvy[i] = static_cast<Real>(static_cast<double>((static_cast<int64_t>((r2 >> 32) & 0xFFFFFFFFULL) - 2147483648LL) * 24) / one_f);
        bmass[i] = static_cast<Real>(static_cast<double>((4 + static_cast<int64_t>(i & 3)) << 30) / one_f);
    }

    std::array<Real, N_PICKUPS> px{}, py{};
    std::array<uint8_t, N_PICKUPS> pactive{};
    std::array<uint16_t, N_PICKUPS> prespawn{};
    for (size_t p = 0; p < N_PICKUPS; ++p) {
        px[p] = ((p & 1) == 0) ? Real(-20.0) : Real(20.0);
        py[p] = ((p >> 1) == 0) ? Real(-20.0) : Real(20.0);
        pactive[p] = 1;
        prespawn[p] = 0;
    }

    const Real dt_f = static_cast<Real>(1.0 / 64.0);
    const Real drag_idle_f = static_cast<Real>(static_cast<double>(DRAG_IDLE) / one_f);
    const Real drag_dash_f = static_cast<Real>(static_cast<double>(DRAG_DASH) / one_f);
    const Real rest_wall_f = static_cast<Real>(static_cast<double>(REST_WALL) / one_f);
    const Real one_plus_e_f = static_cast<Real>(static_cast<double>(ONE_PLUS_E) / one_f);

    uint8_t ieee_buf[732];
    uint8_t mm_buf[4 + N_BODIES * 23];
    uint8_t gp_buf[4 + N_BODIES * 6 + N_PICKUPS];
    uint32_t tick = 0;

    std::cout << "{\"trace\":[";
    for (uint32_t step = 0; step < ticks; ++step) {
        auto [rng2, ev] = splitmix64_next(rng);
        rng = rng2;
        size_t actor = static_cast<size_t>(ev & 15ULL);
        size_t d = static_cast<size_t>((ev >> 4) & 7ULL);
        bool want_dash = ((ev >> 7) & 3ULL) == 0ULL;
        Real ux, uy;
        if (use_trig) {
            Real theta = static_cast<Real>(0.017453292519943295) * static_cast<Real>(tick + 1) +
                         static_cast<Real>(0.7853981633974483) * static_cast<Real>(d);
            ux = std::cos(theta);
            uy = std::sin(theta);
        } else {
            ux = dir_fx[d];
            uy = dir_fy[d];
        }
        if (want_dash && bfsm[actor] == 0) {
            bfsm[actor] = 1;
            btimer[actor] = 12;
            bvx[actor] = bvx[actor] + Real(6.0) * ux;
            bvy[actor] = bvy[actor] + Real(6.0) * uy;
        } else {
            bvx[actor] = bvx[actor] + Real(2.0) * ux;
            bvy[actor] = bvy[actor] + Real(2.0) * uy;
        }

        for (size_t i = 0; i < N_BODIES; ++i) {
            if (bfsm[i] == 1) {
                btimer[i] -= 1;
                if (btimer[i] == 0) {
                    bfsm[i] = 2;
                    btimer[i] = 40;
                }
            } else if (bfsm[i] == 2) {
                btimer[i] -= 1;
                if (btimer[i] == 0) bfsm[i] = 0;
            }
            Real drag = (bfsm[i] == 1) ? drag_dash_f : drag_idle_f;
            Real vx = bvx[i] * drag;
            Real vy = bvy[i] * drag;
            if (vx > Real(48.0)) vx = Real(48.0);
            else if (vx < Real(-48.0)) vx = Real(-48.0);
            if (vy > Real(48.0)) vy = Real(48.0);
            else if (vy < Real(-48.0)) vy = Real(-48.0);

            Real x = bx[i] + vx * dt_f;
            Real y = by[i] + vy * dt_f;
            if (x > Real(62.0)) {
                x = Real(124.0) - x;
                vx = -(vx * rest_wall_f);
            } else if (x < Real(-62.0)) {
                x = Real(-124.0) - x;
                vx = -(vx * rest_wall_f);
            }
            if (y > Real(62.0)) {
                y = Real(124.0) - y;
                vy = -(vy * rest_wall_f);
            } else if (y < Real(-62.0)) {
                y = Real(-124.0) - y;
                vy = -(vy * rest_wall_f);
            }
            bx[i] = x;
            by[i] = y;
            bvx[i] = vx;
            bvy[i] = vy;
        }

        for (size_t i = 0; i < N_BODIES; ++i) {
            for (size_t j = i + 1; j < N_BODIES; ++j) {
                Real dx = bx[j] - bx[i];
                Real dy = by[j] - by[i];
                Real dist_sq = dx * dx + dy * dy;
                if (dist_sq > Real(0.0) && dist_sq < Real(16.0)) {
                    Real dist = std::sqrt(dist_sq);
                    Real nx = dx / dist;
                    Real ny = dy / dist;
                    Real sep = Real(0.5) * (Real(4.0) - dist);
                    bx[i] = bx[i] - sep * nx;
                    by[i] = by[i] - sep * ny;
                    bx[j] = bx[j] + sep * nx;
                    by[j] = by[j] + sep * ny;
                    Real rvx = bvx[j] - bvx[i];
                    Real rvy = bvy[j] - bvy[i];
                    Real vn = rvx * nx + rvy * ny;
                    if (vn < Real(0.0)) {
                        Real j_base = (-vn) * one_plus_e_f;
                        Real msum = bmass[i] + bmass[j];
                        Real dvi = (j_base * bmass[j]) / msum;
                        Real dvj = (j_base * bmass[i]) / msum;
                        bvx[i] = bvx[i] - dvi * nx;
                        bvy[i] = bvy[i] - dvi * ny;
                        bvx[j] = bvx[j] + dvj * nx;
                        bvy[j] = bvy[j] + dvj * ny;
                    }
                }
            }
        }

        std::array<uint8_t, N_PICKUPS> deact{}, resp{};
        for (size_t p = 0; p < N_PICKUPS; ++p) {
            if (pactive[p] == 1) {
                for (size_t i = 0; i < N_BODIES; ++i) {
                    Real pdx = bx[i] - px[p];
                    Real pdy = by[i] - py[p];
                    if (pdx * pdx + pdy * pdy <= Real(25.0)) {
                        bscore[i] += 1;
                        deact[p] = 1;
                        break;
                    }
                }
            } else {
                prespawn[p] -= 1;
                if (prespawn[p] == 0) resp[p] = 1;
            }
        }
        for (size_t p = 0; p < N_PICKUPS; ++p) {
            if (deact[p] == 1) {
                pactive[p] = 0;
                prespawn[p] = 75;
            }
            if (resp[p] == 1) {
                auto [rng3, rp] = splitmix64_next(rng);
                rng = rng3;
                px[p] = static_cast<Real>(static_cast<double>((static_cast<int64_t>(rp & 0xFFFFFFFFULL) - 2147483648LL) * 80) / one_f);
                py[p] = static_cast<Real>(static_cast<double>((static_cast<int64_t>((rp >> 32) & 0xFFFFFFFFULL) - 2147483648LL) * 80) / one_f);
                pactive[p] = 1;
            }
        }

        ++tick;
        size_t o1 = 0, o2 = 0, o3 = 0;
        put_le(ieee_buf, o1, tick);
        put_le(ieee_buf, o1, rng);
        put_le(mm_buf, o2, tick);
        put_le(gp_buf, o3, tick);
        for (size_t i = 0; i < N_BODIES; ++i) {
            put_le(ieee_buf, o1, canon_f64_bits(static_cast<double>(bx[i])));
            put_le(ieee_buf, o1, canon_f64_bits(static_cast<double>(by[i])));
            put_le(ieee_buf, o1, canon_f64_bits(static_cast<double>(bvx[i])));
            put_le(ieee_buf, o1, canon_f64_bits(static_cast<double>(bvy[i])));
            put_le(ieee_buf, o1, bscore[i]);
            put_le(ieee_buf, o1, btimer[i]);
            put_le(ieee_buf, o1, bfsm[i]);
            put_le(ieee_buf, o1, uint8_t(0));

            int64_t qx = static_cast<int64_t>(std::floor(static_cast<double>(bx[i]) * 1000.0));
            int64_t qy = static_cast<int64_t>(std::floor(static_cast<double>(by[i]) * 1000.0));
            put_le(mm_buf, o2, qx);
            put_le(mm_buf, o2, qy);
            put_le(mm_buf, o2, bscore[i]);
            put_le(mm_buf, o2, btimer[i]);
            put_le(mm_buf, o2, bfsm[i]);

            uint8_t quad = (bx[i] >= Real(0.0) ? 1u : 0u) | (by[i] >= Real(0.0) ? 2u : 0u);
            put_le(gp_buf, o3, bscore[i]);
            put_le(gp_buf, o3, bfsm[i]);
            put_le(gp_buf, o3, quad);
        }
        for (size_t p = 0; p < N_PICKUPS; ++p) {
            put_le(ieee_buf, o1, canon_f64_bits(static_cast<double>(px[p])));
            put_le(ieee_buf, o1, canon_f64_bits(static_cast<double>(py[p])));
            put_le(ieee_buf, o1, prespawn[p]);
            put_le(ieee_buf, o1, pactive[p]);
            put_le(ieee_buf, o1, uint8_t(0));
            put_le(gp_buf, o3, pactive[p]);
        }

        if (step > 0) std::cout << ",";
        std::cout << "[\"" << sha256_hex(ieee_buf, sizeof(ieee_buf)).substr(0, 16) << "\",\""
                  << sha256_hex(mm_buf, sizeof(mm_buf)).substr(0, 16) << "\",\""
                  << sha256_hex(gp_buf, sizeof(gp_buf)).substr(0, 16) << "\"]";
    }
    std::cout << "]}\n";
}

int main(int argc, char** argv) {
    std::string mode = "q32";
    uint32_t ticks = 100000;
    uint32_t stride = 1000;
    uint32_t loops = 1;
    bool handshake = false;

    for (int i = 1; i < argc; ++i) {
        std::string a(argv[i]);
        if (a == "--mode" && i + 1 < argc) mode = argv[++i];
        else if (a == "--ticks" && i + 1 < argc) ticks = static_cast<uint32_t>(std::stoul(argv[++i]));
        else if (a == "--stride" && i + 1 < argc) stride = static_cast<uint32_t>(std::stoul(argv[++i]));
        else if (a == "--loops" && i + 1 < argc) loops = static_cast<uint32_t>(std::stoul(argv[++i]));
        else if (a == "--handshake") handshake = true;
    }

    if (mode == "q32") {
        (void)run_q32_sim(500, 500);
        std::string line;
        if (handshake) {
            std::cout << "READY\n" << std::flush;
            std::getline(std::cin, line);
        }
        auto t0 = std::chrono::steady_clock::now();
        std::vector<std::pair<uint32_t, std::string>> ck;
        for (uint32_t l = 0; l < loops; ++l) {
            ck = run_q32_sim(ticks, stride);
        }
        auto t1 = std::chrono::steady_clock::now();
        double wall_ms = std::chrono::duration<double, std::milli>(t1 - t0).count() / static_cast<double>(loops);
        std::cout << "DONE\t{\"wall_ms\":" << wall_ms << ",\"loops\":" << loops << ",\"checkpoints\":{";
        for (size_t idx = 0; idx < ck.size(); ++idx) {
            if (idx > 0) std::cout << ",";
            std::cout << "\"" << ck[idx].first << "\":\"" << ck[idx].second << "\"";
        }
        std::cout << "}}\n" << std::flush;
        if (handshake) {
            std::getline(std::cin, line);
        }
    } else if (mode == "f64_strict") {
        run_float_trace<double>(ticks, false);
    } else if (mode == "f64_trig") {
        run_float_trace<double>(ticks, true);
    } else if (mode == "f32_strict") {
        run_float_trace<float>(ticks, false);
    } else if (mode == "f32_trig") {
        run_float_trace<float>(ticks, true);
    }
    return 0;
}
