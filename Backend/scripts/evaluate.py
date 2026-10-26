"""Offline validator benchmark. No API calls and no model-as-judge grading."""

import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.validation import validate_itinerary
from app.schemas.planning import Evidence, Itinerary, Requirements


def main():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evals/cases.json").read_text())
    results = []
    for case in cases:
        sample = deepcopy(
            json.loads((root / "evals" / case.get("baseline", "baseline.json")).read_text())
        )
        for path, value in case["patches"]:
            target = sample
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        report = validate_itinerary(
            Itinerary.model_validate(sample["itinerary"]),
            Requirements.model_validate(sample["requirements"]),
            [Evidence.model_validate(e) for e in sample["evidence"]],
        )
        codes = {issue.code for issue in report.issues}
        errors = {issue.code for issue in report.issues if issue.severity == "error"}
        warnings = {issue.code for issue in report.issues if issue.severity == "warning"}
        correct = (
            report.passed == case["passed"]
            and set(case.get("codes", [])) <= codes
            and set(case.get("error_codes", [])) <= errors
            and set(case.get("warning_codes", [])) <= warnings
        )
        results.append(
            {
                "id": case["id"],
                "group": case.get("group", "specific"),
                "correct": correct,
                "expected_accepted": case["passed"],
                "actual_accepted": report.passed,
                "detected_codes": sorted(codes),
                "error_codes": sorted(errors),
                "warning_codes": sorted(warnings),
            }
        )
    total, passed = len(results), sum(r["correct"] for r in results)
    output = {
        "benchmark": "deterministic-validator-v2",
        "scope": "固定合成案例的约束检测；不代表真实生成成功率或零幻觉率",
        "total": total,
        "passed": passed,
        "accuracy": passed / total,
        "cases": results,
    }
    destination = root.parent / "docs/offline-evaluation.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"Validator cases: {passed}/{total}; report: {destination}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
