"""Fast, offline tests for the bounded analytical design optimizer."""

import unittest

from optimizer import OBJECTIVES, SEARCH_BOUNDS, evaluate, optimize_all, snap


BASE = {
    "cell_ff": 20,
    "bitline_ff": 300,
    "supply": 1.10,
    "precharge_fraction": 0.50,
    "width_um": 1.0,
    "length_nm": 180,
    "threshold": 0.45,
    "kp_ua": 200,
    "wordline_high": 1.80,
    "driver_ron": 50,
    "time_scale": 1.0,
}
LIMITS = {"min_margin_mv": 20.0, "max_energy_fj": 250.0, "max_delay_ns": 1.0}


class OptimizerTests(unittest.TestCase):
    def test_baseline_charge_sharing(self):
        result = evaluate(BASE, "Balanced", LIMITS)
        self.assertAlmostEqual(result["metrics"]["margin_mv"], 34.375)
        self.assertTrue(result["feasible"])

    def test_more_bitline_capacitance_lowers_margin(self):
        baseline = evaluate(BASE, "Balanced", LIMITS)
        increased = evaluate({**BASE, "bitline_ff": 600}, "Balanced", LIMITS)
        self.assertLess(increased["metrics"]["margin_mv"], baseline["metrics"]["margin_mv"])

    def test_weak_wordline_reduces_read_one(self):
        good = evaluate(BASE, "Balanced", LIMITS)
        weak = evaluate({**BASE, "wordline_high": 1.2}, "Balanced", LIMITS)
        self.assertLess(weak["metrics"]["margin_mv"], good["metrics"]["margin_mv"])

    def test_snap_stays_bounded(self):
        for key, (low, high, _) in SEARCH_BOUNDS.items():
            self.assertEqual(snap(key, -100), low)
            self.assertEqual(snap(key, 1e6), high)

    def test_three_algorithms_are_reproducible(self):
        a = optimize_all(BASE, "Balanced", LIMITS, 72, 11)
        b = optimize_all(BASE, "Balanced", LIMITS, 72, 11)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 3)
        self.assertEqual({x["algorithm"] for x in a},
                         {"Random search", "Coordinate search", "Differential evolution"})
        self.assertGreaterEqual(a[0]["rank"], a[-1]["rank"])
        for winner in a:
            for key, (low, high, _) in SEARCH_BOUNDS.items():
                self.assertGreaterEqual(winner["parameters"][key], low)
                self.assertLessEqual(winner["parameters"][key], high)

    def test_each_objective_runs(self):
        for name in OBJECTIVES:
            with self.subTest(name=name):
                self.assertEqual(len(optimize_all(BASE, name, LIMITS, 24, 9)), 3)


if __name__ == "__main__":
    unittest.main()
