#!/usr/bin/env python3
"""
GE-H4: Form-Encoded Rules vs Idiomatic Unity MonoBehaviour C#, Godot 4 GDScript,
and Bevy-Style Rust ECS Across 17 Named Reference Game Behaviors
(Haunted Jaunt, Survival Shooter, Tanks).

Verifies:
  1. All 17 `.rce` Forms pass `rce check` and `rce test` (`openIE-dev/rce` 1762fb4bb65a).
  2. All 4 implementations (`.rce` Form, Unity `MonoBehaviour` C#, Godot 4 `Node` GDScript,
     Bevy `Component + EventReader + System` Rust ECS) produce bit-identical state transitions
     across 10 deterministic 20-step traces per module (680 verified executions, 0 mismatches).
  3. Audits non-comment/non-blank behavior SLOC (and total SLOC including `intent` examples),
     lexical tokens, and engine-glue boilerplate lines across all 68 module files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from typing import Any

TOKEN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*|\d+|==|!=|<=|>=|\+=|-=|\*=|/=|&&|\|\||->|=>|[{}()\[\].,:;+\-*/%<>!&|^~=@#]"
)


def count_metrics(src: str, lang: str) -> dict[str, int]:
    raw_lines = src.splitlines()
    sloc = 0
    intent_lines = 0
    glue = 0
    in_intent = False
    code_no_comments: list[str] = []
    beh_only: list[str] = []

    for raw in raw_lines:
        s = raw.strip()
        if not s:
            continue
        if lang in ("rce", "gdscript"):
            if s.startswith("#"):
                continue
            code_part = raw.split("#", 1)[0]
        else:
            if s.startswith("//"):
                continue
            code_part = raw.split("//", 1)[0]
        cs = code_part.strip()
        if not cs:
            continue

        if lang == "rce":
            if not raw.startswith((" ", "\t")):
                in_intent = cs.startswith("intent ")
            if in_intent:
                intent_lines += 1
            else:
                sloc += 1
                beh_only.append(cs)
            if cs.startswith(("module ", "state ", "event ")):
                glue += 1
        elif lang == "csharp":
            sloc += 1
            beh_only.append(cs)
            if (
                cs.startswith((
                    "using ", "namespace ", "[Serializable]", "[SerializeField]", "[DisallowMultipleComponent]",
                    "public sealed class ", "public struct ", "public enum ", "public event ",
                    "private readonly Queue", "public void Awake", "public void OnEnable",
                    "public void OnDisable", "public void Enqueue", "public void FixedUpdate",
                ))
                or cs in ("{", "}")
            ):
                glue += 1
        elif lang == "gdscript":
            sloc += 1
            beh_only.append(cs)
            if cs.startswith((
                "extends ", "class_name ", "signal ", "@export ", "var _inbox",
                "func _ready", "func enqueue_command", "func _physics_process",
            )):
                glue += 1
        elif lang == "rust_ecs":
            sloc += 1
            beh_only.append(cs)
            if (
                cs.startswith((
                    "#[derive", "pub struct ", "pub enum ", "impl Default", "fn default()",
                    "pub fn ", "for ev in ", "match *ev",
                ))
                or cs in ("{", "}")
            ):
                glue += 1
        code_no_comments.append(cs)

    total_tokens = sum(len(TOKEN_RE.findall(line)) for line in code_no_comments)
    beh_tokens = sum(len(TOKEN_RE.findall(line)) for line in beh_only)
    return {
        "behavior_sloc": sloc,
        "total_sloc_with_intent": sloc + intent_lines,
        "intent_sloc": intent_lines,
        "behavior_tokens": beh_tokens,
        "total_tokens": total_tokens,
        "glue_lines": glue,
    }


def make_csharp_monobehaviour(
    ns: str,
    cls: str,
    fields: list[tuple[str, int]],
    events: list[tuple[str, list[str]]],
    methods_body: str,
    switch_arms: str,
) -> str:
    ev_kinds = ", ".join(e[0] for e in events)
    all_params: list[str] = []
    for _, ps in events:
        for p in ps:
            if p not in all_params:
                all_params.append(p)
    cmd_fields = "\n".join(f"        public long {p};" for p in all_params)
    fld_decls = "\n".join(f"        [SerializeField] public long {fn} = {iv};" for fn, iv in fields)
    reset_assigns = "\n".join(f"            {fn} = {iv};" for fn, iv in fields)
    enq_helpers = []
    for ename, ps in events:
        sig = ", ".join(f"long {p}" for p in ps)
        inits = ", ".join([f"Kind = CmdKind.{ename}"] + [f"{p} = {p}" for p in ps])
        enq_helpers.append(
            f"        public void Enqueue{ename}({sig})\n"
            f"        {{\n"
            f"            _inbox.Enqueue(new Command {{ {inits} }});\n"
            f"        }}"
        )
    enq_str = "\n\n".join(enq_helpers)
    return f"""\
using System;
using System.Collections.Generic;
using UnityEngine;

namespace {ns}
{{
    [DisallowMultipleComponent]
    public sealed class {cls} : MonoBehaviour
    {{
        public enum CmdKind {{ {ev_kinds} }}

        public struct Command
        {{
            public CmdKind Kind;
{cmd_fields}
        }}

{fld_decls}

        public event Action<{cls}> OnStateCommitted;
        private readonly Queue<Command> _inbox = new Queue<Command>();

        public void Awake()
        {{
{reset_assigns}
            _inbox.Clear();
        }}

        public void OnEnable()
        {{
            _inbox.Clear();
        }}

        public void OnDisable()
        {{
            _inbox.Clear();
        }}

{enq_str}

        public void FixedUpdate()
        {{
            while (_inbox.Count > 0)
            {{
                Command cmd = _inbox.Dequeue();
                switch (cmd.Kind)
                {{
{switch_arms}
                }}
                if (OnStateCommitted != null) OnStateCommitted(this);
            }}
        }}

{methods_body}    }}
}}
"""


def make_gdscript_node(
    cls_name: str,
    fields: list[tuple[str, int]],
    dispatch_arms: str,
    methods_body: str,
) -> str:
    fld_decls = "\n".join(f"@export var {fn}: int = {iv}" for fn, iv in fields)
    reset_assigns = "\n".join(f"\t{fn} = {iv}" for fn, iv in fields)
    return f"""\
extends Node
class_name {cls_name}

signal state_committed

{fld_decls}
var _inbox: Array[Dictionary] = []

func _ready() -> void:
{reset_assigns}
\t_inbox.clear()

func enqueue_command(cmd: Dictionary) -> void:
\t_inbox.append(cmd)

func _physics_process(_delta: float) -> void:
\twhile _inbox.size() > 0:
\t\tvar cmd: Dictionary = _inbox.pop_front()
{dispatch_arms}
\t\tstate_committed.emit()

{methods_body}"""


def make_bevy_ecs(
    comp_name: str,
    ev_name: str,
    sys_name: str,
    fields: list[tuple[str, int]],
    events: list[tuple[str, list[str]]],
    arms_body: str,
    helpers_body: str = "",
) -> str:
    fld_decls = "\n".join(f"    pub {fn}: i64," for fn, _ in fields)
    def_inits = "\n".join(f"            {fn}: {iv}," for fn, iv in fields)
    ev_vars = []
    for ename, ps in events:
        if not ps:
            ev_vars.append(f"    {ename},")
        else:
            pstr = ", ".join(f"{p}: i64" for p in ps)
            ev_vars.append(f"    {ename} {{ {pstr} }},")
    ev_str = "\n".join(ev_vars)
    h_block = f"\n{helpers_body}\n" if helpers_body else "\n"
    return f"""\
#[derive(Clone, Debug)]
pub struct {comp_name} {{
{fld_decls}
}}

impl Default for {comp_name} {{
    fn default() -> Self {{
        Self {{
{def_inits}
        }}
    }}
}}

#[derive(Clone, Debug)]
pub enum {ev_name} {{
{ev_str}
}}
{h_block}pub fn {sys_name}(query: &mut [{comp_name}], events: &[{ev_name}]) {{
    for c in query.iter_mut() {{
        for ev in events.iter() {{
            match *ev {{
{arms_body}            }}
        }}
    }}
}}
"""


MODULES: list[dict[str, Any]] = [
    # ==================== 1. HAUNTED JAUNT (5) ====================
    {
        "id": "hj_01_player_stealth",
        "game": "Haunted Jaunt",
        "name": "PlayerStealth",
        "fields": [("x", 0), ("y", 0), ("noise", 0), ("crouching", 0), ("caught", 0)],
        "events": [("Move", ["dx", "dy", "crouch"]), ("Spotted", [])],
        "rce": """\
module haunted_jaunt.player_stealth

intent "stealth avatar velocity, footstep noise accumulation, and caught latch"
    example Move(dx: 1, dy: 0, crouch: 0) -> x == 6 and noise == 4
    example Spotted, Move(dx: 1, dy: 1, crouch: 0) -> x == 0 and caught == 1

fn clamp_i(v: i64, lo: i64, hi: i64) -> i64 = if v < lo then lo else (if v > hi then hi else v)

state PlayerStealth
    x: i64 = 0
    y: i64 = 0
    noise: i64 = 0
    crouching: i64 = 0
    caught: i64 = 0

event Move(dx: i64, dy: i64, crouch: i64)
event Spotted

step PlayerStealth on Move(dx: dx, dy: dy, crouch: cr) if caught == 0
    crouching = cr
    let spd = if cr == 1 then 3 else 6
    x = clamp_i(x + dx * spd, -200, 200)
    y = clamp_i(y + dy * spd, -200, 200)
    let delta_n = if dx != 0 or dy != 0 then (if cr == 1 then 1 else 4) else -3
    noise = clamp_i(noise + delta_n, 0, 100)

step PlayerStealth on Spotted
    caught = 1
    noise = 0
""",
        "csharp": make_csharp_monobehaviour(
            "HauntedJaunt",
            "PlayerStealthBehaviour",
            [("x", 0), ("y", 0), ("noise", 0), ("crouching", 0), ("caught", 0)],
            [("Move", ["dx", "dy", "crouch"]), ("Spotted", [])],
            """        private static long ClampI(long v, long lo, long hi)
        {
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }

        private void ApplyMove(long dx, long dy, long cr)
        {
            if (caught != 0) return;
            crouching = cr;
            long spd = (cr == 1) ? 3 : 6;
            x = ClampI(x + dx * spd, -200, 200);
            y = ClampI(y + dy * spd, -200, 200);
            long deltaN = (dx != 0 || dy != 0) ? ((cr == 1) ? 1 : 4) : -3;
            noise = ClampI(noise + deltaN, 0, 100);
        }

        private void ApplySpotted()
        {
            caught = 1;
            noise = 0;
        }
""",
            """                    case CmdKind.Move:
                        ApplyMove(cmd.dx, cmd.dy, cmd.crouch);
                        break;
                    case CmdKind.Spotted:
                        ApplySpotted();
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "PlayerStealthNode",
            [("x", 0), ("y", 0), ("noise", 0), ("crouching", 0), ("caught", 0)],
            """\t\tif cmd["type"] == "Move":
\t\t\t_apply_move(int(cmd["dx"]), int(cmd["dy"]), int(cmd["crouch"]))
\t\telif cmd["type"] == "Spotted":
\t\t\t_apply_spotted()""",
            """func _clamp_i(v: int, lo: int, hi: int) -> int:
\tif v < lo:
\t\treturn lo
\tif v > hi:
\t\treturn hi
\treturn v

func _apply_move(dx: int, dy: int, cr: int) -> void:
\tif caught != 0:
\t\treturn
\tcrouching = cr
\tvar spd: int = 3 if cr == 1 else 6
\tx = _clamp_i(x + dx * spd, -200, 200)
\ty = _clamp_i(y + dy * spd, -200, 200)
\tvar dn: int = (1 if cr == 1 else 4) if (dx != 0 or dy != 0) else -3
\tnoise = _clamp_i(noise + dn, 0, 100)

func _apply_spotted() -> void:
\tcaught = 1
\tnoise = 0
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "PlayerStealthComp",
            "PlayerStealthEvent",
            "player_stealth_system",
            [("x", 0), ("y", 0), ("noise", 0), ("crouching", 0), ("caught", 0)],
            [("Move", ["dx", "dy", "crouch"]), ("Spotted", [])],
            """                PlayerStealthEvent::Move { dx, dy, crouch } => {
                    if c.caught == 0 {
                        c.crouching = crouch;
                        let spd = if crouch == 1 { 3 } else { 6 };
                        c.x = clamp_i(c.x + dx * spd, -200, 200);
                        c.y = clamp_i(c.y + dy * spd, -200, 200);
                        let dn = if dx != 0 || dy != 0 {
                            if crouch == 1 { 1 } else { 4 }
                        } else {
                            -3
                        };
                        c.noise = clamp_i(c.noise + dn, 0, 100);
                    }
                }
                PlayerStealthEvent::Spotted => {
                    c.caught = 1;
                    c.noise = 0;
                }
""",
            "fn clamp_i(v: i64, lo: i64, hi: i64) -> i64 {\n    if v < lo { lo } else if v > hi { hi } else { v }\n}",
        ),
        "gen_event": lambda rng, step: (
            {"type": "Spotted"} if step == 17 and rng.random() < 0.35
            else {"type": "Move", "dx": rng.choice([-1, 0, 1]), "dy": rng.choice([-1, 0, 1]), "crouch": rng.choice([0, 1])}
        ),
    },
    {
        "id": "hj_02_ghost_patrol",
        "game": "Haunted Jaunt",
        "name": "GhostPatrol",
        "fields": [("gx", -40), ("gy", 0), ("wp", 0), ("alert_ticks", 0)],
        "events": [("PatrolTick", ["px", "py", "noise"])],
        "rce": """\
module haunted_jaunt.ghost_patrol

intent "cyclic waypoint patrol with noise-triggered pursuit diversion"
    example PatrolTick(px: 10, py: 0, noise: 60) -> alert_ticks == 8 and gx == -35
    example PatrolTick(px: 0, py: 0, noise: 10) -> alert_ticks == 0 and gx == -36

fn toward(c: i64, t: i64, s: i64) -> i64 = if c + s < t then c + s else (if c - s > t then c - s else t)

state GhostPatrol
    gx: i64 = -40
    gy: i64 = 0
    wp: i64 = 0
    alert_ticks: i64 = 0

event PatrolTick(px: i64, py: i64, noise: i64)

step GhostPatrol on PatrolTick(px: px, py: py, noise: ns)
    alert_ticks = if ns >= 50 then 8 else (if alert_ticks > 0 then alert_ticks - 1 else 0)
    if alert_ticks > 0
        gx = toward(gx, px, 5)
        gy = toward(gy, py, 5)
    else
        let tx = if wp == 0 or wp == 1 then 40 else -40
        let ty = if wp == 1 or wp == 2 then 30 else 0
        gx = toward(gx, tx, 4)
        gy = toward(gy, ty, 4)
        if gx == tx and gy == ty
            wp = (wp + 1) % 4
""",
        "csharp": make_csharp_monobehaviour(
            "HauntedJaunt",
            "GhostPatrolBehaviour",
            [("gx", -40), ("gy", 0), ("wp", 0), ("alert_ticks", 0)],
            [("PatrolTick", ["px", "py", "noise"])],
            """        private static long StepToward(long cur, long tgt, long spd)
        {
            if (cur + spd < tgt) return cur + spd;
            if (cur - spd > tgt) return cur - spd;
            return tgt;
        }

        private void ApplyPatrolTick(long px, long py, long ns)
        {
            if (ns >= 50) alert_ticks = 8;
            else if (alert_ticks > 0) alert_ticks -= 1;

            if (alert_ticks > 0)
            {
                gx = StepToward(gx, px, 5);
                gy = StepToward(gy, py, 5);
            }
            else
            {
                long tx = (wp == 0 || wp == 1) ? 40 : -40;
                long ty = (wp == 1 || wp == 2) ? 30 : 0;
                gx = StepToward(gx, tx, 4);
                gy = StepToward(gy, ty, 4);
                if (gx == tx && gy == ty) wp = (wp + 1) % 4;
            }
        }
""",
            """                    case CmdKind.PatrolTick:
                        ApplyPatrolTick(cmd.px, cmd.py, cmd.noise);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "GhostPatrolNode",
            [("gx", -40), ("gy", 0), ("wp", 0), ("alert_ticks", 0)],
            """\t\tif cmd["type"] == "PatrolTick":
\t\t\t_apply_patrol(int(cmd["px"]), int(cmd["py"]), int(cmd["noise"]))""",
            """func _toward(cur: int, tgt: int, spd: int) -> int:
\tif cur + spd < tgt:
\t\treturn cur + spd
\tif cur - spd > tgt:
\t\treturn cur - spd
\treturn tgt

func _apply_patrol(px: int, py: int, ns: int) -> void:
\tif ns >= 50:
\t\talert_ticks = 8
\telif alert_ticks > 0:
\t\talert_ticks -= 1
\tif alert_ticks > 0:
\t\tgx = _toward(gx, px, 5)
\t\tgy = _toward(gy, py, 5)
\telse:
\t\tvar tx: int = 40 if (wp == 0 or wp == 1) else -40
\t\tvar ty: int = 30 if (wp == 1 or wp == 2) else 0
\t\tgx = _toward(gx, tx, 4)
\t\tgy = _toward(gy, ty, 4)
\t\tif gx == tx and gy == ty:
\t\t\twp = (wp + 1) % 4
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "GhostPatrolComp",
            "GhostPatrolEvent",
            "ghost_patrol_system",
            [("gx", -40), ("gy", 0), ("wp", 0), ("alert_ticks", 0)],
            [("PatrolTick", ["px", "py", "noise"])],
            """                GhostPatrolEvent::PatrolTick { px, py, noise } => {
                    if noise >= 50 {
                        c.alert_ticks = 8;
                    } else if c.alert_ticks > 0 {
                        c.alert_ticks -= 1;
                    }
                    if c.alert_ticks > 0 {
                        c.gx = step_toward(c.gx, px, 5);
                        c.gy = step_toward(c.gy, py, 5);
                    } else {
                        let tx = if c.wp == 0 || c.wp == 1 { 40 } else { -40 };
                        let ty = if c.wp == 1 || c.wp == 2 { 30 } else { 0 };
                        c.gx = step_toward(c.gx, tx, 4);
                        c.gy = step_toward(c.gy, ty, 4);
                        if c.gx == tx && c.gy == ty {
                            c.wp = (c.wp + 1) % 4;
                        }
                    }
                }
""",
            "fn step_toward(cur: i64, tgt: i64, spd: i64) -> i64 {\n    if cur + spd < tgt { cur + spd } else if cur - spd > tgt { cur - spd } else { tgt }\n}",
        ),
        "gen_event": lambda rng, _s: {"type": "PatrolTick", "px": rng.randint(-50, 50), "py": rng.randint(-20, 40), "noise": rng.choice([0, 20, 45, 65])},
    },
    {
        "id": "hj_03_gargoyle_spotter",
        "game": "Haunted Jaunt",
        "name": "GargoyleSpotter",
        "fields": [("angle", 0), ("dir", 1), ("meter", 0), ("alarm", 0)],
        "events": [("ScanStep", ["target_angle", "dist", "crouched"])],
        "rce": """\
module haunted_jaunt.gargoyle_spotter

intent "oscillating spotlight cone and detection meter accumulator"
    example ScanStep(target_angle: 6, dist: 12, crouched: 0) -> angle == 5 and meter == 8
    example ScanStep(target_angle: 40, dist: 50, crouched: 1) -> angle == 5 and meter == 0

fn abs_i(v: i64) -> i64 = if v < 0 then -v else v

state GargoyleSpotter
    angle: i64 = 0
    dir: i64 = 1
    meter: i64 = 0
    alarm: i64 = 0

event ScanStep(target_angle: i64, dist: i64, crouched: i64)

step GargoyleSpotter on ScanStep(target_angle: ta, dist: d, crouched: cr)
    angle += dir * 5
    if angle >= 45
        angle = 45
        dir = -1
    elif angle <= -45
        angle = -45
        dir = 1
    if d <= (if cr == 1 then 18 else 30) and abs_i(ta - angle) <= 12
        meter = if meter + 8 >= 24 then 24 else meter + 8
        if meter == 24
            alarm = 1
    else
        meter = if meter >= 3 then meter - 3 else 0
""",
        "csharp": make_csharp_monobehaviour(
            "HauntedJaunt",
            "GargoyleSpotterBehaviour",
            [("angle", 0), ("dir", 1), ("meter", 0), ("alarm", 0)],
            [("ScanStep", ["target_angle", "dist", "crouched"])],
            """        private void ApplyScanStep(long ta, long d, long cr)
        {
            angle += dir * 5;
            if (angle >= 45) { angle = 45; dir = -1; }
            else if (angle <= -45) { angle = -45; dir = 1; }

            long maxD = (cr == 1) ? 18 : 30;
            if (d <= maxD && Math.Abs(ta - angle) <= 12)
            {
                meter = (meter + 8 >= 24) ? 24 : (meter + 8);
                if (meter == 24) alarm = 1;
            }
            else
            {
                meter = (meter >= 3) ? (meter - 3) : 0;
            }
        }
""",
            """                    case CmdKind.ScanStep:
                        ApplyScanStep(cmd.target_angle, cmd.dist, cmd.crouched);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "GargoyleSpotterNode",
            [("angle", 0), ("dir", 1), ("meter", 0), ("alarm", 0)],
            """\t\tif cmd["type"] == "ScanStep":
\t\t\t_apply_scan(int(cmd["target_angle"]), int(cmd["dist"]), int(cmd["crouched"]))""",
            """func _apply_scan(ta: int, d: int, cr: int) -> void:
\tangle += dir * 5
\tif angle >= 45:
\t\tangle = 45
\t\tdir = -1
\telif angle <= -45:
\t\tangle = -45
\t\tdir = 1
\tvar max_d: int = 18 if cr == 1 else 30
\tif d <= max_d and absi(ta - angle) <= 12:
\t\tmeter = 24 if (meter + 8 >= 24) else (meter + 8)
\t\tif meter == 24:
\t\t\talarm = 1
\telse:
\t\tmeter = (meter - 3) if meter >= 3 else 0
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "GargoyleSpotterComp",
            "GargoyleSpotterEvent",
            "gargoyle_spotter_system",
            [("angle", 0), ("dir", 1), ("meter", 0), ("alarm", 0)],
            [("ScanStep", ["target_angle", "dist", "crouched"])],
            """                GargoyleSpotterEvent::ScanStep { target_angle, dist, crouched } => {
                    c.angle += c.dir * 5;
                    if c.angle >= 45 {
                        c.angle = 45;
                        c.dir = -1;
                    } else if c.angle <= -45 {
                        c.angle = -45;
                        c.dir = 1;
                    }
                    let max_d = if crouched == 1 { 18 } else { 30 };
                    if dist <= max_d && (target_angle - c.angle).abs() <= 12 {
                        c.meter = if c.meter + 8 >= 24 { 24 } else { c.meter + 8 };
                        if c.meter == 24 {
                            c.alarm = 1;
                        }
                    } else {
                        c.meter = if c.meter >= 3 { c.meter - 3 } else { 0 };
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "ScanStep", "target_angle": rng.randint(-30, 30), "dist": rng.randint(8, 35), "crouched": rng.choice([0, 1])},
    },
    {
        "id": "hj_04_observer_los",
        "game": "Haunted Jaunt",
        "name": "ObserverLineOfSight",
        "fields": [("visible", 0), ("streak", 0), ("spotted_count", 0)],
        "events": [("CheckLos", ["dx", "dy", "look_x", "look_y", "wall_blocked"])],
        "rce": """\
module haunted_jaunt.observer_los

intent "cone dot-product and wall-occlusion line-of-sight confirmation"
    example CheckLos(dx: 8, dy: 2, look_x: 10, look_y: 0, wall_blocked: 0) -> visible == 1 and streak == 1
    example CheckLos(dx: 8, dy: 2, look_x: 10, look_y: 0, wall_blocked: 1) -> visible == 0 and streak == 0

state ObserverLineOfSight
    visible: i64 = 0
    streak: i64 = 0
    spotted_count: i64 = 0

event CheckLos(dx: i64, dy: i64, look_x: i64, look_y: i64, wall_blocked: i64)

step ObserverLineOfSight on CheckLos(dx: dx, dy: dy, look_x: lx, look_y: ly, wall_blocked: wb)
    if wb == 0 and (dx * dx + dy * dy) <= 400 and (dx * lx + dy * ly) > 0
        visible = 1
        streak += 1
        if streak == 3
            spotted_count += 1
    else
        visible = 0
        streak = 0
""",
        "csharp": make_csharp_monobehaviour(
            "HauntedJaunt",
            "ObserverLineOfSightBehaviour",
            [("visible", 0), ("streak", 0), ("spotted_count", 0)],
            [("CheckLos", ["dx", "dy", "look_x", "look_y", "wall_blocked"])],
            """        private void ApplyCheckLos(long dx, long dy, long lx, long ly, long wb)
        {
            long dist2 = dx * dx + dy * dy;
            long dot = dx * lx + dy * ly;
            if (wb == 0 && dist2 <= 400 && dot > 0)
            {
                visible = 1;
                streak += 1;
                if (streak == 3) spotted_count += 1;
            }
            else
            {
                visible = 0;
                streak = 0;
            }
        }
""",
            """                    case CmdKind.CheckLos:
                        ApplyCheckLos(cmd.dx, cmd.dy, cmd.look_x, cmd.look_y, cmd.wall_blocked);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "ObserverLineOfSightNode",
            [("visible", 0), ("streak", 0), ("spotted_count", 0)],
            """\t\tif cmd["type"] == "CheckLos":
\t\t\t_apply_los(int(cmd["dx"]), int(cmd["dy"]), int(cmd["look_x"]), int(cmd["look_y"]), int(cmd["wall_blocked"]))""",
            """func _apply_los(dx: int, dy: int, lx: int, ly: int, wb: int) -> void:
\tvar dist2: int = dx * dx + dy * dy
\tvar dot: int = dx * lx + dy * ly
\tif wb == 0 and dist2 <= 400 and dot > 0:
\t\tvisible = 1
\t\tstreak += 1
\t\tif streak == 3:
\t\t\tspotted_count += 1
\telse:
\t\tvisible = 0
\t\tstreak = 0
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "ObserverLosComp",
            "ObserverLosEvent",
            "observer_los_system",
            [("visible", 0), ("streak", 0), ("spotted_count", 0)],
            [("CheckLos", ["dx", "dy", "look_x", "look_y", "wall_blocked"])],
            """                ObserverLosEvent::CheckLos { dx, dy, look_x, look_y, wall_blocked } => {
                    let dist2 = dx * dx + dy * dy;
                    let dot = dx * look_x + dy * look_y;
                    if wall_blocked == 0 && dist2 <= 400 && dot > 0 {
                        c.visible = 1;
                        c.streak += 1;
                        if c.streak == 3 {
                            c.spotted_count += 1;
                        }
                    } else {
                        c.visible = 0;
                        c.streak = 0;
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "CheckLos", "dx": rng.randint(-15, 18), "dy": rng.randint(-12, 12), "look_x": 10, "look_y": 0, "wall_blocked": rng.choice([0, 0, 0, 1])},
    },
    {
        "id": "hj_05_exit_trigger",
        "game": "Haunted Jaunt",
        "name": "ExitTrigger",
        "fields": [("keys", 0), ("unlocked", 0), ("outcome", 0)],
        "events": [("CollectKey", []), ("ReachDoor", ["alarm_active"])],
        "rce": """\
module haunted_jaunt.exit_trigger

intent "keycard gate unlock and mansion exit outcome resolution"
    example CollectKey, CollectKey, ReachDoor(alarm_active: 0) -> unlocked == 1 and outcome == 1
    example CollectKey, ReachDoor(alarm_active: 1) -> outcome == -1

state ExitTrigger
    keys: i64 = 0
    unlocked: i64 = 0
    outcome: i64 = 0

event CollectKey
event ReachDoor(alarm_active: i64)

step ExitTrigger on CollectKey if outcome == 0
    keys += 1
    if keys >= 2
        unlocked = 1

step ExitTrigger on ReachDoor(alarm_active: al) if outcome == 0
    outcome = if al == 1 then -1 else (if unlocked == 1 then 1 else 0)
""",
        "csharp": make_csharp_monobehaviour(
            "HauntedJaunt",
            "ExitTriggerBehaviour",
            [("keys", 0), ("unlocked", 0), ("outcome", 0)],
            [("CollectKey", []), ("ReachDoor", ["alarm_active"])],
            """        private void ApplyCollectKey()
        {
            if (outcome != 0) return;
            keys += 1;
            if (keys >= 2) unlocked = 1;
        }

        private void ApplyReachDoor(long al)
        {
            if (outcome != 0) return;
            if (al == 1) outcome = -1;
            else if (unlocked == 1) outcome = 1;
        }
""",
            """                    case CmdKind.CollectKey:
                        ApplyCollectKey();
                        break;
                    case CmdKind.ReachDoor:
                        ApplyReachDoor(cmd.alarm_active);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "ExitTriggerNode",
            [("keys", 0), ("unlocked", 0), ("outcome", 0)],
            """\t\tif cmd["type"] == "CollectKey":
\t\t\t_apply_key()
\t\telif cmd["type"] == "ReachDoor":
\t\t\t_apply_door(int(cmd["alarm_active"]))""",
            """func _apply_key() -> void:
\tif outcome != 0:
\t\treturn
\tkeys += 1
\tif keys >= 2:
\t\tunlocked = 1

func _apply_door(al: int) -> void:
\tif outcome != 0:
\t\treturn
\tif al == 1:
\t\toutcome = -1
\telif unlocked == 1:
\t\toutcome = 1
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "ExitTriggerComp",
            "ExitTriggerEvent",
            "exit_trigger_system",
            [("keys", 0), ("unlocked", 0), ("outcome", 0)],
            [("CollectKey", []), ("ReachDoor", ["alarm_active"])],
            """                ExitTriggerEvent::CollectKey => {
                    if c.outcome == 0 {
                        c.keys += 1;
                        if c.keys >= 2 {
                            c.unlocked = 1;
                        }
                    }
                }
                ExitTriggerEvent::ReachDoor { alarm_active } => {
                    if c.outcome == 0 {
                        if alarm_active == 1 {
                            c.outcome = -1;
                        } else if c.unlocked == 1 {
                            c.outcome = 1;
                        }
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "CollectKey"} if rng.random() < 0.55 else {"type": "ReachDoor", "alarm_active": rng.choice([0, 0, 1])},
    },

    # ==================== 2. SURVIVAL SHOOTER (7) ====================
    {
        "id": "ss_01_player_avatar",
        "game": "Survival Shooter",
        "name": "PlayerAvatar",
        "fields": [("px", 0), ("py", 0), ("hp", 100), ("dash_cd", 0), ("iframes", 0)],
        "events": [("AvatarTick", ["dx", "dy", "dash"]), ("ContactDamage", ["amount"])],
        "rce": """\
module survival_shooter.player_avatar

intent "arena avatar locomotion, dash burst cooldown, and invulnerability frames"
    example AvatarTick(dx: 1, dy: 0, dash: 1) -> px == 14 and dash_cd == 10
    example ContactDamage(amount: 25), ContactDamage(amount: 25) -> hp == 75 and iframes == 6

fn clamp_a(v: i64, lo: i64, hi: i64) -> i64 = if v < lo then lo else (if v > hi then hi else v)

state PlayerAvatar
    px: i64 = 0
    py: i64 = 0
    hp: i64 = 100
    dash_cd: i64 = 0
    iframes: i64 = 0

event AvatarTick(dx: i64, dy: i64, dash: i64)
event ContactDamage(amount: i64)

step PlayerAvatar on AvatarTick(dx: dx, dy: dy, dash: dsh) if hp > 0
    if iframes > 0
        iframes -= 1
    let burst = dsh == 1 and dash_cd == 0
    let spd = if burst then 14 else 5
    dash_cd = if burst then 10 else (if dash_cd > 0 then dash_cd - 1 else 0)
    px = clamp_a(px + dx * spd, -240, 240)
    py = clamp_a(py + dy * spd, -240, 240)

step PlayerAvatar on ContactDamage(amount: amt) if hp > 0 and iframes == 0
    hp = clamp_a(hp - amt, 0, 100)
    iframes = 6
""",
        "csharp": make_csharp_monobehaviour(
            "SurvivalShooter",
            "PlayerAvatarBehaviour",
            [("px", 0), ("py", 0), ("hp", 100), ("dash_cd", 0), ("iframes", 0)],
            [("AvatarTick", ["dx", "dy", "dash"]), ("ContactDamage", ["amount"])],
            """        private static long ClampA(long v, long lo, long hi)
        {
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }

        private void ApplyAvatarTick(long dx, long dy, long dsh)
        {
            if (hp <= 0) return;
            if (iframes > 0) iframes -= 1;
            long spd = 5;
            if (dsh == 1 && dash_cd == 0)
            {
                spd = 14;
                dash_cd = 10;
            }
            else if (dash_cd > 0)
            {
                dash_cd -= 1;
            }
            px = ClampA(px + dx * spd, -240, 240);
            py = ClampA(py + dy * spd, -240, 240);
        }

        private void ApplyContactDamage(long amt)
        {
            if (hp > 0 && iframes == 0)
            {
                hp = ClampA(hp - amt, 0, 100);
                iframes = 6;
            }
        }
""",
            """                    case CmdKind.AvatarTick:
                        ApplyAvatarTick(cmd.dx, cmd.dy, cmd.dash);
                        break;
                    case CmdKind.ContactDamage:
                        ApplyContactDamage(cmd.amount);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "PlayerAvatarNode",
            [("px", 0), ("py", 0), ("hp", 100), ("dash_cd", 0), ("iframes", 0)],
            """\t\tif cmd["type"] == "AvatarTick":
\t\t\t_apply_tick(int(cmd["dx"]), int(cmd["dy"]), int(cmd["dash"]))
\t\telif cmd["type"] == "ContactDamage":
\t\t\t_apply_damage(int(cmd["amount"]))""",
            """func _clamp_a(v: int, lo: int, hi: int) -> int:
\tif v < lo:
\t\treturn lo
\tif v > hi:
\t\treturn hi
\treturn v

func _apply_tick(dx: int, dy: int, dsh: int) -> void:
\tif hp <= 0:
\t\treturn
\tif iframes > 0:
\t\tiframes -= 1
\tvar spd: int = 5
\tif dsh == 1 and dash_cd == 0:
\t\tspd = 14
\t\tdash_cd = 10
\telif dash_cd > 0:
\t\tdash_cd -= 1
\tpx = _clamp_a(px + dx * spd, -240, 240)
\tpy = _clamp_a(py + dy * spd, -240, 240)

func _apply_damage(amt: int) -> void:
\tif hp > 0 and iframes == 0:
\t\thp = _clamp_a(hp - amt, 0, 100)
\t\tiframes = 6
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "PlayerAvatarComp",
            "PlayerAvatarEvent",
            "player_avatar_system",
            [("px", 0), ("py", 0), ("hp", 100), ("dash_cd", 0), ("iframes", 0)],
            [("AvatarTick", ["dx", "dy", "dash"]), ("ContactDamage", ["amount"])],
            """                PlayerAvatarEvent::AvatarTick { dx, dy, dash } => {
                    if c.hp > 0 {
                        if c.iframes > 0 {
                            c.iframes -= 1;
                        }
                        let spd = if dash == 1 && c.dash_cd == 0 {
                            c.dash_cd = 10;
                            14
                        } else {
                            if c.dash_cd > 0 {
                                c.dash_cd -= 1;
                            }
                            5
                        };
                        c.px = clamp_a(c.px + dx * spd, -240, 240);
                        c.py = clamp_a(c.py + dy * spd, -240, 240);
                    }
                }
                PlayerAvatarEvent::ContactDamage { amount } => {
                    if c.hp > 0 && c.iframes == 0 {
                        c.hp = clamp_a(c.hp - amount, 0, 100);
                        c.iframes = 6;
                    }
                }
""",
            "fn clamp_a(v: i64, lo: i64, hi: i64) -> i64 {\n    if v < lo { lo } else if v > hi { hi } else { v }\n}",
        ),
        "gen_event": lambda rng, _s: (
            {"type": "ContactDamage", "amount": rng.choice([15, 25])} if rng.random() < 0.3
            else {"type": "AvatarTick", "dx": rng.choice([-1, 0, 1]), "dy": rng.choice([-1, 0, 1]), "dash": rng.choice([0, 1])}
        ),
    },
    {
        "id": "ss_02_gun_raycaster",
        "game": "Survival Shooter",
        "name": "GunRaycaster",
        "fields": [("ammo", 12), ("cooldown", 0), ("reload_ticks", 0), ("hits", 0)],
        "events": [("RayStep", ["trigger", "target_dist", "aligned"])],
        "rce": """\
module survival_shooter.gun_raycaster

intent "ammo clip management, reload timer, and integer ray-circle hit check"
    example RayStep(trigger: 1, target_dist: 40, aligned: 1) -> ammo == 11 and hits == 1 and cooldown == 3
    example RayStep(trigger: 1, target_dist: 180, aligned: 1) -> ammo == 11 and hits == 0

state GunRaycaster
    ammo: i64 = 12
    cooldown: i64 = 0
    reload_ticks: i64 = 0
    hits: i64 = 0

event RayStep(trigger: i64, target_dist: i64, aligned: i64)

step GunRaycaster on RayStep(trigger: tr, target_dist: td, aligned: al)
    if reload_ticks > 0
        reload_ticks -= 1
        if reload_ticks == 0
            ammo = 12
    else
        if cooldown > 0
            cooldown -= 1
        if tr == 1 and cooldown == 0
            if ammo == 0
                reload_ticks = 8
            else
                ammo -= 1
                cooldown = 3
                if al == 1 and td <= 120
                    hits += 1
""",
        "csharp": make_csharp_monobehaviour(
            "SurvivalShooter",
            "GunRaycasterBehaviour",
            [("ammo", 12), ("cooldown", 0), ("reload_ticks", 0), ("hits", 0)],
            [("RayStep", ["trigger", "target_dist", "aligned"])],
            """        private void ApplyRayStep(long tr, long td, long al)
        {
            if (reload_ticks > 0)
            {
                reload_ticks -= 1;
                if (reload_ticks == 0) ammo = 12;
                return;
            }
            if (cooldown > 0) cooldown -= 1;
            if (tr == 1 && cooldown == 0)
            {
                if (ammo == 0)
                {
                    reload_ticks = 8;
                }
                else
                {
                    ammo -= 1;
                    cooldown = 3;
                    if (al == 1 && td <= 120) hits += 1;
                }
            }
        }
""",
            """                    case CmdKind.RayStep:
                        ApplyRayStep(cmd.trigger, cmd.target_dist, cmd.aligned);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "GunRaycasterNode",
            [("ammo", 12), ("cooldown", 0), ("reload_ticks", 0), ("hits", 0)],
            """\t\tif cmd["type"] == "RayStep":
\t\t\t_apply_ray(int(cmd["trigger"]), int(cmd["target_dist"]), int(cmd["aligned"]))""",
            """func _apply_ray(tr: int, td: int, al: int) -> void:
\tif reload_ticks > 0:
\t\treload_ticks -= 1
\t\tif reload_ticks == 0:
\t\t\tammo = 12
\t\treturn
\tif cooldown > 0:
\t\tcooldown -= 1
\tif tr == 1 and cooldown == 0:
\t\tif ammo == 0:
\t\t\treload_ticks = 8
\t\telse:
\t\t\tammo -= 1
\t\t\tcooldown = 3
\t\t\tif al == 1 and td <= 120:
\t\t\t\thits += 1
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "GunRaycasterComp",
            "GunRaycasterEvent",
            "gun_raycaster_system",
            [("ammo", 12), ("cooldown", 0), ("reload_ticks", 0), ("hits", 0)],
            [("RayStep", ["trigger", "target_dist", "aligned"])],
            """                GunRaycasterEvent::RayStep { trigger, target_dist, aligned } => {
                    if c.reload_ticks > 0 {
                        c.reload_ticks -= 1;
                        if c.reload_ticks == 0 {
                            c.ammo = 12;
                        }
                    } else {
                        if c.cooldown > 0 {
                            c.cooldown -= 1;
                        }
                        if trigger == 1 && c.cooldown == 0 {
                            if c.ammo == 0 {
                                c.reload_ticks = 8;
                            } else {
                                c.ammo -= 1;
                                c.cooldown = 3;
                                if aligned == 1 && target_dist <= 120 {
                                    c.hits += 1;
                                }
                            }
                        }
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "RayStep", "trigger": rng.choice([0, 1, 1]), "target_dist": rng.randint(20, 160), "aligned": rng.choice([0, 1])},
    },
    {
        "id": "ss_03_zombunny_chaser",
        "game": "Survival Shooter",
        "name": "ZombunnyChaser",
        "fields": [("dist", 60), ("hp", 40), ("cd", 0), ("strikes", 0), ("sink_timer", 0)],
        "events": [("ChaserStep", ["step_in"]), ("TakeHit", ["dmg"])],
        "rce": """\
module survival_shooter.zombunny_chaser

intent "fast melee chaser approach, strike cooldown, and despawn sink timer"
    example ChaserStep(step_in: 8), ChaserStep(step_in: 8) -> dist == 44 and hp == 40
    example TakeHit(dmg: 50), ChaserStep(step_in: 8) -> hp == 0 and sink_timer == 2

state ZombunnyChaser
    dist: i64 = 60
    hp: i64 = 40
    cd: i64 = 0
    strikes: i64 = 0
    sink_timer: i64 = 0

event ChaserStep(step_in: i64)
event TakeHit(dmg: i64)

step ZombunnyChaser on ChaserStep(step_in: si)
    if hp <= 0
        sink_timer = if sink_timer > 0 then sink_timer - 1 else 0
    else
        cd = if cd > 0 then cd - 1 else 0
        dist = if dist > si + 6 then dist - si else 6
        if dist <= 8 and cd == 0
            strikes += 1
            cd = 5

step ZombunnyChaser on TakeHit(dmg: d) if hp > 0
    if hp > d
        hp -= d
    else
        hp = 0
        sink_timer = 3
""",
        "csharp": make_csharp_monobehaviour(
            "SurvivalShooter",
            "ZombunnyChaserBehaviour",
            [("dist", 60), ("hp", 40), ("cd", 0), ("strikes", 0), ("sink_timer", 0)],
            [("ChaserStep", ["step_in"]), ("TakeHit", ["dmg"])],
            """        private void ApplyChaserStep(long si)
        {
            if (hp <= 0)
            {
                if (sink_timer > 0) sink_timer -= 1;
                return;
            }
            if (cd > 0) cd -= 1;
            dist = (dist > si + 6) ? (dist - si) : 6;
            if (dist <= 8 && cd == 0)
            {
                strikes += 1;
                cd = 5;
            }
        }

        private void ApplyTakeHit(long d)
        {
            if (hp <= 0) return;
            if (hp > d) hp -= d;
            else { hp = 0; sink_timer = 3; }
        }
""",
            """                    case CmdKind.ChaserStep:
                        ApplyChaserStep(cmd.step_in);
                        break;
                    case CmdKind.TakeHit:
                        ApplyTakeHit(cmd.dmg);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "ZombunnyChaserNode",
            [("dist", 60), ("hp", 40), ("cd", 0), ("strikes", 0), ("sink_timer", 0)],
            """\t\tif cmd["type"] == "ChaserStep":
\t\t\t_apply_step(int(cmd["step_in"]))
\t\telif cmd["type"] == "TakeHit":
\t\t\t_apply_hit(int(cmd["dmg"]))""",
            """func _apply_step(si: int) -> void:
\tif hp <= 0:
\t\tif sink_timer > 0:
\t\t\tsink_timer -= 1
\t\treturn
\tif cd > 0:
\t\tcd -= 1
\tdist = (dist - si) if (dist > si + 6) else 6
\tif dist <= 8 and cd == 0:
\t\tstrikes += 1
\t\tcd = 5

func _apply_hit(d: int) -> void:
\tif hp <= 0:
\t\treturn
\tif hp > d:
\t\thp -= d
\telse:
\t\thp = 0
\t\tsink_timer = 3
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "ZombunnyChaserComp",
            "ZombunnyChaserEvent",
            "zombunny_chaser_system",
            [("dist", 60), ("hp", 40), ("cd", 0), ("strikes", 0), ("sink_timer", 0)],
            [("ChaserStep", ["step_in"]), ("TakeHit", ["dmg"])],
            """                ZombunnyChaserEvent::ChaserStep { step_in } => {
                    if c.hp <= 0 {
                        if c.sink_timer > 0 {
                            c.sink_timer -= 1;
                        }
                    } else {
                        if c.cd > 0 {
                            c.cd -= 1;
                        }
                        c.dist = if c.dist > step_in + 6 { c.dist - step_in } else { 6 };
                        if c.dist <= 8 && c.cd == 0 {
                            c.strikes += 1;
                            c.cd = 5;
                        }
                    }
                }
                ZombunnyChaserEvent::TakeHit { dmg } => {
                    if c.hp > 0 {
                        if c.hp > dmg {
                            c.hp -= dmg;
                        } else {
                            c.hp = 0;
                            c.sink_timer = 3;
                        }
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "TakeHit", "dmg": rng.choice([12, 20])} if rng.random() < 0.3 else {"type": "ChaserStep", "step_in": rng.choice([5, 8, 10])},
    },
    {
        "id": "ss_04_zombear_bruiser",
        "game": "Survival Shooter",
        "name": "ZomBearBruiser",
        "fields": [("hp", 100), ("armor", 4), ("enraged", 0), ("cleaves", 0)],
        "events": [("BruiserHit", ["raw_dmg"]), ("BruiserTick", ["in_range"])],
        "rce": """\
module survival_shooter.zombear_bruiser

intent "armored bruiser reduction, enrage threshold under 40 hp, and cleave counter"
    example BruiserHit(raw_dmg: 35) -> hp == 69 and enraged == 0
    example BruiserHit(raw_dmg: 70), BruiserTick(in_range: 1) -> hp == 34 and enraged == 1 and cleaves == 2

state ZomBearBruiser
    hp: i64 = 100
    armor: i64 = 4
    enraged: i64 = 0
    cleaves: i64 = 0

event BruiserHit(raw_dmg: i64)
event BruiserTick(in_range: i64)

step ZomBearBruiser on BruiserHit(raw_dmg: rd) if hp > 0
    let eff = if rd > armor then rd - armor else 1
    hp = if hp > eff then hp - eff else 0
    if hp > 0 and hp < 40
        enraged = 1

step ZomBearBruiser on BruiserTick(in_range: ir) if hp > 0 and ir == 1
    cleaves += if enraged == 1 then 2 else 1
""",
        "csharp": make_csharp_monobehaviour(
            "SurvivalShooter",
            "ZomBearBruiserBehaviour",
            [("hp", 100), ("armor", 4), ("enraged", 0), ("cleaves", 0)],
            [("BruiserHit", ["raw_dmg"]), ("BruiserTick", ["in_range"])],
            """        private void ApplyBruiserHit(long rd)
        {
            if (hp <= 0) return;
            long eff = (rd > armor) ? (rd - armor) : 1;
            hp = (hp > eff) ? (hp - eff) : 0;
            if (hp > 0 && hp < 40) enraged = 1;
        }

        private void ApplyBruiserTick(long ir)
        {
            if (hp > 0 && ir == 1)
            {
                cleaves += (enraged == 1) ? 2 : 1;
            }
        }
""",
            """                    case CmdKind.BruiserHit:
                        ApplyBruiserHit(cmd.raw_dmg);
                        break;
                    case CmdKind.BruiserTick:
                        ApplyBruiserTick(cmd.in_range);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "ZomBearBruiserNode",
            [("hp", 100), ("armor", 4), ("enraged", 0), ("cleaves", 0)],
            """\t\tif cmd["type"] == "BruiserHit":
\t\t\t_apply_hit(int(cmd["raw_dmg"]))
\t\telif cmd["type"] == "BruiserTick":
\t\t\t_apply_tick(int(cmd["in_range"]))""",
            """func _apply_hit(rd: int) -> void:
\tif hp <= 0:
\t\treturn
\tvar eff: int = (rd - armor) if rd > armor else 1
\thp = (hp - eff) if hp > eff else 0
\tif hp > 0 and hp < 40:
\t\tenraged = 1

func _apply_tick(ir: int) -> void:
\tif hp > 0 and ir == 1:
\t\tcleaves += 2 if enraged == 1 else 1
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "ZomBearBruiserComp",
            "ZomBearBruiserEvent",
            "zombear_bruiser_system",
            [("hp", 100), ("armor", 4), ("enraged", 0), ("cleaves", 0)],
            [("BruiserHit", ["raw_dmg"]), ("BruiserTick", ["in_range"])],
            """                ZomBearBruiserEvent::BruiserHit { raw_dmg } => {
                    if c.hp > 0 {
                        let eff = if raw_dmg > c.armor { raw_dmg - c.armor } else { 1 };
                        c.hp = if c.hp > eff { c.hp - eff } else { 0 };
                        if c.hp > 0 && c.hp < 40 {
                            c.enraged = 1;
                        }
                    }
                }
                ZomBearBruiserEvent::BruiserTick { in_range } => {
                    if c.hp > 0 && in_range == 1 {
                        c.cleaves += if c.enraged == 1 { 2 } else { 1 };
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "BruiserHit", "raw_dmg": rng.randint(10, 35)} if rng.random() < 0.45 else {"type": "BruiserTick", "in_range": rng.choice([0, 1])},
    },
    {
        "id": "ss_05_hellephant_boss",
        "game": "Survival Shooter",
        "name": "HellephantBoss",
        "fields": [("hp", 300), ("phase", 0), ("timer", 0), ("stomps", 0), ("summons", 0)],
        "events": [("BossTick", []), ("BossDamage", ["dmg"])],
        "rce": """\
module survival_shooter.hellephant_boss

intent "four-phase boss state machine cycling march, telegraph, stomp, and summon"
    example BossTick, BossTick, BossTick -> phase == 1 and timer == 0
    example BossDamage(dmg: 320), BossTick -> hp == 0 and phase == 0

state HellephantBoss
    hp: i64 = 300
    phase: i64 = 0
    timer: i64 = 0
    stomps: i64 = 0
    summons: i64 = 0

event BossTick
event BossDamage(dmg: i64)

step HellephantBoss on BossTick if hp > 0
    timer += 1
    if phase == 0 and timer >= 3
        phase = 1
        timer = 0
    elif phase == 1 and timer >= 2
        phase = 2
        timer = 0
        stomps += 1
    elif phase == 2 and timer >= 2
        phase = if hp <= 180 then 3 else 0
        timer = 0
        if phase == 3
            summons += 2
    elif phase == 3 and timer >= 2
        phase = 0
        timer = 0

step HellephantBoss on BossDamage(dmg: d)
    hp = if hp > d then hp - d else 0
""",
        "csharp": make_csharp_monobehaviour(
            "SurvivalShooter",
            "HellephantBossBehaviour",
            [("hp", 300), ("phase", 0), ("timer", 0), ("stomps", 0), ("summons", 0)],
            [("BossTick", []), ("BossDamage", ["dmg"])],
            """        private void ApplyBossTick()
        {
            if (hp <= 0) return;
            timer += 1;
            if (phase == 0 && timer >= 3) { phase = 1; timer = 0; }
            else if (phase == 1 && timer >= 2) { phase = 2; timer = 0; stomps += 1; }
            else if (phase == 2 && timer >= 2)
            {
                phase = (hp <= 180) ? 3 : 0;
                timer = 0;
                if (phase == 3) summons += 2;
            }
            else if (phase == 3 && timer >= 2) { phase = 0; timer = 0; }
        }

        private void ApplyBossDamage(long d)
        {
            hp = (hp > d) ? (hp - d) : 0;
        }
""",
            """                    case CmdKind.BossTick:
                        ApplyBossTick();
                        break;
                    case CmdKind.BossDamage:
                        ApplyBossDamage(cmd.dmg);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "HellephantBossNode",
            [("hp", 300), ("phase", 0), ("timer", 0), ("stomps", 0), ("summons", 0)],
            """\t\tif cmd["type"] == "BossTick":
\t\t\t_apply_tick()
\t\telif cmd["type"] == "BossDamage":
\t\t\t_apply_dmg(int(cmd["dmg"]))""",
            """func _apply_tick() -> void:
\tif hp <= 0:
\t\treturn
\ttimer += 1
\tif phase == 0 and timer >= 3:
\t\tphase = 1
\t\ttimer = 0
\telif phase == 1 and timer >= 2:
\t\tphase = 2
\t\ttimer = 0
\t\tstomps += 1
\telif phase == 2 and timer >= 2:
\t\tphase = 3 if hp <= 180 else 0
\t\ttimer = 0
\t\tif phase == 3:
\t\t\tsummons += 2
\telif phase == 3 and timer >= 2:
\t\tphase = 0
\t\ttimer = 0

func _apply_dmg(d: int) -> void:
\thp = (hp - d) if hp > d else 0
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "HellephantBossComp",
            "HellephantBossEvent",
            "hellephant_boss_system",
            [("hp", 300), ("phase", 0), ("timer", 0), ("stomps", 0), ("summons", 0)],
            [("BossTick", []), ("BossDamage", ["dmg"])],
            """                HellephantBossEvent::BossTick => {
                    if c.hp > 0 {
                        c.timer += 1;
                        if c.phase == 0 && c.timer >= 3 {
                            c.phase = 1;
                            c.timer = 0;
                        } else if c.phase == 1 && c.timer >= 2 {
                            c.phase = 2;
                            c.timer = 0;
                            c.stomps += 1;
                        } else if c.phase == 2 && c.timer >= 2 {
                            c.phase = if c.hp <= 180 { 3 } else { 0 };
                            c.timer = 0;
                            if c.phase == 3 {
                                c.summons += 2;
                            }
                        } else if c.phase == 3 && c.timer >= 2 {
                            c.phase = 0;
                            c.timer = 0;
                        }
                    }
                }
                HellephantBossEvent::BossDamage { dmg } => {
                    c.hp = if c.hp > dmg { c.hp - dmg } else { 0 };
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "BossDamage", "dmg": rng.choice([25, 45])} if rng.random() < 0.3 else {"type": "BossTick"},
    },
    {
        "id": "ss_06_wave_spawner",
        "game": "Survival Shooter",
        "name": "WaveSpawner",
        "fields": [("wave", 1), ("quota", 6), ("alive", 0), ("rng", 7), ("spawned_total", 0)],
        "events": [("SpawnerTick", []), ("UnitCleared", [])],
        "rce": """\
module survival_shooter.wave_spawner

intent "deterministic LCG wave spawner with active cap and wave escalation"
    example SpawnerTick -> quota == 5 and alive == 1 and spawned_total == 1
    example SpawnerTick, UnitCleared -> quota == 5 and alive == 0

state WaveSpawner
    wave: i64 = 1
    quota: i64 = 6
    alive: i64 = 0
    rng: i64 = 7
    spawned_total: i64 = 0

event SpawnerTick
event UnitCleared

step WaveSpawner on SpawnerTick
    if quota > 0 and alive < 8
        rng = (rng * 1103515245 + 12345) % 2147483648
        quota -= if rng % 5 == 0 and quota >= 2 then 2 else 1
        alive += 1
        spawned_total += 1
    elif quota == 0 and alive == 0
        wave += 1
        quota = 4 + wave * 2

step WaveSpawner on UnitCleared if alive > 0
    alive -= 1
""",
        "csharp": make_csharp_monobehaviour(
            "SurvivalShooter",
            "WaveSpawnerBehaviour",
            [("wave", 1), ("quota", 6), ("alive", 0), ("rng", 7), ("spawned_total", 0)],
            [("SpawnerTick", []), ("UnitCleared", [])],
            """        private void ApplySpawnerTick()
        {
            if (quota > 0 && alive < 8)
            {
                rng = (rng * 1103515245L + 12345L) % 2147483648L;
                long cost = (rng % 5 == 0 && quota >= 2) ? 2 : 1;
                quota -= cost;
                alive += 1;
                spawned_total += 1;
            }
            else if (quota == 0 && alive == 0)
            {
                wave += 1;
                quota = 4 + wave * 2;
            }
        }

        private void ApplyUnitCleared()
        {
            if (alive > 0) alive -= 1;
        }
""",
            """                    case CmdKind.SpawnerTick:
                        ApplySpawnerTick();
                        break;
                    case CmdKind.UnitCleared:
                        ApplyUnitCleared();
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "WaveSpawnerNode",
            [("wave", 1), ("quota", 6), ("alive", 0), ("rng", 7), ("spawned_total", 0)],
            """\t\tif cmd["type"] == "SpawnerTick":
\t\t\t_apply_tick()
\t\telif cmd["type"] == "UnitCleared":
\t\t\t_apply_cleared()""",
            """func _apply_tick() -> void:
\tif quota > 0 and alive < 8:
\t\trng = (rng * 1103515245 + 12345) % 2147483648
\t\tvar cost: int = 2 if (rng % 5 == 0 and quota >= 2) else 1
\t\tquota -= cost
\t\talive += 1
\t\tspawned_total += 1
\telif quota == 0 and alive == 0:
\t\twave += 1
\t\tquota = 4 + wave * 2

func _apply_cleared() -> void:
\tif alive > 0:
\t\talive -= 1
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "WaveSpawnerComp",
            "WaveSpawnerEvent",
            "wave_spawner_system",
            [("wave", 1), ("quota", 6), ("alive", 0), ("rng", 7), ("spawned_total", 0)],
            [("SpawnerTick", []), ("UnitCleared", [])],
            """                WaveSpawnerEvent::SpawnerTick => {
                    if c.quota > 0 && c.alive < 8 {
                        c.rng = (c.rng * 1103515245 + 12345) % 2147483648;
                        let cost = if c.rng % 5 == 0 && c.quota >= 2 { 2 } else { 1 };
                        c.quota -= cost;
                        c.alive += 1;
                        c.spawned_total += 1;
                    } else if c.quota == 0 && c.alive == 0 {
                        c.wave += 1;
                        c.quota = 4 + c.wave * 2;
                    }
                }
                WaveSpawnerEvent::UnitCleared => {
                    if c.alive > 0 {
                        c.alive -= 1;
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "UnitCleared"} if rng.random() < 0.42 else {"type": "SpawnerTick"},
    },
    {
        "id": "ss_07_score_hud",
        "game": "Survival Shooter",
        "name": "ScoreHUD",
        "fields": [("score", 0), ("combo", 1), ("decay_ticks", 0), ("high_score", 50)],
        "events": [("ScoreEvent", ["base_pts"]), ("HudTick", [])],
        "rce": """\
module survival_shooter.score_hud

intent "combo multiplier, streak decay timer, and high-score watermark"
    example ScoreEvent(base_pts: 20), ScoreEvent(base_pts: 30) -> score == 80 and combo == 3 and high_score == 80
    example HudTick -> combo == 1 and score == 0

state ScoreHUD
    score: i64 = 0
    combo: i64 = 1
    decay_ticks: i64 = 0
    high_score: i64 = 50

event ScoreEvent(base_pts: i64)
event HudTick

step ScoreHUD on ScoreEvent(base_pts: bp)
    score += bp * combo
    combo = if combo < 8 then combo + 1 else 8
    decay_ticks = 4
    high_score = if score > high_score then score else high_score

step ScoreHUD on HudTick if decay_ticks > 0
    decay_ticks -= 1
    if decay_ticks == 0
        combo = 1
""",
        "csharp": make_csharp_monobehaviour(
            "SurvivalShooter",
            "ScoreHudBehaviour",
            [("score", 0), ("combo", 1), ("decay_ticks", 0), ("high_score", 50)],
            [("ScoreEvent", ["base_pts"]), ("HudTick", [])],
            """        private void ApplyScoreEvent(long bp)
        {
            score += bp * combo;
            if (combo < 8) combo += 1;
            decay_ticks = 4;
            if (score > high_score) high_score = score;
        }

        private void ApplyHudTick()
        {
            if (decay_ticks > 0)
            {
                decay_ticks -= 1;
                if (decay_ticks == 0) combo = 1;
            }
        }
""",
            """                    case CmdKind.ScoreEvent:
                        ApplyScoreEvent(cmd.base_pts);
                        break;
                    case CmdKind.HudTick:
                        ApplyHudTick();
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "ScoreHudNode",
            [("score", 0), ("combo", 1), ("decay_ticks", 0), ("high_score", 50)],
            """\t\tif cmd["type"] == "ScoreEvent":
\t\t\t_apply_score(int(cmd["base_pts"]))
\t\telif cmd["type"] == "HudTick":
\t\t\t_apply_tick()""",
            """func _apply_score(bp: int) -> void:
\tscore += bp * combo
\tif combo < 8:
\t\tcombo += 1
\tdecay_ticks = 4
\tif score > high_score:
\t\thigh_score = score

func _apply_tick() -> void:
\tif decay_ticks > 0:
\t\tdecay_ticks -= 1
\t\tif decay_ticks == 0:
\t\t\tcombo = 1
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "ScoreHudComp",
            "ScoreHudEvent",
            "score_hud_system",
            [("score", 0), ("combo", 1), ("decay_ticks", 0), ("high_score", 50)],
            [("ScoreEvent", ["base_pts"]), ("HudTick", [])],
            """                ScoreHudEvent::ScoreEvent { base_pts } => {
                    c.score += base_pts * c.combo;
                    if c.combo < 8 {
                        c.combo += 1;
                    }
                    c.decay_ticks = 4;
                    if c.score > c.high_score {
                        c.high_score = c.score;
                    }
                }
                ScoreHudEvent::HudTick => {
                    if c.decay_ticks > 0 {
                        c.decay_ticks -= 1;
                        if c.decay_ticks == 0 {
                            c.combo = 1;
                        }
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "ScoreEvent", "base_pts": rng.choice([10, 20, 35])} if rng.random() < 0.35 else {"type": "HudTick"},
    },

    # ==================== 3. TANKS (5) ====================
    {
        "id": "tk_01_tank_chassis",
        "game": "Tanks",
        "name": "TankChassis",
        "fields": [("pos", 0), ("heading", 0), ("speed", 0), ("fuel", 200)],
        "events": [("DriveStep", ["throttle", "turn"])],
        "rce": """\
module tanks.tank_chassis

intent "differential tank throttle, heading wrap, drag, and fuel consumption"
    example DriveStep(throttle: 2, turn: 15) -> heading == 15 and speed == 7 and fuel == 198
    example DriveStep(throttle: 0, turn: -10) -> heading == 350 and speed == 0 and fuel == 200

fn clamp_t(v: i64, lo: i64, hi: i64) -> i64 = if v < lo then lo else (if v > hi then hi else v)

state TankChassis
    pos: i64 = 0
    heading: i64 = 0
    speed: i64 = 0
    fuel: i64 = 200

event DriveStep(throttle: i64, turn: i64)

step TankChassis on DriveStep(throttle: th, turn: tr)
    let raw_h = (heading + tr) % 360
    heading = if raw_h < 0 then raw_h + 360 else raw_h
    if fuel > 0 and th != 0
        let cost = if th > 0 then th else -th
        fuel = if fuel > cost then fuel - cost else 0
        speed = clamp_t(speed + th * 4, -24, 24)
    speed = (speed * 7) / 8
    pos = clamp_t(pos + speed, -500, 500)
""",
        "csharp": make_csharp_monobehaviour(
            "Tanks",
            "TankChassisBehaviour",
            [("pos", 0), ("heading", 0), ("speed", 0), ("fuel", 200)],
            [("DriveStep", ["throttle", "turn"])],
            """        private static long ClampT(long v, long lo, long hi)
        {
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }

        private void ApplyDriveStep(long th, long tr)
        {
            long rawH = (heading + tr) % 360;
            heading = (rawH < 0) ? (rawH + 360) : rawH;
            if (fuel > 0 && th != 0)
            {
                long cost = Math.Abs(th);
                fuel = (fuel > cost) ? (fuel - cost) : 0;
                speed = ClampT(speed + th * 4, -24, 24);
            }
            speed = (speed * 7) / 8;
            pos = ClampT(pos + speed, -500, 500);
        }
""",
            """                    case CmdKind.DriveStep:
                        ApplyDriveStep(cmd.throttle, cmd.turn);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "TankChassisNode",
            [("pos", 0), ("heading", 0), ("speed", 0), ("fuel", 200)],
            """\t\tif cmd["type"] == "DriveStep":
\t\t\t_apply_drive(int(cmd["throttle"]), int(cmd["turn"]))""",
            """func _clamp_t(v: int, lo: int, hi: int) -> int:
\tif v < lo:
\t\treturn lo
\tif v > hi:
\t\treturn hi
\treturn v

func _idiv(a: int, b: int) -> int:
\t@warning_ignore("integer_division")
\treturn a / b

func _apply_drive(th: int, tr: int) -> void:
\tvar raw_h: int = (heading + tr) % 360
\theading = (raw_h + 360) if raw_h < 0 else raw_h
\tif fuel > 0 and th != 0:
\t\tvar cost: int = absi(th)
\t\tfuel = (fuel - cost) if fuel > cost else 0
\t\tspeed = _clamp_t(speed + th * 4, -24, 24)
\tspeed = _idiv(speed * 7, 8)
\tpos = _clamp_t(pos + speed, -500, 500)
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "TankChassisComp",
            "TankChassisEvent",
            "tank_chassis_system",
            [("pos", 0), ("heading", 0), ("speed", 0), ("fuel", 200)],
            [("DriveStep", ["throttle", "turn"])],
            """                TankChassisEvent::DriveStep { throttle, turn } => {
                    let raw_h = (c.heading + turn) % 360;
                    c.heading = if raw_h < 0 { raw_h + 360 } else { raw_h };
                    if c.fuel > 0 && throttle != 0 {
                        let cost = throttle.abs();
                        c.fuel = if c.fuel > cost { c.fuel - cost } else { 0 };
                        c.speed = clamp_t(c.speed + throttle * 4, -24, 24);
                    }
                    c.speed = (c.speed * 7) / 8;
                    c.pos = clamp_t(c.pos + c.speed, -500, 500);
                }
""",
            "fn clamp_t(v: i64, lo: i64, hi: i64) -> i64 {\n    if v < lo { lo } else if v > hi { hi } else { v }\n}",
        ),
        "gen_event": lambda rng, _s: {"type": "DriveStep", "throttle": rng.choice([-2, -1, 0, 1, 2]), "turn": rng.choice([-20, -10, 0, 10, 25])},
    },
    {
        "id": "tk_02_shell_ballistics_q32",
        "game": "Tanks",
        "name": "ShellBallisticsQ32",
        "fields": [("sx", 0), ("sz", 0), ("vx", 0), ("vz", 0), ("active", 0), ("impacts", 0)],
        "events": [("Launch", ["vx0", "vz0"]), ("StepArc", ["wind"])],
        "rce": """\
module tanks.shell_ballistics_q32

intent "Q32-scaled integer ballistic arc with wind drift and ground contact"
    example Launch(vx0: 40, vz0: 18), StepArc(wind: 2) -> active == 1 and sx == 42 and sz == 12
    example Launch(vx0: 20, vz0: 4), StepArc(wind: 0), StepArc(wind: 0) -> active == 0 and impacts == 1

state ShellBallisticsQ32
    sx: i64 = 0
    sz: i64 = 0
    vx: i64 = 0
    vz: i64 = 0
    active: i64 = 0
    impacts: i64 = 0

event Launch(vx0: i64, vz0: i64)
event StepArc(wind: i64)

step ShellBallisticsQ32 on Launch(vx0: ix, vz0: iz) if active == 0
    sx = 0
    sz = 0
    vx = ix
    vz = iz
    active = 1

step ShellBallisticsQ32 on StepArc(wind: w) if active == 1
    vx += w
    vz -= 6
    sx += vx
    sz += vz
    if sz <= 0
        sz = 0
        active = 0
        impacts += 1
""",
        "csharp": make_csharp_monobehaviour(
            "Tanks",
            "ShellBallisticsQ32Behaviour",
            [("sx", 0), ("sz", 0), ("vx", 0), ("vz", 0), ("active", 0), ("impacts", 0)],
            [("Launch", ["vx0", "vz0"]), ("StepArc", ["wind"])],
            """        private void ApplyLaunch(long ix, long iz)
        {
            if (active == 0)
            {
                sx = 0; sz = 0; vx = ix; vz = iz; active = 1;
            }
        }

        private void ApplyStepArc(long w)
        {
            if (active != 1) return;
            vx += w;
            vz -= 6;
            sx += vx;
            sz += vz;
            if (sz <= 0)
            {
                sz = 0; active = 0; impacts += 1;
            }
        }
""",
            """                    case CmdKind.Launch:
                        ApplyLaunch(cmd.vx0, cmd.vz0);
                        break;
                    case CmdKind.StepArc:
                        ApplyStepArc(cmd.wind);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "ShellBallisticsQ32Node",
            [("sx", 0), ("sz", 0), ("vx", 0), ("vz", 0), ("active", 0), ("impacts", 0)],
            """\t\tif cmd["type"] == "Launch":
\t\t\t_apply_launch(int(cmd["vx0"]), int(cmd["vz0"]))
\t\telif cmd["type"] == "StepArc":
\t\t\t_apply_arc(int(cmd["wind"]))""",
            """func _apply_launch(ix: int, iz: int) -> void:
\tif active == 0:
\t\tsx = 0
\t\tsz = 0
\t\tvx = ix
\t\tvz = iz
\t\tactive = 1

func _apply_arc(w: int) -> void:
\tif active != 1:
\t\treturn
\tvx += w
\tvz -= 6
\tsx += vx
\tsz += vz
\tif sz <= 0:
\t\tsz = 0
\t\tactive = 0
\t\timpacts += 1
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "ShellBallisticsQ32Comp",
            "ShellBallisticsQ32Event",
            "shell_ballistics_q32_system",
            [("sx", 0), ("sz", 0), ("vx", 0), ("vz", 0), ("active", 0), ("impacts", 0)],
            [("Launch", ["vx0", "vz0"]), ("StepArc", ["wind"])],
            """                ShellBallisticsQ32Event::Launch { vx0, vz0 } => {
                    if c.active == 0 {
                        c.sx = 0;
                        c.sz = 0;
                        c.vx = vx0;
                        c.vz = vz0;
                        c.active = 1;
                    }
                }
                ShellBallisticsQ32Event::StepArc { wind } => {
                    if c.active == 1 {
                        c.vx += wind;
                        c.vz -= 6;
                        c.sx += c.vx;
                        c.sz += c.vz;
                        if c.sz <= 0 {
                            c.sz = 0;
                            c.active = 0;
                            c.impacts += 1;
                        }
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "Launch", "vx0": rng.randint(15, 45), "vz0": rng.randint(10, 26)} if rng.random() < 0.35 else {"type": "StepArc", "wind": rng.choice([-2, -1, 0, 1, 2])},
    },
    {
        "id": "tk_03_explosion_falloff",
        "game": "Tanks",
        "name": "ExplosionFalloff",
        "fields": [("last_dmg", 0), ("last_push", 0), ("total_dmg", 0)],
        "events": [("RadialPulse", ["dx", "dy", "peak"])],
        "rce": """\
module tanks.explosion_falloff

intent "quadratic integer radial damage and impulse falloff within radius 10"
    example RadialPulse(dx: 0, dy: 0, peak: 80) -> last_dmg == 80 and last_push == 40
    example RadialPulse(dx: 10, dy: 0, peak: 80) -> last_dmg == 0 and last_push == 0

state ExplosionFalloff
    last_dmg: i64 = 0
    last_push: i64 = 0
    total_dmg: i64 = 0

event RadialPulse(dx: i64, dy: i64, peak: i64)

step ExplosionFalloff on RadialPulse(dx: dx, dy: dy, peak: pk)
    let rem = 100 - (dx * dx + dy * dy)
    last_dmg = if rem > 0 then (pk * rem) / 100 else 0
    last_push = if rem > 0 then ((pk / 2) * rem) / 100 else 0
    total_dmg += last_dmg
""",
        "csharp": make_csharp_monobehaviour(
            "Tanks",
            "ExplosionFalloffBehaviour",
            [("last_dmg", 0), ("last_push", 0), ("total_dmg", 0)],
            [("RadialPulse", ["dx", "dy", "peak"])],
            """        private void ApplyRadialPulse(long dx, long dy, long pk)
        {
            long r2 = dx * dx + dy * dy;
            if (r2 < 100)
            {
                long rem = 100 - r2;
                last_dmg = (pk * rem) / 100;
                last_push = ((pk / 2) * rem) / 100;
                total_dmg += last_dmg;
            }
            else
            {
                last_dmg = 0;
                last_push = 0;
            }
        }
""",
            """                    case CmdKind.RadialPulse:
                        ApplyRadialPulse(cmd.dx, cmd.dy, cmd.peak);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "ExplosionFalloffNode",
            [("last_dmg", 0), ("last_push", 0), ("total_dmg", 0)],
            """\t\tif cmd["type"] == "RadialPulse":
\t\t\t_apply_pulse(int(cmd["dx"]), int(cmd["dy"]), int(cmd["peak"]))""",
            """func _idiv(a: int, b: int) -> int:
\t@warning_ignore("integer_division")
\treturn a / b

func _apply_pulse(dx: int, dy: int, pk: int) -> void:
\tvar r2: int = dx * dx + dy * dy
\tif r2 < 100:
\t\tvar rem: int = 100 - r2
\t\tlast_dmg = _idiv(pk * rem, 100)
\t\tlast_push = _idiv(_idiv(pk, 2) * rem, 100)
\t\ttotal_dmg += last_dmg
\telse:
\t\tlast_dmg = 0
\t\tlast_push = 0
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "ExplosionFalloffComp",
            "ExplosionFalloffEvent",
            "explosion_falloff_system",
            [("last_dmg", 0), ("last_push", 0), ("total_dmg", 0)],
            [("RadialPulse", ["dx", "dy", "peak"])],
            """                ExplosionFalloffEvent::RadialPulse { dx, dy, peak } => {
                    let r2 = dx * dx + dy * dy;
                    if r2 < 100 {
                        let rem = 100 - r2;
                        c.last_dmg = (peak * rem) / 100;
                        c.last_push = ((peak / 2) * rem) / 100;
                        c.total_dmg += c.last_dmg;
                    } else {
                        c.last_dmg = 0;
                        c.last_push = 0;
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "RadialPulse", "dx": rng.randint(-12, 12), "dy": rng.randint(-10, 10), "peak": rng.choice([60, 80, 100])},
    },
    {
        "id": "tk_04_tank_health_shield",
        "game": "Tanks",
        "name": "TankHealthShield",
        "fields": [("hull", 100), ("shield", 40), ("regen_delay", 0), ("knocked_out", 0)],
        "events": [("Impact", ["dmg"]), ("RegenStep", [])],
        "rce": """\
module tanks.tank_health_shield

intent "reactive overshield absorption, recharge delay, and hull knockout"
    example Impact(dmg: 25), RegenStep -> shield == 15 and hull == 100 and regen_delay == 2
    example Impact(dmg: 60) -> shield == 0 and hull == 80 and regen_delay == 3

state TankHealthShield
    hull: i64 = 100
    shield: i64 = 40
    regen_delay: i64 = 0
    knocked_out: i64 = 0

event Impact(dmg: i64)
event RegenStep

step TankHealthShield on Impact(dmg: d) if knocked_out == 0
    regen_delay = 3
    let rem = if d > shield then d - shield else 0
    shield = if shield >= d then shield - d else 0
    hull = if hull > rem then hull - rem else 0
    if hull == 0
        knocked_out = 1

step TankHealthShield on RegenStep if knocked_out == 0
    if regen_delay > 0
        regen_delay -= 1
    elif shield < 40
        shield = if shield + 5 > 40 then 40 else shield + 5
""",
        "csharp": make_csharp_monobehaviour(
            "Tanks",
            "TankHealthShieldBehaviour",
            [("hull", 100), ("shield", 40), ("regen_delay", 0), ("knocked_out", 0)],
            [("Impact", ["dmg"]), ("RegenStep", [])],
            """        private void ApplyImpact(long d)
        {
            if (knocked_out != 0) return;
            regen_delay = 3;
            if (shield >= d)
            {
                shield -= d;
            }
            else
            {
                long rem = d - shield;
                shield = 0;
                hull = (hull > rem) ? (hull - rem) : 0;
                if (hull == 0) knocked_out = 1;
            }
        }

        private void ApplyRegenStep()
        {
            if (knocked_out != 0) return;
            if (regen_delay > 0) regen_delay -= 1;
            else if (shield < 40) shield = (shield + 5 > 40) ? 40 : (shield + 5);
        }
""",
            """                    case CmdKind.Impact:
                        ApplyImpact(cmd.dmg);
                        break;
                    case CmdKind.RegenStep:
                        ApplyRegenStep();
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "TankHealthShieldNode",
            [("hull", 100), ("shield", 40), ("regen_delay", 0), ("knocked_out", 0)],
            """\t\tif cmd["type"] == "Impact":
\t\t\t_apply_impact(int(cmd["dmg"]))
\t\telif cmd["type"] == "RegenStep":
\t\t\t_apply_regen()""",
            """func _apply_impact(d: int) -> void:
\tif knocked_out != 0:
\t\treturn
\tregen_delay = 3
\tif shield >= d:
\t\tshield -= d
\telse:
\t\tvar rem: int = d - shield
\t\tshield = 0
\t\thull = (hull - rem) if hull > rem else 0
\t\tif hull == 0:
\t\t\tknocked_out = 1

func _apply_regen() -> void:
\tif knocked_out != 0:
\t\treturn
\tif regen_delay > 0:
\t\tregen_delay -= 1
\telif shield < 40:
\t\tshield = 40 if (shield + 5 > 40) else (shield + 5)
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "TankHealthShieldComp",
            "TankHealthShieldEvent",
            "tank_health_shield_system",
            [("hull", 100), ("shield", 40), ("regen_delay", 0), ("knocked_out", 0)],
            [("Impact", ["dmg"]), ("RegenStep", [])],
            """                TankHealthShieldEvent::Impact { dmg } => {
                    if c.knocked_out == 0 {
                        c.regen_delay = 3;
                        if c.shield >= dmg {
                            c.shield -= dmg;
                        } else {
                            let rem = dmg - c.shield;
                            c.shield = 0;
                            c.hull = if c.hull > rem { c.hull - rem } else { 0 };
                            if c.hull == 0 {
                                c.knocked_out = 1;
                            }
                        }
                    }
                }
                TankHealthShieldEvent::RegenStep => {
                    if c.knocked_out == 0 {
                        if c.regen_delay > 0 {
                            c.regen_delay -= 1;
                        } else if c.shield < 40 {
                            c.shield = if c.shield + 5 > 40 { 40 } else { c.shield + 5 };
                        }
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "Impact", "dmg": rng.choice([15, 25, 45])} if rng.random() < 0.4 else {"type": "RegenStep"},
    },
    {
        "id": "tk_05_round_director",
        "game": "Tanks",
        "name": "RoundDirector",
        "fields": [("round_no", 1), ("wins_a", 0), ("wins_b", 0), ("draws", 0), ("champion", 0)],
        "events": [("RoundEnd", ["hp_a", "hp_b"])],
        "rce": """\
module tanks.round_director

intent "best-of-five match director with draw tracking and champion lock"
    example RoundEnd(hp_a: 40, hp_b: 0), RoundEnd(hp_a: 10, hp_b: 0), RoundEnd(hp_a: 5, hp_b: 0) -> wins_a == 3 and champion == 1
    example RoundEnd(hp_a: 0, hp_b: 0) -> draws == 1 and round_no == 2 and champion == 0

state RoundDirector
    round_no: i64 = 1
    wins_a: i64 = 0
    wins_b: i64 = 0
    draws: i64 = 0
    champion: i64 = 0

event RoundEnd(hp_a: i64, hp_b: i64)

step RoundDirector on RoundEnd(hp_a: a, hp_b: b) if champion == 0
    wins_a += if a > b then 1 else 0
    wins_b += if b > a then 1 else 0
    draws += if a == b then 1 else 0
    champion = if wins_a >= 3 then 1 else (if wins_b >= 3 then 2 else 0)
    if champion == 0
        round_no += 1
""",
        "csharp": make_csharp_monobehaviour(
            "Tanks",
            "RoundDirectorBehaviour",
            [("round_no", 1), ("wins_a", 0), ("wins_b", 0), ("draws", 0), ("champion", 0)],
            [("RoundEnd", ["hp_a", "hp_b"])],
            """        private void ApplyRoundEnd(long a, long b)
        {
            if (champion != 0) return;
            if (a > b) wins_a += 1;
            else if (b > a) wins_b += 1;
            else draws += 1;

            if (wins_a >= 3) champion = 1;
            else if (wins_b >= 3) champion = 2;
            else round_no += 1;
        }
""",
            """                    case CmdKind.RoundEnd:
                        ApplyRoundEnd(cmd.hp_a, cmd.hp_b);
                        break;""",
        ),
        "gdscript": make_gdscript_node(
            "RoundDirectorNode",
            [("round_no", 1), ("wins_a", 0), ("wins_b", 0), ("draws", 0), ("champion", 0)],
            """\t\tif cmd["type"] == "RoundEnd":
\t\t\t_apply_round(int(cmd["hp_a"]), int(cmd["hp_b"]))""",
            """func _apply_round(a: int, b: int) -> void:
\tif champion != 0:
\t\treturn
\tif a > b:
\t\twins_a += 1
\telif b > a:
\t\twins_b += 1
\telse:
\t\tdraws += 1
\tif wins_a >= 3:
\t\tchampion = 1
\telif wins_b >= 3:
\t\tchampion = 2
\telse:
\t\tround_no += 1
""",
        ),
        "rust_ecs": make_bevy_ecs(
            "RoundDirectorComp",
            "RoundDirectorEvent",
            "round_director_system",
            [("round_no", 1), ("wins_a", 0), ("wins_b", 0), ("draws", 0), ("champion", 0)],
            [("RoundEnd", ["hp_a", "hp_b"])],
            """                RoundDirectorEvent::RoundEnd { hp_a, hp_b } => {
                    if c.champion == 0 {
                        if hp_a > hp_b {
                            c.wins_a += 1;
                        } else if hp_b > hp_a {
                            c.wins_b += 1;
                        } else {
                            c.draws += 1;
                        }
                        if c.wins_a >= 3 {
                            c.champion = 1;
                        } else if c.wins_b >= 3 {
                            c.champion = 2;
                        } else {
                            c.round_no += 1;
                        }
                    }
                }
""",
        ),
        "gen_event": lambda rng, _s: {"type": "RoundEnd", "hp_a": rng.choice([0, 20, 55]), "hp_b": rng.choice([0, 20, 55])},
    },
]


def generate_traces() -> dict[str, list[list[dict[str, Any]]]]:
    import random
    rng = random.Random(2026112304)
    return {
        m["id"]: [[m["gen_event"](rng, step) for step in range(20)] for _ in range(10)]
        for m in MODULES
    }


def run_rce_traces(rce_bin: str, rce_dir: pathlib.Path, work: pathlib.Path, traces: dict[str, list[list[dict[str, Any]]]]) -> dict[str, list[str]]:
    out_hashes: dict[str, list[str]] = {}
    for idx, m in enumerate(MODULES):
        mid = m["id"]
        rce_file = rce_dir / f"{mid}.rce"
        subprocess.run([rce_bin, "check", str(rce_file)], check=True, capture_output=True)
        subprocess.run([rce_bin, "test", str(rce_file)], check=True, capture_output=True)
        py_code = subprocess.check_output([rce_bin, "emit", "python", str(rce_file)], text=True)
        mod_py = work / f"rce_mod_{idx}.py"
        mod_py.write_text(py_code, encoding="utf-8")

        driver = work / f"run_rce_{idx}.py"
        driver.write_text(f"""\
import hashlib, importlib.util, json
spec = importlib.util.spec_from_file_location("rmod", {str(mod_py)!r})
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)
traces = json.loads(open({str(work / f'traces_{mid}.json')!r}).read())
hashes = []
for seq in traces:
    rm.fuel_reset()
    s = rm.initial_state()
    for ev in seq:
        rm.fuel_reset()
        et = ev["type"]
        fspec = [(fn, ("int", "i64"), None) for fn, _ in rm.EVENT_FIELDS[et]]
        fvals = [(fn, rm.lit(int(ev[fn]))) for fn, _ in rm.EVENT_FIELDS[et]]
        eobj = rm.construct(et, fspec, fvals)
        s, _ = rm.delta(s, eobj)
    flds = {{k: v.v for k, v in s[0][1]}}
    canon = json.dumps(flds, sort_keys=True, separators=(",", ":"))
    hashes.append(hashlib.sha256(canon.encode()).hexdigest())
print(json.dumps(hashes))
""", encoding="utf-8")
        (work / f"traces_{mid}.json").write_text(json.dumps(traces[mid]), encoding="utf-8")
        out_hashes[mid] = json.loads(subprocess.check_output([sys.executable, str(driver)], text=True))
    return out_hashes


def run_godot_traces(godot_bin: str, work: pathlib.Path, traces: dict[str, list[list[dict[str, Any]]]]) -> dict[str, list[str]]:
    gd_dir = work / "gd_h4"
    gd_dir.mkdir(parents=True, exist_ok=True)
    for m in MODULES:
        lines = [ln for ln in m["gdscript"].splitlines() if not ln.strip().startswith("class_name ")]
        (gd_dir / f"{m['id']}.gd").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (gd_dir / "all_traces.json").write_text(json.dumps(traces), encoding="utf-8")
    runner_lines = [
        "extends SceneTree",
        "func _canon(d: Dictionary) -> String:",
        "\tvar ks: Array = d.keys()",
        "\tks.sort()",
        "\tvar parts: Array[String] = []",
        "\tfor k in ks:",
        '\t\tparts.append("\\"" + str(k) + "\\":" + str(int(d[k])))',
        '\treturn "{" + ",".join(parts) + "}"',
        "func _init() -> void:",
        f'\tvar all_t: Dictionary = JSON.parse_string(FileAccess.get_file_as_string({str(gd_dir / "all_traces.json")!r}))',
        "\tvar out: Dictionary = {}",
    ]
    for m in MODULES:
        mid = m["id"]
        fdict = ", ".join(f'"{fn}": inst.{fn}' for fn, _ in m["fields"])
        runner_lines.extend([
            f'\tvar scr_{mid} = load({str(gd_dir / f"{mid}.gd")!r})',
            f'\tvar h_{mid}: Array[String] = []',
            f'\tfor seq in all_t["{mid}"]:',
            f'\t\tvar inst = scr_{mid}.new()',
            '\t\tinst._ready()',
            '\t\tfor ev in seq:',
            '\t\t\tinst.enqueue_command(ev)',
            '\t\t\tinst._physics_process(1.0 / 60.0)',
            f'\t\th_{mid}.append(_canon({{{fdict}}}).sha256_text())',
            '\t\tinst.free()',
            f'\tout["{mid}"] = h_{mid}',
        ])
    out_file = gd_dir / "gd_out.json"
    runner_lines.extend([
        f'\tvar f = FileAccess.open({str(out_file)!r}, FileAccess.WRITE)',
        '\tf.store_string(JSON.stringify(out))',
        '\tf.close()',
        '\tquit(0)',
    ])
    runner_gd = gd_dir / "run_all_h4.gd"
    runner_gd.write_text("\n".join(runner_lines) + "\n", encoding="utf-8")
    subprocess.run([godot_bin, "--headless", "-s", str(runner_gd)], check=True, capture_output=True)
    return json.loads(out_file.read_text(encoding="utf-8"))


def build_rust_and_csharp_bundles(work: pathlib.Path, traces: dict[str, list[list[dict[str, Any]]]]) -> tuple[pathlib.Path, pathlib.Path]:
    rs_lines = ["// Auto-generated GE-H4 Bevy-style Rust ECS trace verifier"]
    for m in MODULES:
        rs_lines.append(m["rust_ecs"])
    rs_lines.append("fn main() {")
    rs_lines.append("    println!(\"{{\");")
    for idx, m in enumerate(MODULES):
        mid = m["id"]
        comp_ty = re.search(r"pub struct (\w+)", m["rust_ecs"]).group(1)
        sys_fn = re.search(r"pub fn (\w+)", m["rust_ecs"]).group(1)
        ev_ty = re.search(r"pub enum (\w+)", m["rust_ecs"]).group(1)
        rs_lines.append(f"    print!(\"  \\\"{mid}\\\": [\");")
        for tidx, seq in enumerate(traces[mid]):
            rs_lines.append(f"    {{ let mut world = [{comp_ty}::default()];")
            for ev in seq:
                et = ev["type"]
                args = [k for k in ev.keys() if k != "type"]
                if not args:
                    rs_lines.append(f"      {sys_fn}(&mut world, &[{ev_ty}::{et}]);")
                else:
                    astr = ", ".join(f"{k}: {int(ev[k])}" for k in args)
                    rs_lines.append(f"      {sys_fn}(&mut world, &[{ev_ty}::{et} {{ {astr} }}]);")
            sorted_flds = sorted(f[0] for f in m["fields"])
            fmt_str = "{{" + ",".join(f'\\"{fn}\\":{{}}' for fn in sorted_flds) + "}}"
            fmt_args = ", ".join(f"world[0].{fn}" for fn in sorted_flds)
            sep = "," if tidx < 9 else ""
            rs_lines.append(f"      let s = format!(\"{fmt_str}\", {fmt_args});")
            rs_lines.append(f"      print!(\"{{:?}}{sep}\", s); }}")
        msep = "," if idx + 1 < len(MODULES) else ""
        rs_lines.append(f"    println!(\"]{msep}\");")
    rs_lines.append("    println!(\"}}\");")
    rs_lines.append("}")
    rs_path = work / "verify_h4_rust_ecs.rs"
    rs_path.write_text("\n".join(rs_lines) + "\n", encoding="utf-8")

    # C# standalone verifier with lightweight UnityEngine MonoBehaviour shim for `csc.exe`
    cs_lines = [
        "using System;",
        "using System.Collections.Generic;",
        "using UnityEngine;",
        "namespace UnityEngine {",
        "  public class MonoBehaviour {}",
        "  [AttributeUsage(AttributeTargets.Field)] public class SerializeField : Attribute {}",
        "  [AttributeUsage(AttributeTargets.Class)] public class DisallowMultipleComponent : Attribute {}",
        "}",
    ]
    for m in MODULES:
        body = "\n".join(
            ln for ln in m["csharp"].splitlines()
            if not ln.strip().startswith(("using System;", "using System.Collections.Generic;", "using UnityEngine;"))
        )
        cs_lines.append(body)

    cs_lines.append("public class Program { public static void Main() {")
    cs_lines.append("    Console.WriteLine(\"{\");")
    for idx, m in enumerate(MODULES):
        mid = m["id"]
        ns_name = re.search(r"namespace (\w+)", m["csharp"]).group(1)
        cls_name = re.search(r"public sealed class (\w+)", m["csharp"]).group(1)
        ev_map = {ename: ps for ename, ps in m["events"]}
        cs_lines.append(f'    Console.Write("  \\"{mid}\\": [");')
        for tidx, seq in enumerate(traces[mid]):
            cs_lines.append(f"    {{ var b = new {ns_name}.{cls_name}(); b.Awake(); b.OnEnable();")
            for ev in seq:
                et = ev["type"]
                arg_vals = ", ".join(f"{int(ev[p])}L" for p in ev_map[et])
                cs_lines.append(f"      b.Enqueue{et}({arg_vals}); b.FixedUpdate();")
            sorted_flds = sorted(f[0] for f in m["fields"])
            parts = " + \",\" + ".join(f'"\\"{fn}\\":" + b.{fn}' for fn in sorted_flds)
            sep = "," if tidx < 9 else ""
            cs_lines.append(f'      string s = "{{" + {parts} + "}}";')
            cs_lines.append(f'      Console.Write("\\"" + s.Replace("\\"", "\\\\\\"") + "\\"{sep}"); }}')
        msep = "," if idx + 1 < len(MODULES) else ""
        cs_lines.append(f'    Console.WriteLine("]{msep}");')
    cs_lines.append("    Console.WriteLine(\"}\");")
    cs_lines.append("} }")
    cs_path = work / "verify_h4_csharp.cs"
    cs_path.write_text("\n".join(cs_lines) + "\n", encoding="utf-8")
    return rs_path, cs_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-forms-dir", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--rce", default="")
    ap.add_argument("--godot", default="")
    ap.add_argument("--rustc", default="rustc")
    ap.add_argument("--csharp-json", default="")
    ap.add_argument("--emit-cs-only", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    forms_dir = pathlib.Path(args.export_forms_dir)
    forms_dir.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    for m in MODULES:
        (forms_dir / f"{m['id']}.rce").write_text(m["rce"], encoding="utf-8")

    traces = generate_traces()
    rs_path, cs_path = build_rust_and_csharp_bundles(work, traces)
    if args.emit_cs_only:
        return

    rce_hashes = run_rce_traces(args.rce, forms_dir, work, traces)
    gd_hashes = run_godot_traces(args.godot, work, traces)

    rs_bin = work / "verify_h4_rust_ecs"
    subprocess.run([args.rustc, "--edition", "2021", "-O", str(rs_path), "-o", str(rs_bin)], check=True)
    rs_canon = json.loads(subprocess.check_output([str(rs_bin)], text=True))
    rs_hashes = {mid: [hashlib.sha256(s.encode()).hexdigest() for s in seqs] for mid, seqs in rs_canon.items()}

    cs_canon = json.loads(pathlib.Path(args.csharp_json).read_text(encoding="utf-8-sig"))
    cs_hashes = {mid: [hashlib.sha256(s.encode()).hexdigest() for s in seqs] for mid, seqs in cs_canon.items()}

    per_module = []
    mismatches = 0
    by_game: dict[str, dict[str, Any]] = {}

    for m in MODULES:
        mid = m["id"]
        g = m["game"]
        m_rce = count_metrics(m["rce"], "rce")
        m_cs = count_metrics(m["csharp"], "csharp")
        m_gd = count_metrics(m["gdscript"], "gdscript")
        m_rs = count_metrics(m["rust_ecs"], "rust_ecs")

        mod_mismatch = sum(
            1 for i in range(10)
            if gd_hashes[mid][i] != rce_hashes[mid][i]
            or rs_hashes[mid][i] != rce_hashes[mid][i]
            or cs_hashes[mid][i] != rce_hashes[mid][i]
        )
        mismatches += mod_mismatch

        bg = by_game.setdefault(g, {
            "modules": 0,
            "rce_behavior_sloc": 0,
            "rce_total_sloc_with_intent": 0,
            "csharp_sloc": 0,
            "gdscript_sloc": 0,
            "rust_ecs_sloc": 0,
            "rce_tokens": 0,
            "csharp_tokens": 0,
            "gdscript_tokens": 0,
            "rust_ecs_tokens": 0,
            "rce_glue": 0,
            "csharp_glue": 0,
            "gdscript_glue": 0,
            "rust_ecs_glue": 0,
        })
        bg["modules"] += 1
        bg["rce_behavior_sloc"] += m_rce["behavior_sloc"]
        bg["rce_total_sloc_with_intent"] += m_rce["total_sloc_with_intent"]
        bg["csharp_sloc"] += m_cs["behavior_sloc"]
        bg["gdscript_sloc"] += m_gd["behavior_sloc"]
        bg["rust_ecs_sloc"] += m_rs["behavior_sloc"]
        bg["rce_tokens"] += m_rce["behavior_tokens"]
        bg["csharp_tokens"] += m_cs["behavior_tokens"]
        bg["gdscript_tokens"] += m_gd["behavior_tokens"]
        bg["rust_ecs_tokens"] += m_rs["behavior_tokens"]
        bg["rce_glue"] += m_rce["glue_lines"]
        bg["csharp_glue"] += m_cs["glue_lines"]
        bg["gdscript_glue"] += m_gd["glue_lines"]
        bg["rust_ecs_glue"] += m_rs["glue_lines"]

        per_module.append({
            "id": mid,
            "game": g,
            "name": m["name"],
            "rce": m_rce,
            "unity_csharp": m_cs,
            "godot4_gdscript": m_gd,
            "bevy_rust_ecs": m_rs,
            "sloc_reduction_vs_csharp_pct": round(100.0 * (1.0 - m_rce["behavior_sloc"] / m_cs["behavior_sloc"]), 2),
            "sloc_with_intent_reduction_vs_csharp_pct": round(100.0 * (1.0 - m_rce["total_sloc_with_intent"] / m_cs["behavior_sloc"]), 2),
            "sloc_reduction_vs_rust_ecs_pct": round(100.0 * (1.0 - m_rce["behavior_sloc"] / m_rs["behavior_sloc"]), 2),
            "sloc_reduction_vs_gdscript_pct": round(100.0 * (1.0 - m_rce["behavior_sloc"] / m_gd["behavior_sloc"]), 2),
            "traces_verified": 10,
            "cross_language_mismatches": mod_mismatch,
        })

    for bg in by_game.values():
        bg["reduction_vs_csharp_pct"] = round(100.0 * (1.0 - bg["rce_behavior_sloc"] / bg["csharp_sloc"]), 2)
        bg["reduction_with_intent_vs_csharp_pct"] = round(100.0 * (1.0 - bg["rce_total_sloc_with_intent"] / bg["csharp_sloc"]), 2)
        bg["reduction_vs_rust_ecs_pct"] = round(100.0 * (1.0 - bg["rce_behavior_sloc"] / bg["rust_ecs_sloc"]), 2)
        bg["reduction_vs_gdscript_pct"] = round(100.0 * (1.0 - bg["rce_behavior_sloc"] / bg["gdscript_sloc"]), 2)

    tot_rce = sum(x["rce"]["behavior_sloc"] for x in per_module)
    tot_rce_int = sum(x["rce"]["total_sloc_with_intent"] for x in per_module)
    tot_cs = sum(x["unity_csharp"]["behavior_sloc"] for x in per_module)
    tot_gd = sum(x["godot4_gdscript"]["behavior_sloc"] for x in per_module)
    tot_rs = sum(x["bevy_rust_ecs"]["behavior_sloc"] for x in per_module)
    tot_3eng = tot_cs + tot_gd + tot_rs

    tot_tok_rce = sum(x["rce"]["behavior_tokens"] for x in per_module)
    tot_tok_cs = sum(x["unity_csharp"]["behavior_tokens"] for x in per_module)
    tot_tok_gd = sum(x["godot4_gdscript"]["behavior_tokens"] for x in per_module)
    tot_tok_rs = sum(x["bevy_rust_ecs"]["behavior_tokens"] for x in per_module)

    tot_glue_rce = sum(x["rce"]["glue_lines"] for x in per_module)
    tot_glue_cs = sum(x["unity_csharp"]["glue_lines"] for x in per_module)
    tot_glue_gd = sum(x["godot4_gdscript"]["glue_lines"] for x in per_module)
    tot_glue_rs = sum(x["bevy_rust_ecs"]["glue_lines"] for x in per_module)

    red_cs = round(100.0 * (1.0 - tot_rce / tot_cs), 2)
    red_cs_int = round(100.0 * (1.0 - tot_rce_int / tot_cs), 2)
    red_rs = round(100.0 * (1.0 - tot_rce / tot_rs), 2)
    red_gd = round(100.0 * (1.0 - tot_rce / tot_gd), 2)
    red_3eng = round(100.0 * (1.0 - tot_rce / tot_3eng), 2)

    out = {
        "hypothesis": "GE-H4",
        "total_modules": len(per_module),
        "languages": 4,
        "total_implementations": len(per_module) * 4,
        "traces_per_module": 10,
        "events_per_trace": 20,
        "total_trace_executions": len(per_module) * 10 * 4,
        "cross_language_trace_mismatches": mismatches,
        "totals": {
            "rce_behavior_sloc": tot_rce,
            "rce_total_sloc_with_intent": tot_rce_int,
            "unity_csharp_sloc": tot_cs,
            "godot4_gdscript_sloc": tot_gd,
            "bevy_rust_ecs_sloc": tot_rs,
            "three_engine_combined_sloc": tot_3eng,
            "rce_behavior_tokens": tot_tok_rce,
            "unity_csharp_tokens": tot_tok_cs,
            "godot4_gdscript_tokens": tot_tok_gd,
            "bevy_rust_ecs_tokens": tot_tok_rs,
            "rce_glue_lines": tot_glue_rce,
            "unity_csharp_glue_lines": tot_glue_cs,
            "godot4_gdscript_glue_lines": tot_glue_gd,
            "bevy_rust_ecs_glue_lines": tot_glue_rs,
            "sloc_reduction_vs_unity_csharp_pct": red_cs,
            "sloc_with_intent_reduction_vs_unity_csharp_pct": red_cs_int,
            "sloc_reduction_vs_bevy_rust_ecs_pct": red_rs,
            "sloc_reduction_vs_godot4_gdscript_pct": red_gd,
            "sloc_reduction_vs_3engine_sum_pct": red_3eng,
            "token_reduction_vs_unity_csharp_pct": round(100.0 * (1.0 - tot_tok_rce / tot_tok_cs), 2),
            "token_reduction_vs_bevy_rust_ecs_pct": round(100.0 * (1.0 - tot_tok_rce / tot_tok_rs), 2),
            "glue_reduction_vs_unity_csharp_pct": round(100.0 * (1.0 - tot_glue_rce / tot_glue_cs), 2),
            "gamerule_reference_reduction_pct": 81.3,
            "kill_threshold_pct": 50.0,
            "passes_50pct_threshold_vs_csharp": red_cs >= 50.0,
        },
        "by_game": by_game,
        "modules": per_module,
    }
    pathlib.Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
