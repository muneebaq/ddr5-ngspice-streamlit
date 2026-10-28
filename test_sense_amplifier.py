"""Non-ngspice regression tests for Lesson 3 netlist and measurements."""

import unittest

import pandas as pd

from sense_amplifier import DEFAULT_SENSE, analyze_sense_waveform, build_sense_netlist, ideal_charge_share


class SenseAmplifierTests(unittest.TestCase):
    def test_charge_sharing_baseline(self):
        one, zero = ideal_charge_share(20, 300, 1.1)
        self.assertAlmostEqual(one, 0.584375)
        self.assertAlmostEqual(zero, 0.515625)
        self.assertAlmostEqual(one - 0.55, 0.034375)

    def test_two_cross_coupled_latches_and_bitlines(self):
        text = build_sense_netlist(**DEFAULT_SENSE)
        for label in ("MNL1", "MNR1", "MPL1", "MPR1", "MNL0", "MNR0", "MPL0", "MPR0"):
            self.assertIn(label + " ", text)
        self.assertIn(".model PSENSE PMOS", text)
        self.assertIn(".model NSENSE NMOS", text)
        self.assertIn("wrdata waveform.txt", text)
        self.assertIn("VPREEN pre_en", text)
        self.assertIn("VSAN san", text)
        self.assertIn("VSAP sap", text)

    def test_rejects_out_of_bounds_inputs(self):
        params = dict(DEFAULT_SENSE)
        params["n_width_um"] = 1000
        with self.assertRaises(ValueError):
            build_sense_netlist(**params)

    def test_pass_and_fail_verification_metrics(self):
        v = 1.1
        # Samples at 3 ns (precharge), 7.8 ns (share), and 20 ns (latched).
        frame = pd.DataFrame([
            [3.0, 1.1, 0.55, 0.55, 0, 0.55, 0.55],
            [7.8, 0.584375, 0.584375, 0.55, 0.515625, 0.515625, 0.55],
            [20.0, 1.1, 1.1, 0, 0, 0, 1.1],
        ], columns=["Time (ns)", "Cell 1 (V)", "BL1 (V)", "REF1 (V)",
                    "Cell 0 (V)", "BL0 (V)", "REF0 (V)"])
        p = dict(DEFAULT_SENSE)
        result = analyze_sense_waveform(frame, p)
        self.assertTrue(result["pass"])
        self.assertAlmostEqual(result["read1_delta_mv"], 34.375)
        self.assertAlmostEqual(result["read0_delta_mv"], -34.375)
        frame.loc[2, "BL1 (V)"] = 0.55
        self.assertFalse(analyze_sense_waveform(frame, p)["latch_ok"])


if __name__ == "__main__":
    unittest.main()
