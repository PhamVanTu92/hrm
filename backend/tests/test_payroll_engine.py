"""Unit tests for the payroll formula engine (pure, no DB)."""

from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.modules.payroll.engine import (
    build_eval_order,
    evaluate,
    extract_vars,
    make_evaluator,
)


# --------------------------------------------------------------------------- #
# extract_vars                                                                #
# --------------------------------------------------------------------------- #
def test_extract_vars_excludes_functions() -> None:
    assert extract_vars("luong + phu_cap") == {"luong", "phu_cap"}
    # min/max/round/if are functions, not variables.
    assert extract_vars("max(luong, 0) + round(thuong, 2)") == {"luong", "thuong"}
    assert extract_vars("IF(cong > 0, luong, 0)") == {"cong", "luong"}
    # native ternary is also supported
    assert extract_vars("luong if cong > 0 else 0") == {"cong", "luong"}


def test_extract_vars_syntax_error() -> None:
    with pytest.raises(ValidationError):
        extract_vars("luong +")


# --------------------------------------------------------------------------- #
# build_eval_order                                                            #
# --------------------------------------------------------------------------- #
def test_eval_order_respects_dependencies() -> None:
    formulas = [
        ("tong_luong", "luong_thang + phu_cap"),
        ("luong_thang", "luong_cung / cong_chuan * cong_thuc_te"),
        ("phu_cap", "phu_cap_an + phu_cap_xang"),
    ]
    base = {"luong_cung", "cong_chuan", "cong_thuc_te", "phu_cap_an", "phu_cap_xang"}
    order = build_eval_order(formulas, base)
    # Dependencies must precede dependents.
    assert order.index("luong_thang") < order.index("tong_luong")
    assert order.index("phu_cap") < order.index("tong_luong")


def test_eval_order_unknown_variable() -> None:
    with pytest.raises(ValidationError) as exc:
        build_eval_order([("x", "khong_ton_tai + 1")], base_vars=set())
    assert exc.value.details.get("unknown_var") == "khong_ton_tai"


def test_eval_order_detects_cycle() -> None:
    formulas = [("a", "b + 1"), ("b", "a + 1")]
    with pytest.raises(ValidationError) as exc:
        build_eval_order(formulas, base_vars=set())
    assert "cycle" in exc.value.details


# --------------------------------------------------------------------------- #
# evaluate                                                                    #
# --------------------------------------------------------------------------- #
def test_evaluate_full_chain() -> None:
    formulas = {
        "luong_thang": "round(luong_cung / cong_chuan * cong_thuc_te, 2)",
        "phu_cap": "phu_cap_an + phu_cap_xang",
        "tong_luong": "luong_thang + phu_cap + ot_gio * 100000",
    }
    order = build_eval_order(
        list(formulas.items()),
        base_vars={
            "luong_cung",
            "cong_chuan",
            "cong_thuc_te",
            "phu_cap_an",
            "phu_cap_xang",
            "ot_gio",
        },
    )
    ctx = {
        "luong_cung": 22000000.0,
        "cong_chuan": 22.0,
        "cong_thuc_te": 22.0,
        "phu_cap_an": 730000.0,
        "phu_cap_xang": 500000.0,
        "ot_gio": 3.0,
    }
    result = evaluate(formulas, order, ctx)
    assert result["luong_thang"] == 22000000.0
    assert result["phu_cap"] == 1230000.0
    assert result["tong_luong"] == 23530000.0


def test_evaluate_with_conditional() -> None:
    formulas = {"thuong": "IF(cong_thuc_te >= cong_chuan, 1000000, 0)"}
    order = build_eval_order(list(formulas.items()), {"cong_thuc_te", "cong_chuan"})
    assert (
        evaluate(formulas, order, {"cong_thuc_te": 22.0, "cong_chuan": 22.0})["thuong"] == 1000000.0
    )
    assert evaluate(formulas, order, {"cong_thuc_te": 10.0, "cong_chuan": 22.0})["thuong"] == 0.0


def test_evaluate_runtime_error_wrapped() -> None:
    formulas = {"x": "luong / 0"}
    order = build_eval_order(list(formulas.items()), {"luong"})
    with pytest.raises(ValidationError):
        evaluate(formulas, order, {"luong": 100.0})


# --------------------------------------------------------------------------- #
# Sandbox safety — the security-critical part                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "malicious",
    [
        "__import__('os').system('echo hacked')",
        "(1).__class__.__bases__",
        "[x for x in range(10)]",
        "globals()",
        "open('/etc/passwd')",
    ],
)
def test_sandbox_rejects_dangerous_expressions(malicious: str) -> None:
    evaluator = make_evaluator({})
    with pytest.raises(Exception):  # noqa: B017,PT011 - any rejection is acceptable
        evaluator.eval(malicious)
