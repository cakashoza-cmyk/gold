# Gold Desk · Surat/Gujarat

Public, zero-cost decision support for small jewellers, gold traders and families in Surat/Gujarat: should I buy my gold now, wait, or buy part now? Gold counterpart of [STTIE](https://github.com/cakashoza-cmyk/sttie), same structure and learning loop.

Live: https://cakashoza-cmyk.github.io/gold/ · Methodology: methodology.html

- `scripts/fetch.py` fetches public data into `data/live.json` (IBJA rates, COMEX gold via Sina [unofficial], RBI/FBIL, ECB, FRED, Google News RSS headlines).
- `scripts/model.py` computes the Indian premium vs import cost, back-tests the trader rules and the model, logs dated calls (`data/predictions.json`), scores matured ones, re-fits weights and writes `data/model.json`, `data/models/` and `data/track_record.csv`.
- `data/rates.json` holds customs duty, GST and the CBIC tariff value, checked by hand with notification links.
- `.github/workflows/refresh.yml` runs both at 08:30, 14:30 and 20:30 IST.
- `test/test_model.py` unit tests (`python3 -m unittest discover test`); `test/verify.py` browser check and screenshots.

No keys, no backend, no AI-generated numbers. User entries stay in the browser (localStorage). Not investment advice; no MCX or ETF calls.
