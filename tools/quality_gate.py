"""Print quality metrics and fail on unmet project thresholds."""
import argparse
import ast
import json
from pathlib import Path
import sys

MIN_LINE_COVERAGE = 90
MAX_COMPLEXITY = 20


def coverage_result(report):
    totals = report["totals"]
    covered = totals["covered_lines"]
    statements = totals["num_statements"]
    if statements <= 0 or not 0 <= covered <= statements:
        raise ValueError("Invalid or empty line coverage report")
    if not report["meta"]["branch_coverage"]:
        raise ValueError("Branch coverage must be measured")
    branches = totals["num_branches"]
    covered_branches = totals["covered_branches"]
    if not 0 <= covered_branches <= branches:
        raise ValueError("Invalid branch coverage report")
    line_rate = 100 * covered / statements
    branch_rate = 100 * covered_branches / branches if branches else None
    return line_rate, branch_rate, covered * 100 >= MIN_LINE_COVERAGE * statements


def production_files(root):
    """Include all runtime Python files and entry points, not test/build output."""
    files = sorted((root / "custom_components" / "smarthouse_gaming").rglob("*.py"))
    windows = root / "windows_agent"
    files += sorted(windows.glob("*.py"))
    files += sorted((windows / "gaming_control").rglob("*.py"))
    if not (windows / "gaming_control").is_dir() or not (windows / "updater.py").is_file() or not files or not (root / "custom_components/smarthouse_gaming/manifest.json").is_file():
        raise ValueError("Production source tree missing")
    return files


def complexity_units(tree):
    from radon.complexity import cc_visit_ast, cc_rank

    # Score every named function, including async methods and nested functions,
    # independently. Do not use an average or a class aggregate as a unit.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            block = cc_visit_ast(ast.Module(body=[node], type_ignores=[]))[0]
            yield node.lineno, node.name, block.complexity, cc_rank(block.complexity)


def complexity_report(root):
    rows = []
    for path in production_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for line, name, score, rank in complexity_units(tree):
            rows.append({"file": path.relative_to(root).as_posix(), "line": line,
                         "unit": name, "complexity": score, "rank": rank})
    if not rows:
        raise ValueError("No production functions measured")
    rows.sort(key=lambda row: (-row["complexity"], row["file"], row["line"]))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="metric", required=True)
    coverage = sub.add_parser("coverage")
    coverage.add_argument("report", type=Path)
    complexity = sub.add_parser("complexity")
    complexity.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    complexity.add_argument("--output", type=Path, default=Path("complexity-report.json"))
    for command in (coverage, complexity):
        command.add_argument("--baseline", action="store_true", help="Report known threshold violations without enforcement during initial baseline measurement")
    args = parser.parse_args()
    if args.metric == "coverage":
        line, branch, passed = coverage_result(json.loads(args.report.read_text(encoding="utf-8")))
        print(f"Line coverage: {line:.2f}% (minimum {MIN_LINE_COVERAGE}%)")
        print(f"Branch coverage: {branch:.2f}%" if branch is not None else "Branch coverage: N/A")
        print("PASS" if passed else "FAIL: line coverage below target")
        if not passed and args.baseline:
            print("BASELINE ONLY: threshold not met; enforcement pending")
        return 0 if passed or args.baseline else 1
    rows = complexity_report(args.root)
    args.output.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    violations = [row for row in rows if row["complexity"] > MAX_COMPLEXITY]
    print(f"Measured {len(rows)} units; maximum allowed complexity C ({MAX_COMPLEXITY})")
    for row in violations:
        print(f"{row['file']}:{row['line']} {row['unit']}: {row['rank']} ({row['complexity']})")
    print(f"{len(violations)} violating units; worst score {rows[0]['complexity']}")
    if violations and args.baseline:
        print("BASELINE ONLY: threshold not met; enforcement pending")
    return 1 if violations and not args.baseline else 0


if __name__ == "__main__":
    sys.exit(main())
