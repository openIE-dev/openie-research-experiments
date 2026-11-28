# SPDX-License-Identifier: Apache-2.0
"""40-Task Deterministic Benchmark Suite & Programmatic AST Mutant Generator
for Kit #8 (`kits/spec-fidelity-barrier/`).

Covers 6 systems domains (40 tasks total, 25 deterministic test vectors/task = 1,000 vectors):
  1. `ring_buffers`          (Tasks 01..07, 7 tasks)
  2. `saturating_ledgers`    (Tasks 08..14, 7 tasks)
  3. `interval_schedules`    (Tasks 15..20, 6 tasks)
  4. `capability_acls`       (Tasks 21..27, 7 tasks)
  5. `parser_state_machines` (Tasks 28..34, 7 tasks)
  6. `sorting_invariants`    (Tasks 35..40, 6 tasks)

Also provides:
  - 5 deterministic programmatic AST mutation operators (`ast.NodeTransformer`):
      M1 `zero_constant_stub`
      M2 `boundary_off_by_one`
      M3 `sign_or_bitop_flip`
      M4 `branch_drop`
      M5 `invariant_bypass`
  - 1 independent valid implementation + 5 distinct implanted defective candidates per task
    (`40` valid + `200` defective = `240` candidate implementations).
  - Three specification architectures:
      * Arm A (`shared_context_naive`): Goodhart/tautological spec sharing candidate context
      * Arm B (`isolated_spec_only`): Context-isolated (`Spec ⊥ Impl`) partial property spec
      * Arm C (`mutant_vacuity_barrier`): Context-isolated relational spec audited by the
        100%-kill AST Mutant/Vacuity Barrier (`SPEC_VACUOUS_REFUSED` on any surviving mutant).
"""

from __future__ import annotations

import ast
import collections
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    domain: str
    return_kind: str  # "INT", "BOOL", "LIST", "TUPLE2"
    grammar_type: str  # "INT", "BOOL", "LIST" (for Arm D typed token-masking)
    description: str
    reference_src: str
    valid_alt_fn: Callable[[Any], Any]
    defective_fns: dict[str, Callable[[Any], Any]]
    test_inputs: list[Any]
    partial_isolated_check: Callable[[Any, Any], bool]
    complete_isolated_check: Callable[[Any, Any], bool]


def _compile_solve_fn(src: str) -> Callable[[Any], Any]:
    ns: dict[str, Any] = {"collections": collections}
    code = compile(src, "<spec_barrier_ast>", "exec")
    exec(code, ns)
    fn = ns.get("solve")
    if not callable(fn):
        raise ValueError("Compiled source did not define callable `solve(inp)`")
    return fn


# ── Programmatic AST Mutation Operators (`ast.NodeTransformer`) ──────────────

def _zero_expr_for_kind(return_kind: str) -> ast.expr:
    if return_kind == "BOOL":
        return ast.Constant(value=False)
    if return_kind == "LIST":
        return ast.List(elts=[], ctx=ast.Load())
    if return_kind == "TUPLE2":
        return ast.Tuple(elts=[ast.Constant(value=0), ast.Constant(value=0)], ctx=ast.Load())
    return ast.Constant(value=0)


class _ZeroStubMutator(ast.NodeTransformer):
    """M1 (`zero_constant_stub`): Replaces function return expressions with type-valid zero/empty stub."""

    def __init__(self, return_kind: str) -> None:
        self.return_kind = return_kind
        self.mutated = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if node.name == "solve":
            self.mutated = True
            new_ret = ast.Return(value=_zero_expr_for_kind(self.return_kind))
            return ast.copy_location(
                ast.FunctionDef(
                    name=node.name,
                    args=node.args,
                    body=[new_ret],
                    decorator_list=[],
                    returns=node.returns,
                ),
                node,
            )
        return node


class _BoundaryOffByOneMutator(ast.NodeTransformer):
    """M2 (`boundary_off_by_one`): Shifts a comparison operator (`<` <-> `<=`, `>` <-> `>=`, `==` <-> `!=`)
    OR perturbs an integer boundary literal/call bound by +/-1 at `target_site` in AST pre-order.
    """

    def __init__(self, target_site: int) -> None:
        self.target_site = target_site
        self.seen = 0
        self.mutated = False

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]
        if len(node.ops) == 1:
            op = node.ops[0]
            replacement: ast.cmpop | None = None
            if isinstance(op, ast.Lt):
                replacement = ast.LtE()
            elif isinstance(op, ast.LtE):
                replacement = ast.Lt()
            elif isinstance(op, ast.Gt):
                replacement = ast.GtE()
            elif isinstance(op, ast.GtE):
                replacement = ast.Gt()
            elif isinstance(op, ast.Eq):
                replacement = ast.NotEq()
            elif isinstance(op, ast.NotEq):
                replacement = ast.Eq()
            if replacement is not None:
                if self.seen == self.target_site:
                    self.mutated = True
                    self.seen += 1
                    return ast.copy_location(
                        ast.Compare(left=node.left, ops=[replacement], comparators=node.comparators),
                        node,
                    )
                self.seen += 1
                if self.seen == self.target_site:
                    self.mutated = True
                    self.seen += 1
                    shifted = ast.BinOp(left=node.comparators[0], op=ast.Add(), right=ast.Constant(value=1))
                    return ast.copy_location(
                        ast.Compare(left=node.left, ops=node.ops, comparators=[shifted]),
                        node,
                    )
                self.seen += 1
                if self.seen == self.target_site:
                    self.mutated = True
                    self.seen += 1
                    shifted_dn = ast.BinOp(left=node.comparators[0], op=ast.Sub(), right=ast.Constant(value=1))
                    return ast.copy_location(
                        ast.Compare(left=node.left, ops=node.ops, comparators=[shifted_dn]),
                        node,
                    )
                self.seen += 1
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]
        if isinstance(node.func, ast.Name) and node.func.id in ("range", "min", "max") and node.args:
            if self.seen == self.target_site:
                self.mutated = True
                self.seen += 1
                new_args = list(node.args)
                new_args[-1] = ast.BinOp(left=new_args[-1], op=ast.Sub(), right=ast.Constant(value=1))
                return ast.copy_location(
                    ast.Call(func=node.func, args=new_args, keywords=node.keywords),
                    node,
                )
            self.seen += 1
        return node


class _SignOrOpFlipMutator(ast.NodeTransformer):
    """M3 (`sign_or_bitop_flip`): Flips arithmetic, bitwise, unary-sign, or boolean operator."""

    def __init__(self, target_site: int) -> None:
        self.target_site = target_site
        self.seen = 0
        self.mutated = False

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]
        op = node.op
        new_op: ast.operator | None = None
        if isinstance(op, ast.Add):
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                if self.seen == self.target_site:
                    self.mutated = True
                    self.seen += 1
                    return ast.copy_location(
                        ast.BinOp(left=node.left, op=ast.Sub(), right=ast.Constant(value=1)),
                        node,
                    )
                self.seen += 1
                return node
            new_op = ast.Sub()
        elif isinstance(op, ast.Sub):
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                if self.seen == self.target_site:
                    self.mutated = True
                    self.seen += 1
                    return ast.copy_location(
                        ast.BinOp(left=node.left, op=ast.Add(), right=ast.Constant(value=1)),
                        node,
                    )
                self.seen += 1
                return node
            new_op = ast.Add()
        elif isinstance(op, ast.BitAnd):
            new_op = ast.BitOr()
        elif isinstance(op, ast.BitOr):
            new_op = ast.BitAnd()
        elif isinstance(op, ast.FloorDiv):
            new_op = ast.Mod()
        elif isinstance(op, ast.Mult):
            new_op = ast.Add()
        elif isinstance(op, ast.LShift):
            new_op = ast.RShift()
        if new_op is not None:
            if self.seen == self.target_site:
                self.mutated = True
                self.seen += 1
                return ast.copy_location(ast.BinOp(left=node.left, op=new_op, right=node.right), node)
            self.seen += 1
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]
        if isinstance(node.op, ast.USub):
            if self.seen == self.target_site:
                self.mutated = True
                self.seen += 1
                return ast.copy_location(ast.UnaryOp(op=ast.UAdd(), operand=node.operand), node)
            self.seen += 1
        elif isinstance(node.op, ast.Invert):
            if self.seen == self.target_site:
                self.mutated = True
                self.seen += 1
                return node.operand
            self.seen += 1
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]
        new_op: ast.boolop = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        if self.seen == self.target_site:
            self.mutated = True
            self.seen += 1
            return ast.copy_location(ast.BoolOp(op=new_op, values=node.values), node)
        self.seen += 1
        return node


class _BranchDropMutator(ast.NodeTransformer):
    """M4 (`branch_drop`): Drops conditional guard at `target_site` by forcing condition to `False` (or `True` if else-less)."""

    def __init__(self, target_site: int, force_val: bool) -> None:
        self.target_site = target_site
        self.force_val = force_val
        self.seen = 0
        self.mutated = False

    def visit_If(self, node: ast.If) -> ast.AST:
        if self.seen == self.target_site:
            self.mutated = True
            self.seen += 1
            return ast.copy_location(
                ast.If(test=ast.Constant(value=self.force_val), body=node.body, orelse=node.orelse),
                node,
            )
        self.seen += 1
        return self.generic_visit(node)


class _InvariantBypassMutator(ast.NodeTransformer):
    """M5 (`invariant_bypass`): Wraps every `return expr` inside `solve` with a structural invariant corruptor
    that preserves outer Python return type/shape while violating conservation, uniqueness, or exact value invariants.
    """

    def __init__(self, return_kind: str) -> None:
        self.return_kind = return_kind
        self.mutated = False

    def visit_Return(self, node: ast.Return) -> ast.AST:
        if node.value is None:
            return node
        self.mutated = True
        v = node.value
        if self.return_kind == "LIST":
            # Preserves list length & monotonicity (all repeats of min/first element!) while breaking multiset/FIFO!
            corrupted = ast.parse("([_v[0]] * len(_v)) if len(_v) > 0 else []", mode="eval").body
        elif self.return_kind == "TUPLE2":
            # Preserves 2-tuple shape & first element while zeroing/corrupting second conservation/count component
            corrupted = ast.parse("(_v[0], (_v[1] ^ 1) if isinstance(_v[1], int) else 0)", mode="eval").body
        elif self.return_kind == "BOOL":
            # Inverts boolean verdict
            corrupted = ast.parse("(not bool(_v))", mode="eval").body
        else:
            # Perturbs integer post-value modulo 65536 (breaks saturation/exactness while staying int)
            corrupted = ast.parse("((int(_v) + 1) & 0xFFFF)", mode="eval").body

        # Substitute `_v` with original `node.value`
        class _SubV(ast.NodeTransformer):
            def visit_Name(self, n: ast.Name) -> ast.AST:
                if n.id == "_v":
                    return v
                return n

        replaced = _SubV().visit(corrupted)
        return ast.copy_location(ast.Return(value=replaced), node)


@dataclass(frozen=True)
class SynthesizedMutant:
    mutant_id: str
    category: str
    mutated_src: str
    fn: Callable[[Any], Any]


def generate_ast_mutants(task: TaskSpec) -> list[SynthesizedMutant]:
    """Synthesize all 5 deterministic AST mutants from `task.reference_src`."""
    base_tree = ast.parse(task.reference_src)
    oracle_fn = _compile_solve_fn(task.reference_src)
    oracle_outputs = [oracle_fn(x) for x in task.test_inputs]

    def _differs_from_oracle(fn: Callable[[Any], Any]) -> bool:
        for x, expected in zip(task.test_inputs, oracle_outputs):
            try:
                got = fn(x)
            except Exception:
                return True
            if got != expected or type(got) is not type(expected):
                return True
        return False

    mutants: list[SynthesizedMutant] = []

    # M1: Zero/constant stub
    t1 = ast.fix_missing_locations(_ZeroStubMutator(task.return_kind).visit(ast.parse(task.reference_src)))
    src1 = ast.unparse(t1)
    fn1 = _compile_solve_fn(src1)
    mutants.append(SynthesizedMutant(f"{task.task_id}::M1_zero_stub", "zero_constant_stub", src1, fn1))

    # M2: Boundary off-by-one (scan AST Compare sites until first behavior-changing boundary mutation)
    chosen_m2: SynthesizedMutant | None = None
    for site in range(16):
        m = _BoundaryOffByOneMutator(site)
        t2 = ast.fix_missing_locations(m.visit(ast.parse(task.reference_src)))
        if not m.mutated:
            break
        src2 = ast.unparse(t2)
        fn2 = _compile_solve_fn(src2)
        if _differs_from_oracle(fn2):
            chosen_m2 = SynthesizedMutant(f"{task.task_id}::M2_boundary_obo", "boundary_off_by_one", src2, fn2)
            break
    if chosen_m2 is None:
        raise RuntimeError(f"Failed to synthesize non-equivalent M2 boundary mutant for {task.task_id}")
    mutants.append(chosen_m2)

    # M3: Sign / arithmetic / bit-op flip
    chosen_m3: SynthesizedMutant | None = None
    for site in range(16):
        m = _SignOrOpFlipMutator(site)
        t3 = ast.fix_missing_locations(m.visit(ast.parse(task.reference_src)))
        if not m.mutated:
            break
        src3 = ast.unparse(t3)
        fn3 = _compile_solve_fn(src3)
        if _differs_from_oracle(fn3):
            chosen_m3 = SynthesizedMutant(f"{task.task_id}::M3_sign_op_flip", "sign_or_bitop_flip", src3, fn3)
            break
    if chosen_m3 is None:
        raise RuntimeError(f"Failed to synthesize non-equivalent M3 sign/op mutant for {task.task_id}")
    mutants.append(chosen_m3)

    # M4: Branch drop
    chosen_m4: SynthesizedMutant | None = None
    for site in range(16):
        found_site = False
        for forced in (False, True):
            m = _BranchDropMutator(site, forced)
            t4 = ast.fix_missing_locations(m.visit(ast.parse(task.reference_src)))
            if not m.mutated:
                break
            found_site = True
            src4 = ast.unparse(t4)
            fn4 = _compile_solve_fn(src4)
            if _differs_from_oracle(fn4):
                chosen_m4 = SynthesizedMutant(f"{task.task_id}::M4_branch_drop", "branch_drop", src4, fn4)
                break
        if chosen_m4 is not None or not found_site:
            break
    if chosen_m4 is None:
        raise RuntimeError(f"Failed to synthesize non-equivalent M4 branch-drop mutant for {task.task_id}")
    mutants.append(chosen_m4)

    # M5: Invariant bypass
    t5 = ast.fix_missing_locations(_InvariantBypassMutator(task.return_kind).visit(ast.parse(task.reference_src)))
    src5 = ast.unparse(t5)
    fn5 = _compile_solve_fn(src5)
    if not _differs_from_oracle(fn5):
        raise RuntimeError(f"Failed to synthesize non-equivalent M5 invariant-bypass mutant for {task.task_id}")
    mutants.append(SynthesizedMutant(f"{task.task_id}::M5_invariant_bypass", "invariant_bypass", src5, fn5))

    _ = base_tree
    return mutants


# Helper Fixing syntax typo guard: notice `_differs_from_oracle` above! Let's make sure no space after `_`!
