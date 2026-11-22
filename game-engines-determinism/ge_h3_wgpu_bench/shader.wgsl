// WGSL vertex + fragment pipeline for `game-engines` (`GE-H3` Cross-GPU Tolerance Benchmark).
// Renders canonical `Q32.32` 16-body + 4-pickup simulation states into a 512x512 RGBA8Unorm
// target via (1) a trigonometric procedural radar/grid background pass and (2) 20 declaration-
// ordered alpha-blended SDF + Blinn-Phong lit 3D sphere/torus entity quads.

struct SceneUniforms {
    // x: phase_rad in [0, 2*pi), y: arena_half (64.0), z: n_bodies (16.0), w: tick_id
    header: vec4<f32>,
    // xy: world position in [-64, 64], zw: velocity
    body_pos_vel: array<vec4<f32>, 16>,
    // x: radius (2.0), y: fsm_state (0,1,2), z: mass_tier (0..3), w: score
    body_meta: array<vec4<f32>, 16>,
    // xy: world position, z: radius (3.0), w: active (0 or 1)
    pickups: array<vec4<f32>, 4>,
};

@group(0) @binding(0)
var<uniform> scene: SceneUniforms;

@vertex
fn vs_bg(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let x = f32(i32(vi & 1u) * 4 - 1);
    let y = f32(i32(vi & 2u) * 2 - 1);
    return vec4<f32>(x, y, 0.0, 1.0);
}

fn pow16(v: f32) -> f32 {
    let v2 = v * v;
    let v4 = v2 * v2;
    let v8 = v4 * v4;
    return v8 * v8;
}

@fragment
fn fs_bg(@builtin(position) frag_pos: vec4<f32>) -> @location(0) vec4<f32> {
    let arena_half = scene.header.y;
    let phase = scene.header.x;
    let wx = (frag_pos.x / 512.0 * 2.0 - 1.0) * arena_half;
    let wy = (1.0 - frag_pos.y / 512.0 * 2.0) * arena_half;
    let p = vec2<f32>(wx, wy);
    let r = sqrt(wx * wx + wy * wy);

    let ring_wave = 0.5 + 0.5 * cos(r * 0.35 - phase);
    let gx = 0.5 + 0.5 * cos(wx * 0.39269908);
    let gy = 0.5 + 0.5 * cos(wy * 0.39269908);
    let grid = clamp(pow16(gx) + pow16(gy), 0.0, 1.0);

    let box_d = abs(max(abs(wx), abs(wy)) - 62.0);
    let border = 1.0 / (1.0 + box_d * box_d * 0.65);

    var field_glow = 0.0;
    for (var k: u32 = 0u; k < 4u; k = k + 1u) {
        let pk = scene.pickups[k];
        if (pk.w > 0.5) {
            let dp = p - pk.xy;
            let d2 = dot(dp, dp);
            field_glow = field_glow + 0.14 / (1.0 + d2 * 0.035);
        }
    }

    let vig = 1.0 / (1.0 + 0.00015 * r * r);
    var col = vec3<f32>(0.042, 0.056, 0.096) * vig;
    col = col + vec3<f32>(0.018, 0.048, 0.072) * ring_wave * vig;
    col = col + vec3<f32>(0.055, 0.095, 0.135) * grid * vig;
    col = col + vec3<f32>(0.55, 0.36, 0.08) * border * 0.65;
    col = col + vec3<f32>(0.04, 0.42, 0.36) * field_glow;

    return vec4<f32>(clamp(col, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
}

struct EntityVaryings {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0) @interpolate(flat) inst_id: u32,
};

@vertex
fn vs_entity(
    @builtin(vertex_index) vi: u32,
    @builtin(instance_index) iid: u32,
) -> EntityVaryings {
    var corners = array<vec2<f32>, 6>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>( 1.0, -1.0),
        vec2<f32>(-1.0,  1.0),
        vec2<f32>(-1.0,  1.0),
        vec2<f32>( 1.0, -1.0),
        vec2<f32>( 1.0,  1.0),
    );
    let arena_half = scene.header.y;
    var center = vec2<f32>(0.0, 0.0);
    var radius = 2.0;
    var is_active = 1.0;

    if (iid < 16u) {
        center = scene.body_pos_vel[iid].xy;
        radius = scene.body_meta[iid].x;
    } else {
        let pid = iid - 16u;
        center = scene.pickups[pid].xy;
        radius = scene.pickups[pid].z;
        is_active = scene.pickups[pid].w;
    }

    var v_out: EntityVaryings;
    v_out.inst_id = iid;
    if (is_active < 0.5) {
        v_out.clip_pos = vec4<f32>(4.0, 4.0, 0.0, 1.0);
        return v_out;
    }

    let ext = radius * 1.85;
    let world_pt = center + corners[vi] * ext;
    v_out.clip_pos = vec4<f32>(world_pt.x / arena_half, world_pt.y / arena_half, 0.0, 1.0);
    return v_out;
}

@fragment
fn fs_entity(v_in: EntityVaryings) -> @location(0) vec4<f32> {
    let arena_half = scene.header.y;
    let phase = scene.header.x;
    let wx = (v_in.clip_pos.x / 512.0 * 2.0 - 1.0) * arena_half;
    let wy = (1.0 - v_in.clip_pos.y / 512.0 * 2.0) * arena_half;
    let iid = v_in.inst_id;

    if (iid < 16u) {
        let center = scene.body_pos_vel[iid].xy;
        let bmeta = scene.body_meta[iid];
        let radius = bmeta.x;
        let fsm = i32(bmeta.y + 0.5);
        let tier = bmeta.z * 0.06;

        var base_col = vec3<f32>(0.06 + tier, 0.80 - tier * 0.4, 0.66 + tier * 0.3);
        if (fsm == 1) {
            base_col = vec3<f32>(0.96, 0.62 + tier * 0.4, 0.10);
        } else if (fsm == 2) {
            base_col = vec3<f32>(0.36 + tier * 0.3, 0.62, 0.96);
        }

        let delta = vec2<f32>(wx - center.x, wy - center.y);
        let dist = sqrt(delta.x * delta.x + delta.y * delta.y);
        let u = dist / radius;

        let halo_env = clamp((1.75 - u) / 0.75, 0.0, 1.0);
        let halo_wave = 0.5 + 0.5 * sin(dist * 3.14159265 - phase * 2.0);
        let halo_alpha = 0.26 * halo_env * halo_env * halo_wave;
        let halo_col = base_col * 1.15;

        let sphere_cov = clamp((1.0 - u) * (radius * 4.0) + 0.5, 0.0, 1.0);
        let u_c = min(u, 1.0);
        let nz = sqrt(max(0.0001, 1.0 - u_c * u_c));
        let n = normalize(vec3<f32>(delta.x / radius, delta.y / radius, nz));
        let l_dir = normalize(vec3<f32>(-0.45, 0.60, 0.66143783));
        let h_dir = normalize(vec3<f32>(-0.45, 0.60, 1.66143783));

        let ndotl = max(dot(n, l_dir), 0.0);
        let ndoth = max(dot(n, h_dir), 0.0);
        let spec = pow(ndoth, 32.0);
        let one_m_nz = 1.0 - nz;
        let rim = one_m_nz * one_m_nz * one_m_nz;
        let stripe = 0.88 + 0.12 * cos(delta.y * 2.2 + phase);

        let sphere_col = clamp(
            base_col * stripe * (0.22 + 0.78 * ndotl) + vec3<f32>(0.88, 0.94, 1.0) * (0.55 * spec + 0.22 * rim),
            vec3<f32>(0.0),
            vec3<f32>(1.0),
        );

        let out_alpha = sphere_cov + halo_alpha * (1.0 - sphere_cov);
        if (out_alpha <= 0.0005) {
            return vec4<f32>(0.0, 0.0, 0.0, 0.0);
        }
        let premul = sphere_col * sphere_cov + halo_col * halo_alpha * (1.0 - sphere_cov);
        return vec4<f32>(clamp(premul / out_alpha, vec3<f32>(0.0), vec3<f32>(1.0)), out_alpha);
    } else {
        let pid = iid - 16u;
        let pk = scene.pickups[pid];
        let delta = vec2<f32>(wx - pk.x, wy - pk.y);
        let dist2 = delta.x * delta.x + delta.y * delta.y;
        let dist = sqrt(dist2);
        let r_ring = pk.z * 0.75;
        let w_ring = pk.z * 0.22;
        let ring_d = abs(dist - r_ring) - w_ring;
        let ring_cov = clamp(-ring_d * 4.0 + 0.5, 0.0, 1.0);
        let cos2t = (delta.x * delta.x - delta.y * delta.y) / max(dist2, 0.001);
        let cos4t = 2.0 * cos2t * cos2t - 1.0;
        let pulse = 0.78 + 0.22 * cos4t * cos(phase * 2.0);
        let pcol = clamp(vec3<f32>(0.98, 0.76, 0.18) * pulse + vec3<f32>(0.15, 0.20, 0.05), vec3<f32>(0.0), vec3<f32>(1.0));
        return vec4<f32>(pcol, ring_cov * 0.92);
    }
}
