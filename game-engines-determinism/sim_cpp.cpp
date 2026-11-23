// Cross-OS C++20 target (`MSVC cl.exe` on Windows 11 x86_64, `clang++` / `g++` on macOS & Linux)
// for `game-engines` (`GE-H1` Q32.32 & `GE-H2` strict f64 / AVX2 FMA / fast-math / f32).
// Compiled via:
//   Windows MSVC strict: cl /nologo /std:c++20 /O2 /fp:strict /EHsc sim_cpp.cpp /Fe:sim_cpp_msvc_strict.exe
//   Windows MSVC AVX2:   cl /nologo /std:c++20 /O2 /arch:AVX2 /fp:precise /EHsc sim_cpp.cpp /Fe:sim_cpp_msvc_fma.exe
//   Windows MSVC fast:   cl /nologo /std:c++20 /O2 /arch:AVX2 /fp:fast /EHsc sim_cpp.cpp /Fe:sim_cpp_msvc_fast.exe
//   POSIX Clang/GCC:     clang++ -std=c++20 -O3 -ffp-contract=off -fno-fast-math sim_cpp.cpp -o sim_cpp_strict

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#ifdef _MSC_VER
#include <__msvc_int128.hpp>
using i128_t = std::_Signed128;
using u128_t = std::_Unsigned128;
#else
using i128_t = __int128;
using u128_t = unsigned __int128;
#endif

static inline uint32_t rotr32(uint32_t x, int n) {
    return (x >> n) | (x << (32 - n));
}

static constexpr std::array<uint32_t, 64> K256 = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
    0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
    0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
    0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u
};

static std::string sha256_hex(const uint8_t* data, size_t len) {
    uint32_t h[8] = {
        0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
        0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u
    };
    uint64_t bit_len = static_cast<uint64_t>(len) * 8ULL;
    size_t pad_len = (len + 9 + 63) & ~size_t(63);
    std::vector<uint8_t> msg(pad_len, 0);
    std::memcpy(msg.data(), data, len);
    msg[len] = 0x80u;
    for (int b = 0; b < 8; ++b) {
        msg[pad_len - 8 + b] = static_cast<uint8_t>(bit_len >> (56 - 8 * b));
    }

    uint32_t w[64];
    for (size_t off = 0; off < pad_len; off += 64) {
        for (int i = 0; i < 16; ++i) {
            w[i] = (static_cast<uint32_t>(msg[off + 4 * i]) << 24) |
                   (static_cast<uint32_t>(msg[off + 4 * i + 1]) << 16) |
                   (static_cast<uint32_t>(msg[off + 4 * i + 2]) << 8) |
                   static_cast<uint32_t>(msg[off + 4 * i + 3]);
        }
        for (int i = 16; i < 64; ++i) {
            uint32_t s0 = rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^ (w[i - 15] >> 3);
            uint32_t s1 = rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        uint32_t a = h[0], b = h[1], c = h[2], d = h[3];
        uint32_t e = h[4], f = h[5], g = h[6], hh = h[7];
        for (int i = 0; i < 64; ++i) {
            uint32_t s1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
            uint32_t ch = (e & f) ^ ((~e) & g);
            uint32_t t1 = hh + s1 + ch + K256[i] + w[i];
            uint32_t s0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
            uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            uint32_t t2 = s0 + maj;
            hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
        }
        h[0] += a; h[1] += b; h[2] += c; h[3] += d;
        h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }

    char hex[65];
    for (int i = 0; i < 8; ++i) {
        std::snprintf(hex + i * 8, 9, "%08x", h[i]);
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
static constexpr int64_t PICKUP_DIST = 5 * ONE;
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
    return static_cast<int64_t>((i128_t(a) * i128_t(b)) >> 32);
}

static inline int64_t trunc_div128(i128_t num, i128_t den) {
    u128_t d = static_cast<u128_t>(den);
    if (num >= i128_t(0)) {
        return static_cast<int64_t>(static_cast<u128_t>(num) / d);
    }
    u128_t mag = static_cast<u128_t>(-num);
    return -static_cast<int64_t>(mag / d);
}

static inline int64_t isqrt_u128(u128_t n) {
    if (n == u128_t(0)) return 0;
    uint32_t bits = 0;
    u128_t tmp = n;
    while (tmp > u128_t(0)) {
        ++bits;
        tmp >>= 1;
    }
    u128_t x = u128_t(1) << ((bits + 1) >> 1);
    while (true) {
        u128_t y = (x + n / x) >> 1;
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
    const i128_t min_dist_sq = i128_t(MIN_DIST) * i128_t(MIN_DIST);
    const i128_t pickup_dist_sq = i128_t(PICKUP_DIST) * i128_t(PICKUP_DIST);

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
                i128_t dist_sq = i128_t(dx) * i128_t(dx) + i128_t(dy) * i128_t(dy);
                if (dist_sq > i128_t(0) && dist_sq < min_dist_sq) {
                    int64_t dist = isqrt_u128(static_cast<u128_t>(dist_sq));
                    int64_t nx = trunc_div128(i128_t(dx) * i128_t(ONE), i128_t(dist));
                    int64_t ny = trunc_div128(i128_t(dy) * i128_t(ONE), i128_t(dist));
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
                        int64_t dvi = trunc_div128(i128_t(j_base) * i128_t(bmass[j]), i128_t(msum));
                        int64_t dvj = trunc_div128(i128_t(j_base) * i128_t(bmass[i]), i128_t(msum));
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
                    if (i128_t(pdx) * i128_t(pdx) + i128_t(pdy) * i128_t(pdy) <= pickup_dist_sq) {
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
    if ((bits & 0x7FFFFFFFFFFFFFFFULL) == 0ULL) return 0ULL;
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
