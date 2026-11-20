"""Boundary tests for quality gates."""
import ast
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "quality_gate", Path(__file__).resolve().parents[1] / "tools/quality_gate.py"
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def report(covered, statements=100, branch_coverage=True):
    return {"meta": {"branch_coverage": branch_coverage},
            "totals": {"covered_lines": covered, "num_statements": statements,
                       "covered_branches": 5, "num_branches": 10}}


@pytest.mark.parametrize("covered,statements,expected", [(90,100,True), (89,100,False),
                         (89999,100000,False), (91,100,True)])
def test_line_coverage_boundary(covered, statements, expected):
    line, branch, passed = gate.coverage_result(report(covered, statements))
    assert passed is expected
    assert branch == 50
    assert line == 100 * covered / statements


def test_empty_or_line_only_report_fails():
    with pytest.raises(ValueError):
        gate.coverage_result(report(0, 0))
    with pytest.raises(ValueError):
        gate.coverage_result(report(100, branch_coverage=False))


def test_complexity_boundary_and_nested_async_method():
    source = "class Example:\n    async def outer(self):\n        def nested():\n"
    source += "".join("            if True: pass\n" for _ in range(20))
    source += "        return nested()\n"
    source += "def at_limit():\n" + "".join("    if True: pass\n" for _ in range(19))
    units = {name: (score, rank) for _, name, score, rank in gate.complexity_units(ast.parse(source))}
    assert units["outer"] == (1, "A")
    assert units["nested"] == (21, "D")
    assert units["at_limit"] == (20, "C")


def test_foreground_module_stays_within_complexity_limit():
    path = Path(__file__).resolve().parents[1] / "windows_agent/gaming_control/foreground.py"
    units = list(gate.complexity_units(ast.parse(path.read_text(encoding="utf-8"))))
    assert units
    violations = [(name, score) for _, name, score, _ in units if score > gate.MAX_COMPLEXITY]
    assert not violations, violations


def test_mqtt_bridge_module_stays_within_complexity_limit():
    path = Path(__file__).resolve().parents[1] / "windows_agent/gaming_control/mqtt_bridge.py"
    units = list(gate.complexity_units(ast.parse(path.read_text(encoding="utf-8"))))
    assert units
    violations = [(name, score) for _, name, score, _ in units if score > gate.MAX_COMPLEXITY]
    assert not violations, violations
