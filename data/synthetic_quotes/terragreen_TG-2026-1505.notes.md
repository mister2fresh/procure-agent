# terragreen_TG-2026-1505 — SKU-typo fixture

Exercises the fuzzy-match cascade and the human-override picker end-to-end. Every line carries a deliberately mistyped SKU that should miss the exact-match tiers and land in `SUPPLIER_SKU_FUZZY` (or `DESCRIPTION_FUZZY` when the typo is too aggressive for trigram).

| line | typo'd SKU   | intended inventory | typo pattern              |
| ---- | ------------ | ------------------ | ------------------------- |
| 1    | `FME-50`     | `FEM-50`           | transposed letters        |
| 2    | `BLMD-50`    | `BLDM-50`          | transposed letters        |
| 3    | `ALFM50`     | `ALFM-50`          | missing dash              |
| 4    | `GRENS-CC`   | `GREENS-CC`        | dropped letter            |
| 5    | `BIOCH-2CFT` | `BIOCH-2CF`        | extra trailing letter     |

Some typos sit close to *sibling* SKUs (e.g. `FME-50` is also one edit away from `FBM-50` and `FEM-50`). The override picker is the safety net for cases where trigram lands on the wrong neighbor.
