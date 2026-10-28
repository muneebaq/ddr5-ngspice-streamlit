"""Bounded, reproducible optimization of a *surrogate* 1T1C DRAM model.

The surrogate screens candidates quickly. It is not a substitute for ngspice,
layout extraction, foundry device models, or real-world DDR5 design rules.
"""

from __future__ import annotations

import random


# Only the explicitly tunable circuit parameters are searched. The process
# parameters (L, VTO, KP) and testbench timing stay at the user's settings.
SEARCH_BOUNDS = {
    "cell_ff": (5.0, 50.0, 5.0),
    "bitline_ff": (100.0, 1000.0, 50.0),
    "supply": (0.90, 1.20, 0.05),
    "precharge_fraction": (0.30, 0.70, 0.05),
    "width_um": (0.5, 5.0, 0.5),
    "wordline_high": (1.20, 2.20, 0.05),
    "driver_ron": (10.0, 1000.0, 10.0),
}

OBJECTIVES = {
    "Balanced": (1.0, 0.35, 0.35, 0.20),
    "Maximum sensing margin": (1.40, 0.10, 0.15, 0.05),
    "Low switching energy": (0.80, 0.75, 0.20, 0.10),
    "Fast read access": (0.80, 0.20, 0.80, 0.10),
}


def snap(key: str, value: float) -> float:
    low, high, step = SEARCH_BOUNDS[key]
    count = round((min(high, max(low, value)) - low) / step)
    result = round(min(high, low + count * step), 5)
    return int(result) if step.is_integer() else result


def evaluate(parameters: dict, objective: str, limits: dict) -> dict:
    """Calculate explainable proxy metrics and a constrained ranking score."""
    c = float(parameters["cell_ff"])
    b = float(parameters["bitline_ff"])
    vdd = float(parameters["supply"])
    vpre = vdd * float(parameters["precharge_fraction"])
    # A simple NMOS threshold-limited high-level estimate; no body effect.
    cell_high = max(0.0, min(vdd, parameters["wordline_high"] - parameters["threshold"]))
    read_one = (c * cell_high + b * vpre) / (c + b)
    read_zero = b * vpre / (c + b)
    margin_mv = 1000 * min(read_one - vpre, vpre - read_zero)

    # Switching-energy and first-order RC-delay *proxies*, not power or tRCD.
    energy_fj = 0.5 * (c + b) * vdd**2
    overdrive = max(0.01, parameters["wordline_high"] - parameters["threshold"] - 0.5 * vdd)
    aspect = parameters["width_um"] / (parameters["length_nm"] / 1000.0)
    conductance_s = parameters["kp_ua"] * 1e-6 * aspect * overdrive
    access_ohm = 1 / max(conductance_s, 1e-12)
    cseries_ff = c * b / (c + b)
    delay_ns = 3 * (access_ohm * cseries_ff + parameters["driver_ron"] * b) * 1e-6
    area_proxy = 0.5 * (c / 20 + parameters["width_um"] * parameters["length_nm"] / 180)

    metrics = {
        "margin_mv": margin_mv,
        "energy_fj": energy_fj,
        "delay_ns": delay_ns,
        "area_proxy": area_proxy,
    }
    violation = (
        max(0.0, (limits["min_margin_mv"] - margin_mv) / max(limits["min_margin_mv"], 1))
        + max(0.0, (energy_fj - limits["max_energy_fj"]) / limits["max_energy_fj"])
        + max(0.0, (delay_ns - limits["max_delay_ns"]) / limits["max_delay_ns"])
        + max(0.0, (vdd - limits.get("max_vdd", 1.2)) / limits.get("max_vdd", 1.2))
        + max(0.0, (parameters["wordline_high"] - limits.get("max_wordline_high", 2.2)) / limits.get("max_wordline_high", 2.2))
    )
    weights = OBJECTIVES[objective]
    score = (
        weights[0] * margin_mv / 50
        - weights[1] * energy_fj / 200
        - weights[2] * delay_ns / 0.5
        - weights[3] * area_proxy
    )
    feasible = violation < 1e-9
    # Feasible candidates always outrank infeasible ones; if nothing is
    # feasible, the smallest normalized constraint violation is favored.
    rank = score if feasible else -100 - 100 * violation + 0.001 * score
    return {"parameters": dict(parameters), "metrics": metrics, "score": score,
            "rank": rank, "feasible": feasible, "violation": violation}


def _candidate(base: dict, tweaks: dict) -> dict:
    candidate = dict(base)
    candidate.update({key: snap(key, value) for key, value in tweaks.items()})
    return candidate


def random_search(base: dict, objective: str, limits: dict, budget: int, seed: int) -> dict:
    rng = random.Random(seed)
    best = evaluate(base, objective, limits)
    for _ in range(budget):
        tweaks = {key: rng.uniform(low, high) for key, (low, high, _) in SEARCH_BOUNDS.items()}
        trial = evaluate(_candidate(base, tweaks), objective, limits)
        if trial["rank"] > best["rank"]:
            best = trial
    return {**best, "algorithm": "Random search", "evaluations": budget + 1}


def coordinate_search(base: dict, objective: str, limits: dict, budget: int, seed: int) -> dict:
    rng = random.Random(seed + 17)
    current = evaluate(base, objective, limits)
    best = current
    keys = list(SEARCH_BOUNDS)
    for iteration in range(budget):
        key = keys[iteration % len(keys)]
        low, high, step = SEARCH_BOUNDS[key]
        change = rng.choice((-1, 1)) * rng.choice((step, step * 3, step * 8))
        trial = evaluate(_candidate(base, {**{k: current["parameters"][k] for k in keys},
                                           key: current["parameters"][key] + change}), objective, limits)
        if trial["rank"] > current["rank"]:
            current = trial
        if trial["rank"] > best["rank"]:
            best = trial
        # Escaping local optima periodically prevents the search from freezing.
        if iteration % 31 == 30:
            current = best
    return {**best, "algorithm": "Coordinate search", "evaluations": budget + 1}


def differential_evolution(base: dict, objective: str, limits: dict, budget: int, seed: int) -> dict:
    rng = random.Random(seed + 101)
    keys = list(SEARCH_BOUNDS)
    population_size = 12
    population = [dict(base)]
    while len(population) < population_size:
        population.append(_candidate(base, {
            key: rng.uniform(bounds[0], bounds[1]) for key, bounds in SEARCH_BOUNDS.items()
        }))
    scores = [evaluate(candidate, objective, limits) for candidate in population]
    count = population_size
    while count < budget:
        for i in range(population_size):
            if count >= budget:
                break
            others = [j for j in range(population_size) if j != i]
            a, b, c = rng.sample(others, 3)
            forced = rng.choice(keys)
            tweaks = {}
            for key in keys:
                if rng.random() < 0.75 or key == forced:
                    tweaks[key] = population[a][key] + 0.7 * (population[b][key] - population[c][key])
                else:
                    tweaks[key] = population[i][key]
            trial_p = _candidate(base, tweaks)
            trial = evaluate(trial_p, objective, limits)
            count += 1
            if trial["rank"] > scores[i]["rank"]:
                population[i] = trial_p
                scores[i] = trial
    best = max(scores, key=lambda result: result["rank"])
    return {**best, "algorithm": "Differential evolution", "evaluations": count}


def optimize_all(base: dict, objective: str, limits: dict, budget: int, seed: int) -> list[dict]:
    """Return the best of each method, sorted by constrained rank."""
    budget = max(24, min(400, int(budget)))
    return sorted([
        random_search(base, objective, limits, budget, seed),
        coordinate_search(base, objective, limits, budget, seed),
        differential_evolution(base, objective, limits, budget, seed),
    ], key=lambda result: result["rank"], reverse=True)
