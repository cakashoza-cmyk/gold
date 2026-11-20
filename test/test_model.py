import json, sys, unittest
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import model as m  # noqa: E402


class Rules(unittest.TestCase):
    def test_dip_and_premium_calls(self):
        self.assertEqual(m.dip_call(-3.5), "buy now"); self.assertEqual(m.dip_call(3.0), "wait"); self.assertIsNone(m.dip_call(1.0)); self.assertIsNone(m.dip_call(None))
        self.assertEqual(m.prem_call(2.5), "wait"); self.assertEqual(m.prem_call(-2.5), "buy now"); self.assertIsNone(m.prem_call(0.5))

    def test_combine_and_gate(self):
        self.assertEqual(m.combine(["buy now", None]), "buy now"); self.assertEqual(m.combine(["buy now", "wait"]), "buy part"); self.assertEqual(m.combine([None, None]), "buy part")
        act = {"dip_buy": True, "dip_wait": False, "prem_buy": False, "prem_wait": False}
        self.assertEqual(m.gate("buy now", "dip", act), "buy now"); self.assertIsNone(m.gate("wait", "dip", act)); self.assertIsNone(m.gate("wait", "prem", act))

    def test_call_hit(self):
        self.assertTrue(m.call_hit("buy now", 1.0, 30)); self.assertFalse(m.call_hit("buy now", -1.0, 30))
        self.assertTrue(m.call_hit("wait", -0.5, 30)); self.assertTrue(m.call_hit("buy part", 1.9, 30)); self.assertFalse(m.call_hit("buy part", 2.1, 30))

    def test_duty_schedule(self):
        r = json.loads((ROOT / "data/rates.json").read_text())
        self.assertEqual(m.duty_on(r, date(2026, 11, 20)), 15); self.assertIsNone(m.duty_on(r, date(2026, 5, 12)))
        self.assertEqual(r["bcd_pct"]["value"] + r["aidc_pct"]["value"] + r["sws_pct"]["value"], 15)

    def test_duty_cut_regex(self):
        import re
        for t in ["Govt may cut gold import duty to 6%", "Gold import duty cut likely in Budget", "Centre considers reducing customs duty on gold"]:
            self.assertTrue(re.search(m.DUTY_CUT, t, re.I), t)
        for t in ["Gold price crash: metal slumps 4% on MCX", "Gold rate today in Surat"]:
            self.assertFalse(re.search(m.DUTY_CUT, t, re.I), t)


class Outputs(unittest.TestCase):
    def setUp(self):
        self.live = json.loads((ROOT / "data/live.json").read_text()); self.model = json.loads((ROOT / "data/model.json").read_text())
        self.pred = json.loads((ROOT / "data/predictions.json").read_text())

    def test_premium_formula(self):
        rates = json.loads((ROOT / "data/rates.json").read_text())
        rows, ds = m.build(self.live)
        ps = m.premium_series(self.live, rates, rows, ds)
        d, v = ps[-1]
        it = self.live["items"]
        g = m.Series(it["comex"]["history"]); fx = m.Series(it["usdinr_ecb"]["history"]); ib = dict(it["ibja999_pm"]["history"])
        dd = m.D(d); ref = (g.before(dd) + g.at(dd)) / 2
        landed = ref * fx.at(dd) / m.OZ * 10 * 1.15
        self.assertAlmostEqual(v, round(100 * (ib[d] / landed - 1), 2), places=2)
        self.assertTrue(-15 < v < 15)

    def test_gate_honesty(self):
        for h in ("7", "30"):
            hz = self.model["horizons"][h]; b = self.model["backtest"][h]
            if not any(hz["gate"]["mask"]):
                self.assertTrue(all(w == 0 for w in hz["weights"].values()))
                self.assertEqual(b["mae_pct"], b["naive_mae_pct"])
            else:
                self.assertLess(b["mae_pct"], b["naive_mae_pct"])

    def test_every_item_has_source_and_date(self):
        for k, v in self.live["items"].items():
            for f in ("source", "source_url", "as_of", "status", "unit"):
                self.assertTrue(v.get(f), f"{k}.{f}")

    def test_ledger_calls_valid(self):
        calls = [p for p in self.pred["predictions"] if p["kind"] == "call"]
        self.assertTrue(calls)
        for p in calls:
            self.assertIn(p["buy_call"], ("buy now", "wait", "buy part"))
            if p.get("news_flag"):
                self.assertNotEqual(p["buy_call"], "buy now")


if __name__ == "__main__":
    unittest.main()
