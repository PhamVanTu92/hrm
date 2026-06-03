"""Dynamic payroll formula engine (pure, no DB).

HR defines salary formulas as text expressions over named variables. This
module turns a set of ``target_var = expression`` formulas into a safe,
deterministic evaluation:

1. ``extract_vars``      — static analysis of an expression's variable refs.
2. ``build_eval_order``  — dependency DAG + topological sort; rejects cycles
                            and references to undefined variables.
3. ``make_evaluator``    — a sandboxed SimpleEval (whitelisted ops/functions;
                            no attribute access, imports, comprehensions).
4. ``evaluate``          — evaluate formulas in dependency order.

Security: expressions come from HR (semi-trusted) and must never reach
``eval()``. SimpleEval restricts the grammar to arithmetic + a tiny function
whitelist, so a malicious formula cannot execute code or exfiltrate data.

The engine works in ``float`` and rounds every step to 2 decimals: this keeps
formulas able to use literal rates (e.g. ``luong * 0.105``) and is fully
deterministic, so a run is reproducible from its input + formula snapshot.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping

import networkx as nx
from simpleeval import SimpleEval

from app.core.exceptions import ValidationError

# Functions a formula may call. Everything else (attribute access, imports,
# comprehensions, lambdas, names not listed) is rejected by SimpleEval.
_FUNCTIONS: dict[str, object] = {
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    # Uppercase IF: 'if' is a Python keyword and cannot be a call target.
    # Formulas may also use the native ternary 'a if cond else b'.
    "IF": lambda c, a, b: a if c else b,
}
_FUNCTION_NAMES = frozenset(_FUNCTIONS)

_MAX_STRING_LENGTH = 1000


def extract_vars(expression: str) -> set[str]:
    """Return the set of variable names referenced by an expression.

    Function names from the whitelist are excluded (they are calls, not vars).
    Raises :class:`ValidationError` if the expression is not parseable.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValidationError(f"Biểu thức không hợp lệ: {exc.msg}") from exc
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names - _FUNCTION_NAMES


def build_eval_order(formulas: Iterable[tuple[str, str]], base_vars: set[str]) -> list[str]:
    """Topologically order formula targets by dependency.

    Args:
        formulas: iterable of ``(target_var, expression)``.
        base_vars: variables that already exist in the context (inputs, fixed,
            base attendance/salary vars) and so need no formula.

    Returns:
        Formula target vars in a safe evaluation order.

    Raises:
        ValidationError: on a reference to an unknown variable, or a circular
            dependency (the offending cycle is reported in ``details``).
    """
    formula_list = list(formulas)
    defined = {target for target, _ in formula_list}
    graph: nx.DiGraph = nx.DiGraph()

    for target, expression in formula_list:
        graph.add_node(target)
        for var in extract_vars(expression):
            if var in defined:
                graph.add_edge(var, target)  # var must be computed before target
            elif var not in base_vars:
                raise ValidationError(
                    f"Biến '{var}' trong công thức '{target}' không tồn tại",
                    details={"target": target, "unknown_var": var},
                )

    if not nx.is_directed_acyclic_graph(graph):
        cycle = nx.find_cycle(graph)
        raise ValidationError(
            "Công thức bị phụ thuộc vòng",
            details={"cycle": [f"{u}->{v}" for u, v, *_ in cycle]},
        )
    return list(nx.topological_sort(graph))


def make_evaluator(names: Mapping[str, object]) -> SimpleEval:
    """Build a sandboxed evaluator bound to a variable context."""
    evaluator = SimpleEval()
    evaluator.names = dict(names)
    evaluator.functions = dict(_FUNCTIONS)
    evaluator.MAX_STRING_LENGTH = _MAX_STRING_LENGTH
    return evaluator


def evaluate(
    formula_by_target: Mapping[str, str],
    eval_order: list[str],
    context: dict[str, float],
) -> dict[str, float]:
    """Evaluate formulas into ``context`` following ``eval_order``.

    Each result is rounded to 2 decimals. Returns the augmented context.
    Raises :class:`ValidationError` on any evaluation error.
    """
    for target in eval_order:
        expression = formula_by_target[target]
        evaluator = make_evaluator(context)
        try:
            value = evaluator.eval(expression)
        except ValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any eval failure uniformly
            raise ValidationError(
                f"Lỗi tính công thức '{target}': {exc}",
                details={"target": target},
            ) from exc
        context[target] = round(float(value), 2)
    return context
