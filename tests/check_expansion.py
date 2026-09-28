"""Independent checks and fixtures for recruitment expansion."""
from pathlib import Path
from collections import Counter
from itertools import combinations
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"


def read(path):
    return json.loads(path.read_text())


def support_cost(row):
    return max(0, (row["support"] or 0) - 1) if row["status"] == "recruit" else 0


def cost(row, weight_q):
    if row["status"] == "story":
        return 0
    return 4 * row["renown"] + weight_q * support_cost(row)


def expand(rows, base_ids, routes, weight_q=4, budget=43, keep_gate=False, excluded=()):
    """Budget is additional joins. Exclusions remove recommendations without refilling."""
    assert isinstance(weight_q, int) and 1 <= weight_q <= 24
    assert isinstance(budget, int) and budget >= 0
    by_id = {r["id"]: r for r in rows}
    assert len(by_id) == len(rows) and len(base_ids) == len(set(base_ids))
    base = [by_id[k] for k in base_ids]
    people = sorted({r["characterId"] for r in rows})
    occurrences = Counter(r["characterId"] for r in base)
    assert set(occurrences) == set(people) and all(v == 1 for v in occurrences.values())
    assert all(r["status"] != "no" for r in base)
    assert {r["id"] for r in rows if r["status"] == "story"} <= set(base_ids)
    available = {n: [r for r in rows if r["characterId"] == n and r["status"] != "no"] for n in people}
    upper = sum(min(2, len(rs)) for rs in available.values())
    assert budget <= upper - len(base)
    gates = {route: max([2] + [r["renown"] or 0 for r in base if r["routeId"] == route]) for route in routes}
    counts = Counter(r["routeId"] for r in base if r["status"] != "story")
    candidates = []
    for options in available.values():
        if len(options) < 2:
            continue
        threshold = sorted(cost(r, weight_q) for r in options)[1]
        candidates += [r for r in options if r["id"] not in base_ids
                       and cost(r, weight_q) <= threshold
                       and (not keep_gate or r["renown"] <= gates[r["routeId"]])]
    remaining = list(candidates)
    automatic = []
    route_rank = {r: i for i, r in enumerate(routes)}
    while remaining and len(automatic) < budget:
        row = min(remaining, key=lambda r: (
            cost(r, weight_q), counts[r["routeId"]], r["renown"], r["support"],
            r["rank"], route_rank[r["routeId"]]))
        remaining.remove(row)
        automatic.append(row)
        counts[row["routeId"]] += 1
    added = [r for r in automatic if r["id"] not in excluded]
    final = base + added
    multiplicity = Counter(r["characterId"] for r in final)
    result = {
        "upper": upper, "eligibleCount": len(candidates),
        "baseIds": sorted(base_ids), "automaticIds": [r["id"] for r in automatic],
        "addedIds": [r["id"] for r in added],
        "candidateIds": sorted(r["id"] for r in candidates),
        "total": len(final), "added": len(added),
        "frequency": {str(k): v for k, v in sorted(Counter(multiplicity.values()).items())},
        "r": sum(r["renown"] or 0 for r in final),
        "s": sum(support_cost(r) for r in final),
        "addedCostQ": sum(cost(r, weight_q) for r in added),
        "recruitCounts": [sum(r["routeId"] == route and r["status"] != "story" for r in final) for route in routes],
        "gates": [max([2] + [r["renown"] or 0 for r in final if r["routeId"] == route]) for route in routes],
    }
    assert len(final) == len({r["id"] for r in final}) <= upper
    assert set(multiplicity) == set(people)
    assert sum(int(k) * v for k, v in result["frequency"].items()) == len(final)
    assert len(automatic) == min(budget, len(candidates))
    # Independent primary cost check: no count-balancing tie break may select a more expensive row.
    assert sum(cost(r, weight_q) for r in automatic) == sum(sorted(cost(r, weight_q) for r in candidates)[:budget])
    return result


def fixture_data():
    identities = read(SOURCE / "identities.json")
    data = read(SOURCE / "assets/recruitment-data.json")
    results = read(SOURCE / "assets/optimization-results.json")
    characters = {r["sourceName"]: r for r in identities["characters"]}
    routes = {r["sourceName"]: r for r in identities["routes"]}
    def pair(r):
        return characters[r["name"]]["id"] + "@" + routes[r["route"]]["id"]
    rows = [dict(r, id=pair(r), characterId=characters[r["name"]]["id"],
                 routeId=routes[r["route"]]["id"], rank=characters[r["name"]]["rank"]) for r in data["rows"]]
    best = min(results["inclusive"]["balanced_frontier"], key=lambda p: (p["r"]+p["s"], p["delta"], p["s"]))
    base = best["assignment"] + [r for r in data["rows"] if r["status"] == "story" and r["name"] not in data["targets"]]
    base_ids = sorted(pair(r) for r in base)
    plan_id = "p-" + hashlib.sha256("\n".join(base_ids).encode()).hexdigest()[:16]
    version_inputs = {f: read(SOURCE / f) for f in ["assets/recruitment-data.json", "assets/optimization-results.json", "recruitment-extras.json", "later-characters.json"]}
    version_inputs["identities.json"] = identities
    data_version = hashlib.sha256(json.dumps(version_inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    ordered_routes = [r["id"] for r in identities["routes"]]
    common = (rows, base_ids, ordered_routes)
    cases = {
        "default": expand(*common),
        "keep_gate": expand(*common, keep_gate=True),
        "zero_budget": expand(*common, budget=0),
        "one_extra": expand(*common, budget=1),
    }
    removed = cases["default"]["automaticIds"][0]
    cases["remove_without_refill"] = expand(*common, excluded=[removed])
    assert cases["zero_budget"]["total"] == 50 and cases["one_extra"]["total"] == 51
    assert cases["remove_without_refill"]["total"] == 92
    assert set(cases["remove_without_refill"]["addedIds"]) == set(cases["default"]["addedIds"]) - {removed}
    # Confirm high and low weights retain constraints, without claiming a fixture optimum for route balance.
    for q in (1, 24):
        expand(*common, weight_q=q)
    return {"dataVersion": data_version, "defaultBasePlanId": plan_id, "cases": cases}


def synthetic_checks():
    routes = ["a", "b", "c", "d"]
    rows = []
    # One cheap character on all four routes; two others have expensive second choices;
    # the fourth can only join one route. Global cap still permits the cheap character four times.
    for i, values in enumerate(([2, 2, 2, 2], [3, 20, None, None], [4, 20, None, None], [5, None, None, None])):
        for j, value in enumerate(values):
            rows.append({"id": f"x{i}@{routes[j]}", "characterId": f"x{i}", "routeId": routes[j],
                         "rank": i, "status": "no" if value is None else "recruit",
                         "renown": value, "support": None if value is None else 0})
    base = [f"x{i}@a" for i in range(4)]
    got = expand(rows, base, routes, budget=3)
    assert got["upper"] == 7 and got["total"] == 7 and got["frequency"] == {"1": 3, "4": 1}
    candidates = [r for r in rows if r["id"] in got["candidateIds"]]
    # Exhaustive independent oracle for primary cost on this small case.
    assert got["addedCostQ"] == min(sum(cost(r, 4) for r in subset) for subset in combinations(candidates, 3))
    # Order statistic includes repeated values: 5,5,9,11 admits only the first two routes.
    example = [dict(r, renown=v) for r, v in zip(rows[:4], (5, 5, 9, 11))]
    example += rows[4:]
    second = expand(example, base, routes, budget=3)
    assert "x0@b" in second["candidateIds"] and "x0@c" not in second["candidateIds"]


if __name__ == "__main__":
    synthetic_checks()
    result = fixture_data()
    path = ROOT / "tests/fixtures/expansion.json"
    if "--write-fixtures" in sys.argv:
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        assert read(path) == result, "Fixture mismatch: investigate; do not blindly regenerate."
    print("PASS: five real-data fixtures, 3/4-route eligibility, repeated-cost threshold, no-refill exclusions, and independent primary-cost checks.")
    print("dataVersion:", result["dataVersion"])
    print("defaultBasePlanId:", result["defaultBasePlanId"])
