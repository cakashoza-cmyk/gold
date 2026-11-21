import copy, json, sys, unittest
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import technical as t  # noqa: E402

LIVE = json.loads((ROOT / "data/live.json").read_text())


class Indicators(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds, cls.c, cls.hi, cls.lo, cls.hl = t.series(LIVE)

    def test_series_has_high_low(self):
        self.assertTrue(self.hl); self.assertGreater(len(self.c), 2000)
        self.assertTrue(np.all(self.hi >= self.c) and np.all(self.lo <= self.c))

    def test_rsi_bounds(self):
        r = t.rsi(self.c); r = r[~np.isnan(r)]
        self.assertTrue(np.all((r >= 0) & (r <= 100)))
        up = np.arange(1, 100, dtype=float); self.assertGreater(t.rsi(up)[-1], 99)

    def test_sma_and_atr(self):
        x = np.arange(10, dtype=float); self.assertAlmostEqual(t.sma(x, 4)[-1], 7.5)
        a = t.atr(self.c, self.hi, self.lo); self.assertTrue(np.nanmin(a) > 0)

    def test_no_look_ahead_in_signals(self):
        n = len(self.c) - 60
        S1, _ = t.indicators(self.c[:n], self.hi[:n], self.lo[:n]); S2, _ = t.indicators(self.c, self.hi, self.lo)
        for k in S1:
            np.testing.assert_array_equal(np.nan_to_num(S1[k], nan=9), np.nan_to_num(S2[k][:n], nan=9), err_msg=k)

    def test_no_look_ahead_in_levels(self):
        n = len(self.c) - 60
        sl1, sh1 = t.swings(self.hi[:n], self.lo[:n]); sl2, sh2 = t.swings(self.hi, self.lo)
        for day in range(n - 300, n):
            for kind in ("sup", "res"):
                self.assertEqual(t.level_at(day, kind, self.c, self.hi, self.lo, sl1, sh1), t.level_at(day, kind, self.c, self.hi, self.lo, sl2, sh2))

    def test_swing_needs_confirmation(self):
        lo = np.array([9, 8, 7, 6, 5, 4, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12], dtype=float); hi = lo + 1; c = lo + 0.5
        sl, _ = t.swings(hi, lo); self.assertEqual(sl, [6])
        # the low on day 6 is confirmed by the close of day 11, so it can first be used on day 12
        self.assertIsNone(t.level_at(11, "sup", c, hi, lo, sl, [])); self.assertEqual(t.level_at(12, "sup", c, hi, lo, sl, []), 2.0)


class GateAndOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.T = json.loads((ROOT / "data/model.json").read_text())["technical"]

    def test_every_indicator_reported(self):
        self.assertEqual(set(self.T["indicators"]), set(t.NAMES))
        for k, v in self.T["indicators"].items():
            for h in t.HORIZONS:
                r = v[str(h)]
                for f in ("hit", "drift_hit", "mae", "mae_nochange", "mae_drift", "decision", "periods"):
                    self.assertIn(f, r, f"{k} {h}")

    def test_gate_logic(self):
        for k, v in self.T["indicators"].items():
            r = v[str(t.GATE_H)]
            self.assertEqual(v["passes_gate"], r["mae"] <= 0.99 * r["mae_drift"] and r["mae"] <= 0.99 * r["mae_nochange"], k)
        self.assertEqual(sorted(self.T["passed"]), sorted(k for k, v in self.T["indicators"].items() if v["passes_gate"]))

    def test_vote_only_from_passed(self):
        T = copy.deepcopy(self.T); T["passed"] = []
        self.assertEqual(t.vote(T), [])
        T["passed"] = ["ma20"]; T["now"]["signals"]["ma20"] = 1; self.assertEqual(t.vote(T), ["buy now"])
        T["now"]["signals"]["ma20"] = -1; self.assertEqual(t.vote(T), ["wait"])

    def test_levels_and_ranges_sane(self):
        n = self.T["now"]
        self.assertTrue(all(x < n["close"] for x in n["supports"])); self.assertTrue(all(x > n["close"] for x in n["resistances"]))
        for r in self.T["ranges"].values():
            self.assertLess(r["today_lo_pct"], 0); self.assertGreater(r["today_hi_pct"], 0)
            self.assertEqual(r["calibrated"], 75 <= r["coverage"] <= 85 and r["calm"] >= 70 and r["turbulent"] >= 70)
        ib = self.T["ibja"]; self.assertFalse(ib["testable"]); self.assertGreater(ib["ratio"], 0.9)


if __name__ == "__main__":
    unittest.main()
