#!/usr/bin/env python3
"""
form_to_gdscript.py — Form-to-Godot 4 Headless GDScript Emitter (`GE-H4` & `GE-H9`).

Compiles an admitted `.rce` Form (via `rce check` + `rce emit form` from `openIE-dev/rce`
at commit `1762fb4bb65a`) into standalone Godot 4.x GDScript (`extends SceneTree` or
`extends RefCounted`) with deterministic 64-bit integer / `Q32.32` helpers, transactional
`fail`/`kept` rollback, canonical state serialization, and FIPS `SHA-256` trace hashing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Any


GDSCRIPT_HELPERS = """\
static func _idiv(a: int, b: int) -> int:
\t@warning_ignore("integer_division")
\treturn a / b

static func _irem(a: int, b: int) -> int:
\treturn a % b

static func _ishl(a: int, b: int) -> int:
\treturn a << b

static func _ishr(a: int, b: int) -> int:
\treturn a >> b

static func qmul_q32(a: int, b: int) -> int:
\tvar ah: int = a >> 32
\tvar al: int = a & 0xFFFFFFFF
\tvar bh: int = b >> 32
\tvar bl: int = b & 0xFFFFFFFF
\tvar al1: int = (al >> 16) & 0xFFFF
\tvar al0: int = al & 0xFFFF
\tvar bl1: int = (bl >> 16) & 0xFFFF
\tvar bl0: int = bl & 0xFFFF
\tvar low_hi: int = al1 * bl1 + ((al1 * bl0 + al0 * bl1 + ((al0 * bl0) >> 16)) >> 16)
\treturn ((ah * bh) << 32) + ah * bl + al * bh + low_hi

static func isqrt_i64(n: int) -> int:
\tif n <= 0:
\t\treturn 0
\tvar x: int = n
\tvar y: int = (x + 1) >> 1
\twhile y < x:
\t\tx = y
\t\ty = _idiv(x + _idiv(n, x), 2)
\treturn x

static func _canon_val(v: Variant) -> String:
\tif typeof(v) == TYPE_BOOL:
\t\treturn "true" if v else "false"
\telif typeof(v) == TYPE_INT:
\t\treturn str(v)
\telif typeof(v) == TYPE_STRING:
\t\treturn JSON.stringify(v)
\telif typeof(v) == TYPE_ARRAY:
\t\tvar parts: Array[String] = []
\t\tfor item in v:
\t\t\tparts.append(_canon_val(item))
\t\treturn "[" + ",".join(parts) + "]"
\telif typeof(v) == TYPE_DICTIONARY:
\t\tvar ks: Array = v.keys()
\t\tks.sort()
\t\tvar kv: Array[String] = []
\t\tfor k in ks:
\t\t\tkv.append(JSON.stringify(str(k)) + ":" + _canon_val(v[k]))
\t\treturn "{" + ",".join(kv) + "}"
\treturn str(v)
"""


class GDScriptEmitter:
    def __init__(self, form: dict[str, Any], standalone: bool = True) -> None:
        self.form = form
        self.standalone = standalone
        self.consts: list[tuple[str, dict[str, Any]]] = []
        self.fns: list[dict[str, Any]] = []
        self.state_fields: list[tuple[str, str, dict[str, Any]]] = []
        self.state_names: set[str] = set()
        self.events: dict[str, dict[str, str]] = {}
        self.steps: list[dict[str, Any]] = []
        self._collect_items()

    @staticmethod
    def _gd_type(ty: Any) -> str:
        if isinstance(ty, dict) and "Path" in ty:
            p = ty["Path"][0]
            head = p[-1] if p else ""
            if head in ("i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "usize"):
                return "int"
            if head == "bool":
                return "bool"
            if head == "text":
                return "String"
            if head == "List":
                return "Array"
            if head == "Map":
                return "Dictionary"
        return "Variant"

    def _collect_items(self) -> None:
        for item in self.form.get("terms", {}).get("items", []):
            if not isinstance(item, dict):
                continue
            if "Const" in item:
                c = item["Const"]
                self.consts.append((c["name"], c["e"]))
            elif "Fn" in item:
                self.fns.append(item["Fn"])
            elif "State" in item:
                st = item["State"]
                for fld in st["fields"]:
                    fname = fld["name"]
                    gty = self._gd_type(fld.get("ty"))
                    self.state_fields.append((fname, gty, fld["init"]))
                    self.state_names.add(fname)
            elif "Event" in item:
                ev = item["Event"]
                self.events[ev["name"]] = {p[0]: self._gd_type(p[1]) for p in ev.get("payload", [])}
            elif "Step" in item:
                self.steps.append(item["Step"])

    def emit_expr(self, e: Any, locals_set: set[str]) -> str:
        if e is None:
            return "null"
        if isinstance(e, str):
            return "null"
        if "Int" in e:
            return str(e["Int"][0])
        if "Bool" in e:
            return "true" if e["Bool"][0] else "false"
        if "Str" in e:
            return json.dumps(e["Str"][0])
        if "None" in e or "Unit" in e:
            return "null"
        if "Name" in e:
            nm = e["Name"][0]
            if nm in locals_set:
                return f"_l_{nm}"
            if nm in self.state_names:
                return f"self.{nm}"
            return nm
        if "Neg" in e:
            return f"(-({self.emit_expr(e['Neg'][0], locals_set)}))"
        if "Not" in e:
            return f"(not ({self.emit_expr(e['Not'][0], locals_set)}))"
        if "BitNot" in e:
            return f"(~({self.emit_expr(e['BitNot'][0], locals_set)}))"
        if "Cast" in e:
            inner = self.emit_expr(e["Cast"][0], locals_set)
            return f"int({inner})"
        if "List" in e:
            items = [self.emit_expr(x, locals_set) for x in e["List"][0]]
            return "[" + ", ".join(items) + "]"
        if "ListRepeat" in e:
            val_e, cnt_e, _ = e["ListRepeat"]
            return f"_repeat_val({self.emit_expr(val_e, locals_set)}, {self.emit_expr(cnt_e, locals_set)})"
        if "Map" in e:
            pairs = [f"{self.emit_expr(k, locals_set)}: {self.emit_expr(v, locals_set)}" for k, v in e["Map"][0]]
            return "{" + ", ".join(pairs) + "}"
        if "Index" in e:
            base, idxs, _ = e["Index"]
            res = self.emit_expr(base, locals_set)
            for idx in idxs:
                res = f"{res}[{self.emit_expr(idx, locals_set)}]"
            return res
        if "Member" in e:
            base, fld, _ = e["Member"]
            return f"{self.emit_expr(base, locals_set)}.{fld}"
        if "If" in e:
            c, t_e, f_e, _ = e["If"]
            return f"({self.emit_expr(t_e, locals_set)} if ({self.emit_expr(c, locals_set)}) else {self.emit_expr(f_e, locals_set)})"
        if "Bin" in e:
            op, a, b, _ = e["Bin"]
            sa = self.emit_expr(a, locals_set)
            sb = self.emit_expr(b, locals_set)
            if op == "/":
                return f"_idiv({sa}, {sb})"
            if op == "%":
                return f"_irem({sa}, {sb})"
            if op == "<<":
                return f"_ishl({sa}, {sb})"
            if op == ">>":
                return f"_ishr({sa}, {sb})"
            return f"({sa} {op} {sb})"
        if "Call" in e:
            callee, args, _, _ = e["Call"]
            arg_strs = [self.emit_expr(a["e"], locals_set) for a in args]
            if isinstance(callee, dict) and "Member" in callee:
                recv, meth, _ = callee["Member"]
                s_recv = self.emit_expr(recv, locals_set)
                if meth == "len":
                    return f"({s_recv}).size()"
                if meth == "push":
                    return f"({s_recv}).append({arg_strs[0]})"
                if meth == "contains":
                    return f"({s_recv}).has({arg_strs[0]})"
                if meth == "abs":
                    return f"absi({s_recv})"
                return f"({s_recv}).{meth}({', '.join(arg_strs)})"
            s_callee = self.emit_expr(callee, set())
            return f"{s_callee}({', '.join(arg_strs)})"
        raise ValueError(f"Unsupported RCE Expr in form_to_gdscript: {e!r}")

    def _pat_var_name(self, pat: Any) -> str:
        if isinstance(pat, dict):
            if "Path" in pat and pat["Path"]:
                return pat["Path"][-1]
            if pat == {"Wild": None}:
                return "_unused"
        if pat == "Wild":
            return "_unused"
        raise ValueError(f"Unsupported Pat: {pat!r}")

    def emit_stmts(self, stmts: list[Any], indent: int, locals_set: set[str], in_step: bool) -> list[str]:
        pad = "\t" * indent
        out: list[str] = []
        if not stmts:
            out.append(f"{pad}pass")
            return out
        for st in stmts:
            if st == "Pass" or (isinstance(st, dict) and "Pass" in st):
                out.append(f"{pad}pass")
            elif "Let" in st:
                pat, _ty, val_e, _ = st["Let"]
                vname = self._pat_var_name(pat)
                rhs = self.emit_expr(val_e, locals_set)
                locals_set.add(vname)
                out.append(f"{pad}var _l_{vname} = {rhs}")
            elif "Var" in st:
                vname, _ty, val_e, _ = st["Var"]
                rhs = self.emit_expr(val_e, locals_set)
                locals_set.add(vname)
                out.append(f"{pad}var _l_{vname} = {rhs}")
            elif "Assign" in st:
                op, lhs_e, rhs_e = st["Assign"]
                lhs = self.emit_expr(lhs_e, locals_set)
                rhs = self.emit_expr(rhs_e, locals_set)
                if op == "/=":
                    out.append(f"{pad}{lhs} = _idiv({lhs}, {rhs})")
                else:
                    out.append(f"{pad}{lhs} {op} {rhs}")
            elif "If" in st:
                branches, else_blk = st["If"]
                for idx, (cond_e, blk) in enumerate(branches):
                    kw = "if" if idx == 0 else "elif"
                    c_str = self.emit_expr(cond_e, locals_set)
                    out.append(f"{pad}{kw} {c_str}:")
                    branch_locals = set(locals_set)
                    out.extend(self.emit_stmts(blk, indent + 1, branch_locals, in_step))
                if else_blk is not None:
                    out.append(f"{pad}else:")
                    else_locals = set(locals_set)
                    out.extend(self.emit_stmts(else_blk, indent + 1, else_locals, in_step))
            elif "While" in st:
                cond_e, _inv, blk = st["While"]
                c_str = self.emit_expr(cond_e, locals_set)
                out.append(f"{pad}while {c_str}:")
                w_locals = set(locals_set)
                out.extend(self.emit_stmts(blk, indent + 1, w_locals, in_step))
            elif "For" in st:
                pat, iter_e, blk, _ = st["For"]
                vname = self._pat_var_name(pat)
                it_str = self.emit_expr(iter_e, locals_set)
                f_locals = set(locals_set)
                f_locals.add(vname)
                out.append(f"{pad}for _l_{vname} in {it_str}:")
                out.extend(self.emit_stmts(blk, indent + 1, f_locals, in_step))
            elif "Return" in st:
                ret_e, _ = st["Return"]
                if ret_e is None:
                    out.append(f"{pad}return")
                else:
                    out.append(f"{pad}return {self.emit_expr(ret_e, locals_set)}")
            elif st == "Break" or (isinstance(st, dict) and "Break" in st):
                out.append(f"{pad}break")
            elif st == "Continue" or (isinstance(st, dict) and "Continue" in st):
                out.append(f"{pad}continue")
            elif "Fail" in st:
                if in_step:
                    out.append(f"{pad}self._kept_fail = true")
                    out.append(f"{pad}return")
                else:
                    out.append(f"{pad}push_error('Form fail')")
                    out.append(f"{pad}return null")
            elif "Expr" in st:
                out.append(f"{pad}{self.emit_expr(st['Expr'], locals_set)}")
            else:
                raise ValueError(f"Unsupported Stmt in form_to_gdscript: {st!r}")
        return out

    def emit(self) -> str:
        lines: list[str] = []
        base_cls = "SceneTree" if self.standalone else "RefCounted"
        mod_path = ".".join(self.form.get("terms", {}).get("path", ["form_module"]))
        lines.append(f"# Auto-emitted by form_to_gdscript.py from RCE Form `{mod_path}` (openIE-dev/rce 1762fb4bb65a)")
        lines.append(f"extends {base_cls}")
        lines.append("")
        lines.append("static func _repeat_val(v: Variant, n: int) -> Array:")
        lines.append("\tvar a: Array = []")
        lines.append("\ta.resize(n)")
        lines.append("\tfor i in range(n):")
        lines.append("\t\ta[i] = v")
        lines.append("\treturn a")
        lines.append("")
        lines.append(GDSCRIPT_HELPERS.rstrip())
        lines.append("")

        # Constants
        for cname, ce in self.consts:
            lines.append(f"const {cname} = {self.emit_expr(ce, set())}")
        if self.consts:
            lines.append("")

        # State fields
        lines.append("var _kept_fail: bool = false")
        for fname, gty, init_e in self.state_fields:
            lines.append(f"var {fname}: {gty} = {self.emit_expr(init_e, set())}")
        lines.append("")

        lines.append("func reset_state() -> void:")
        lines.append("\tself._kept_fail = false")
        if not self.state_fields:
            lines.append("\tpass")
        for fname, _gty, init_e in self.state_fields:
            lines.append(f"\tself.{fname} = {self.emit_expr(init_e, set())}")
        lines.append("")

        lines.append("func snapshot_state() -> Dictionary:")
        lines.append("\treturn {")
        for fname, gty, _ in self.state_fields:
            if gty in ("Array", "Dictionary"):
                lines.append(f'\t\t"{fname}": self.{fname}.duplicate(true),')
            else:
                lines.append(f'\t\t"{fname}": self.{fname},')
        lines.append("\t}")
        lines.append("")

        lines.append("func restore_state(snap: Dictionary) -> void:")
        if not self.state_fields:
            lines.append("\tpass")
        for fname, gty, _ in self.state_fields:
            if gty in ("Array", "Dictionary"):
                lines.append(f'\tself.{fname} = snap["{fname}"].duplicate(true)')
            elif gty == "int":
                lines.append(f'\tself.{fname} = int(snap["{fname}"])')
            elif gty == "bool":
                lines.append(f'\tself.{fname} = bool(snap["{fname}"])')
            else:
                lines.append(f'\tself.{fname} = snap["{fname}"]')
        lines.append("")

        lines.append("func canonical_state() -> String:")
        lines.append("\treturn _canon_val(snapshot_state())")
        lines.append("")

        lines.append("func state_sha256() -> String:")
        lines.append("\treturn canonical_state().sha256_text()")
        lines.append("")

        # Pure helper functions
        for fn in self.fns:
            sig = fn["sig"]
            fname = sig["name"]
            if fname == "main":
                continue
            pnames: list[str] = []
            locals_set: set[str] = set()
            for p in sig.get("params", []):
                if isinstance(p, dict) and "Named" in p:
                    pn = p["Named"]["name"]
                    pnames.append(f"_l_{pn}")
                    locals_set.add(pn)
            lines.append(f"func {fname}({', '.join(pnames)}):")
            body = fn["body"]
            if "Arrow" in body:
                lines.append(f"\treturn {self.emit_expr(body['Arrow'], locals_set)}")
            else:
                lines.extend(self.emit_stmts(body["Block"], 1, locals_set, in_step=False))
            lines.append("")

        # Step handlers in document order (SCXML / GameRule deterministic contract)
        for idx, st in enumerate(self.steps):
            pat = st["pat"]
            ev_name = ""
            bindings: list[tuple[str, str]] = []
            if isinstance(pat, dict) and "Ctor" in pat:
                ctor_path, fields = pat["Ctor"]
                ev_name = ctor_path[-1]
                for lbl, subpat in fields:
                    if subpat != "Wild" and subpat != {"Wild": None}:
                        vname = self._pat_var_name(subpat)
                        key = lbl if lbl is not None else vname
                        bindings.append((key, vname))
            elif isinstance(pat, dict) and "Path" in pat:
                ev_name = pat["Path"][-1]
            lines.append(f"func _step_{idx}(_ev: Dictionary) -> bool:")
            lines.append(f'\tif _ev.get("type", "") != "{ev_name}":')
            lines.append("\t\treturn false")
            locals_set = set()
            ev_schema = self.events.get(ev_name, {})
            for key, vname in bindings:
                locals_set.add(vname)
                pty = ev_schema.get(key, "Variant")
                if pty == "int":
                    lines.append(f'\tvar _l_{vname}: int = int(_ev["{key}"])')
                elif pty == "bool":
                    lines.append(f'\tvar _l_{vname}: bool = bool(_ev["{key}"])')
                elif pty == "String":
                    lines.append(f'\tvar _l_{vname}: String = str(_ev["{key}"])')
                else:
                    lines.append(f'\tvar _l_{vname} = _ev["{key}"]')
            if st.get("guard") is not None:
                g_str = self.emit_expr(st["guard"], locals_set)
                lines.append(f"\tif not ({g_str}):")
                lines.append("\t\treturn false")
            body = st["body"]
            if "Arrow" in body:
                only_fld = self.state_fields[0][0]
                lines.append(f"\tself.{only_fld} = {self.emit_expr(body['Arrow'], locals_set)}")
            else:
                lines.extend(self.emit_stmts(body["Block"], 1, locals_set, in_step=True))
            lines.append("\treturn true")
            lines.append("")

        # Master deterministic macrostep dispatcher (declaration order over regions)
        # Group steps by region so first matching guarded step per region fires, matching RCE semantics
        regions_order: list[str] = []
        steps_by_region: dict[str, list[int]] = {}
        for idx, st in enumerate(self.steps):
            reg = st["region"]
            if reg not in steps_by_region:
                regions_order.append(reg)
                steps_by_region[reg] = []
            steps_by_region[reg].append(idx)

        lines.append("func apply_event(ev: Dictionary) -> bool:")
        lines.append("\tvar _pre: Dictionary = snapshot_state()")
        lines.append("\tself._kept_fail = false")
        for reg in regions_order:
            s_idxs = steps_by_region[reg]
            for j, s_idx in enumerate(s_idxs):
                kw = "if" if j == 0 else "elif"
                lines.append(f"\t{kw} _step_{s_idx}(ev):")
                lines.append("\t\tif self._kept_fail:")
                lines.append("\t\t\trestore_state(_pre)")
                lines.append("\t\t\treturn false")
        lines.append("\treturn true")
        lines.append("")

        if self.standalone:
            lines.extend([
                "func _init() -> void:",
                "\tvar args: PackedStringArray = OS.get_cmdline_user_args()",
                "\tif args.size() < 1:",
                '\t\tprint(JSON.stringify({"canonical": canonical_state(), "sha256": state_sha256()}))',
                "\t\tquit(0)",
                "\t\treturn",
                "\tvar trace_path: String = args[0]",
                "\tvar raw: String = FileAccess.get_file_as_string(trace_path)",
                "\tvar parsed: Variant = JSON.parse_string(raw)",
                "\tvar events: Array = parsed if typeof(parsed) == TYPE_ARRAY else parsed.get(\"events\", [])",
                '\tvar rolling: String = "0000000000000000000000000000000000000000000000000000000000000000"',
                "\tvar step_hashes: Array[String] = []",
                "\tfor ev in events:",
                "\t\tapply_event(ev)",
                "\t\tvar h: String = state_sha256()",
                "\t\trolling = (rolling + h).sha256_text()",
                "\t\tstep_hashes.append(h)",
                "\tvar out: Dictionary = {",
                '\t\t"steps": events.size(),',
                '\t\t"final_state": snapshot_state(),',
                '\t\t"final_canonical": canonical_state(),',
                '\t\t"final_sha256": state_sha256(),',
                '\t\t"rolling_trace_sha256": rolling,',
                '\t\t"step_hashes": step_hashes,',
                "\t}",
                "\tif args.size() >= 2:",
                "\t\tvar f: FileAccess = FileAccess.open(args[1], FileAccess.WRITE)",
                "\t\tf.store_string(JSON.stringify(out))",
                "\t\tf.close()",
                "\telse:",
                "\t\tprint(JSON.stringify(out))",
                "\tquit(0)",
            ])
        return "\n".join(lines) + "\n"


def compile_rce_to_gdscript(rce_bin: str, rce_path: pathlib.Path, standalone: bool = True) -> str:
    chk = subprocess.run([rce_bin, "check", str(rce_path)], capture_output=True, text=True, check=False)
    if chk.returncode != 0:
        raise RuntimeError(f"rce check failed on {rce_path}:\n{chk.stdout}\n{chk.stderr}")
    raw_json = subprocess.check_output([rce_bin, "emit", "form", str(rce_path)], text=True)
    form = json.loads(raw_json)
    return GDScriptEmitter(form, standalone=standalone).emit()


def main() -> None:
    ap = argparse.ArgumentParser(description="Compile an admitted .rce Form into Godot 4 GDScript.")
    ap.add_argument("--rce-bin", required=True, help="Path to openIE-dev/rce binary")
    ap.add_argument("--input", required=True, help="Input .rce file")
    ap.add_argument("--output", required=True, help="Output .gd file")
    ap.add_argument("--library", action="store_true", help="Emit extends RefCounted instead of SceneTree")
    args = ap.parse_args()

    gd_src = compile_rce_to_gdscript(args.rce_bin, pathlib.Path(args.input), standalone=not args.library)
    out_p = pathlib.Path(args.output)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(gd_src, encoding="utf-8")


if __name__ == "__main__":
    main()
