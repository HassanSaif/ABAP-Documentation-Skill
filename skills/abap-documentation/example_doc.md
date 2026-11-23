# Worked example — a compliant Full v1 per-object doc

> This file is a **reference for the model**, not a doc to copy into any repo. It shows what a passing 11-section doc looks like for a small fictional object. Note: every section is its own numbered `##` header; §9 is honest about defects; §11 separates read-from-code facts from naming-based guesses; the footer declares the tier.

---

# T-Code `ZMM_GRN_UPL` — Bulk goods-receipt upload from branch Excel files

> **Quick facts** · Module: MM · Type: T-Code → Program · Package: `ZMM_LOGISTICS` · T-Code path: ZMM_GRN_UPL · Handler: `ZMM_R_GRN_UPLOAD` · Source: `zmm_logistics/src/zmm_r_grn_upload.prog.abap`

---

## 1. End-User Story

A warehouse supervisor at a branch receives goods against multiple POs per day. Instead of posting MIGO line-by-line, they export the delivery note register to Excel, run ZMM_GRN_UPL, pick the file, and review a traffic-light ALV of validated rows before posting. Successfully posted rows show the material document number; failed rows show the exact BAPI error so the supervisor can correct the sheet and re-run only the failures.

---

## 2. Functional View *(for MM consultants)*

### 2.1 Module placement
- **Primary:** MM — Inventory Management (goods movements, movement type 101).
- **Cross-functional:** FI (accounting documents from GR posting).
- **Equivalent standard:** MIGO / `BAPI_GOODSMVT_CREATE`; this program is a mass-upload wrapper around the BAPI.

### 2.2 Inputs
Local Excel/CSV file (PO number, item, material, quantity, plant, storage location, delivery note); posting date from selection screen.

### 2.3 Outputs
Material documents (one per PO grouping); ALV log with per-row status; optional spool of the log.

### 2.4 Customising
Movement type is hard-coded (see §9) — no customising table. Tolerance behaviour inherits standard PO tolerance keys (details in §8).

---

## 3. Technical Overview

| Field | Value |
|---|---|
| Object type | T-Code → Executable program |
| Object name | `ZMM_GRN_UPL` / `ZMM_R_GRN_UPLOAD` |
| Package | `ZMM_LOGISTICS` |
| Source path | `zmm_logistics/src/zmm_r_grn_upload.prog.abap` |
| Entry-point | T-Code ZMM_GRN_UPL (SE93 → report transaction) |
| Handler / driver | `ZMM_R_GRN_UPLOAD` (uses class `ZCL_MM_FILE_PARSER`) |

### 3.1 Source-object table
| Object | Type | Role |
|---|---|---|
| `ZMM_R_GRN_UPLOAD` | PROG | Selection screen, orchestration, ALV |
| `ZCL_MM_FILE_PARSER` | CLAS | Excel/CSV → internal table, cell validation |
| `ZMM_GRN_LOG` | TABL | Custom log table, one row per upload line |

### 3.2 External dependencies
`BAPI_GOODSMVT_CREATE`, `BAPI_TRANSACTION_COMMIT`, `GUI_UPLOAD`. No RFC destinations, no HTTP.

---

## 4. Detailed Technical Spec

- **Selection screen (lines 18–41):** file path (F4 via `F4_FILENAME`), posting date (defaults `sy-datum`), test-run checkbox.
- **`START-OF-SELECTION` (lines 43–78):** instantiates `ZCL_MM_FILE_PARSER`, calls `parse_file( )` → `lt_rows`. Rows failing DDIC checks (material exists in MARA, plant in T001W) are flagged status `E` before any posting.
- **Posting loop (lines 80–142):** groups `lt_rows` by PO (`AT NEW ebeln` on a sorted copy), builds `goodsmvt_item` per group, movement type `'101'` literal (line 96). Calls the BAPI once per group; on success commits and writes `ZMM_GRN_LOG`; on error rolls back and copies the first `RETURN` message into the row.
- **ALV output (lines 144–171):** `CL_SALV_TABLE` with status icon column; double-click on a posted row calls `MIGO_DIALOG` display.
- Test-run flag skips the BAPI call entirely and marks rows `S (simulated)` — it does **not** use the BAPI's own test mode (see §9).

---

## 5. Database operations

| Table | Operation | When | Notes |
|---|---|---|---|
| `MARA` | SELECT SINGLE | Per row, validation | Keyed read, no buffering concern |
| `T001W` | SELECT SINGLE | Per row, validation | |
| `EKPO` | SELECT | Per PO group | Open-quantity check before posting |
| `ZMM_GRN_LOG` | INSERT | Per posted/failed row | No archiving concept — see §9 |

---

## 6. External calls

`BAPI_GOODSMVT_CREATE` (movement 101, one call per PO group; error handling: first E/A message surfaced, rollback via `BAPI_TRANSACTION_ROLLBACK`). `GUI_UPLOAD` for file read — GUI-only, fails in background (see §9).

---

## 7. Authorization

`AUTHORITY-CHECK OBJECT 'M_MSEG_WMB'` per plant before the posting loop (lines 84–88). Failure removes the plant's rows with status `E — no authorization`. T-Code itself gated by S_TCODE only.

---

## 8. Customising / Configuration dependencies

- PO tolerance keys (OMC0) apply through the BAPI — over-delivery beyond tolerance returns the standard M7 error; nothing custom.
- No custom config table controls this program (movement type hard-coded).

---

## 9. Quirks / observations *(developer punch-list)*

- Movement type `'101'` hard-coded at line 96 — returns/reversals impossible without a code change.
- `GUI_UPLOAD` makes the program GUI-only; scheduling it as a background job fails at runtime. A `SUBMIT ... VIA JOB` branch exists (lines 175–183) but is dead code — unreachable, never cleaned up.
- Test-run checkbox does not use the BAPI test mode — simulated rows skip open-quantity re-validation, so "green in test, red in real run" is possible.
- `ZMM_GRN_LOG` has no deletion/archiving path; table grows unbounded.
- Commented-out `BREAK-POINT` at line 91 with a developer username — debug remnant.

---

## 10. Cross-references

- **Upstream callers:** none (entry point).
- **Downstream callees:** [`ZCL_MM_FILE_PARSER`](../classes/ZCL_MM_FILE_PARSER.md).
- **Sister objects:** [`ZMM_GRN_REP`](../tcodes/ZMM_GRN_REP.md) (log-viewer T-Code over `ZMM_GRN_LOG`).
- **Related enhancements:** none found (grepped `ENHANCEMENT-POINT` / BAdI calls — none).
- **Related CDS:** none.

---

## 11. Inferences & assumptions

| Inference | Basis |
|---|---|
| Intended for branch warehouses without MIGO power users | Naming (`branch` in selection-screen text elements) + simplicity of the sheet format; not verifiable from code alone |
| The dead background-job branch was an abandoned requirement | Code present but unreachable (no path sets the triggering flag); no transport comment explains it |

---

*Doc version: v1 (Full deep drill) — 2026-07-27*
