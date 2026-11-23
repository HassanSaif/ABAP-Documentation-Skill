# Module Vocabulary — Per-Module Functional Cheat Sheets

> Reference cards for §2 "Functional View" of each per-object drill-down. Each card lists what the module consultant cares about, the tables most likely to appear in the source-object table, common BAPIs/FMs to mention under "equivalent SAP standard", and the customising hooks worth a sentence in §8.
>
> **This is guidance, not a closed list** (hard rule 5). The modules below are the common ones, not all the modules a system can run. Place every object from what its code does — tables written first, then tables read, BAPIs/FMs called — and name the module that evidence points to even when it has no card here (EWM, TM, GTS, PS, QM, HCM, Treasury, Real Estate, IS-* industry solutions, …). When you meet such a module, say so in the doc; do not force the object into the nearest card.
>
> Use this when you don't have a module consultant to ask. **Do not** copy-paste the entire card into every doc — pick the bullets that actually apply to the object you're drilling.

---

## SD — Sales & Distribution

**What the consultant cares about:**
- Document flow: quotation → sales order → delivery → billing → accounting.
- Pricing: condition technique, access sequences, condition records, pricing procedure determination.
- Partner determination (sold-to, ship-to, bill-to, payer).
- Output determination (printouts, EDI, emails — NACE).
- Item categories, schedule lines, availability check (ATP).
- Credit management (FSCM-CR or classic).

**Tables most likely to mention:**
- Headers: `VBAK` (sales order), `LIKP` (delivery), `VBRK` (billing), `VBKD` (sales-business data).
- Items: `VBAP` (sales-order item), `LIPS` (delivery item), `VBRP` (billing item).
- Partners: `VBPA`. Conditions: `KONV` / `PRCD_ELEMENTS` (S/4). Status: `VBUK`/`VBUP`.
- Document flow: `VBFA`. Schedule lines: `VBEP`.

**Common BAPIs / FMs to reference:**
- Create / change order: `BAPI_SALESORDER_CREATEFROMDAT2`, `SD_SALESDOCUMENT_CREATE`, `BAPI_SALESORDER_CHANGE`.
- Delivery: `BAPI_OUTB_DELIVERY_CREATE_SLS`, `WS_DELIVERY_UPDATE_2`, `GN_DELIVERY_CREATE`.
- Billing: `BAPI_BILLINGDOC_CREATEMULTIPLE`.
- Pricing: `PRICING`, `PRICING_REFRESH`.

**Customising hooks to check (§8):**
- IMG SD → Sales → Sales Documents → Define / assign document types (T-Code VOV8).
- Pricing procedure determination (V/08, OVKK).
- Partner determination procedure (VOPA).
- Output determination (NACE / V/57).

---

## MM — Materials Management

**What the consultant cares about:**
- Purchase requisition → PO → goods receipt → invoice receipt → payment.
- Source determination, source list, contracts, scheduling agreements.
- Stock types (unrestricted, blocked, quality, GR-blocked, consignment, special).
- Batch management, valuation (moving-average vs standard).
- MRP run, planned orders, lot-sizing.

**Tables most likely to mention:**
- Material master: `MARA`, `MARC` (plant), `MBEW` (valuation), `MARD` (storage location), `MAKT` (descriptions).
- Purchasing: `EKKO` (PO header), `EKPO` (PO item), `EKBE` (PO history), `EKES` (confirmations).
- PR: `EBAN`. Source list: `EORD`. Contracts/agreements use `EKKO/EKPO` with type.
- Inventory docs: `MKPF` (header), `MSEG` (item). Stocks: `MARD`, `MCHB` (batch).
- Invoice verification: `RBKP` (header), `RSEG` (item).

**Common BAPIs / FMs to reference:**
- PO: `BAPI_PO_CREATE1`, `BAPI_PO_CHANGE`, `ME_PROCESS_PO_CUST`.
- PR: `BAPI_PR_CREATE`, `BAPI_REQUISITION_CREATE`.
- GR: `BAPI_GOODSMVT_CREATE` (with movement type 101/102/...).
- IV: `BAPI_INCOMINGINVOICE_CREATE` / `MRM_INVOICE_DOCUMENT_CREATE`.

**Customising hooks to check (§8):**
- Document type definition (OMEC / OLME for PO).
- Movement-type config (OMJJ / OMBA).
- Number range assignment.
- Release strategy (OMGS for PR, OMGSCK for PO).

---

## FI / FI-AR / FI-AP — Financial Accounting

**What the consultant cares about:**
- Document type, posting key, special G/L indicator.
- Company code, chart of accounts, ledgers (parallel ledgers in New G/L / Universal Journal).
- Open-item management, clearing (manual / automatic via F.13).
- Payment terms (`ZTERM`), dunning levels, withholding tax.
- Down-payment requests, down-payment clearing.
- Tax codes (`MWSKZ`), tax procedure.

**Tables most likely to mention:**
- Document headers: `BKPF`. Items: `BSEG`. Open / cleared splits: `BSID`/`BSAD` (customer), `BSIK`/`BSAK` (vendor), `BSIS`/`BSAS` (G/L).
- S/4 Universal Journal: `ACDOCA`. Asset accounting: `ANLA`, `ANLB`, `ANLC`.
- Customer master: `KNA1`, `KNB1`, `KNBK`. Vendor master: `LFA1`, `LFB1`.
- Down payments: special G/L → `BSEG`-`UMSKZ` field.

**Common BAPIs / FMs to reference:**
- Post document: `BAPI_ACC_DOCUMENT_POST`, `BAPI_ACC_GL_POSTING_POST`.
- Customer / vendor invoice: `BAPI_ACC_INVOICE_RECEIPT_POST`.
- Down-payment: `BAPI_ACC_DOWN_PAYMENT_POST`.
- Clearing: `POSTING_INTERFACE_CLEARING`, FI_F-32 / F-44 / F-04 / F-13.

**Customising hooks to check (§8):**
- Document type (OBA7), posting key (OB41), special G/L indicators (OBYR).
- Payment program (FBZP), dunning (FBMP).
- Tax codes (FTXP). G/L master extension (FS00).

---

## CO — Controlling

**What the consultant cares about:**
- Cost centers, internal orders, profit centers, segments (S/4 universal journal).
- Cost-element accounting (primary / secondary).
- COPA (profitability analysis — costing-based vs account-based).
- Allocations: assessment, distribution, periodic reposting.
- Product costing (CK11N / CK24).

**Tables most likely to mention:**
- Cost-center master: `CSKS`, `CSKT`. Cost elements: `CSKB` (primary), `CSKA` (secondary in classic).
- Internal orders: `AUFK`. Profit center: `CEPC`.
- Line items (classic): `COBK`, `COEP`, `COSP`, `COSS`. **In S/4: read from `ACDOCA` instead.**
- COPA characteristics / value fields: `CE1xxxx`/`CE3xxxx` (xxxx = operating concern).

---

## PM / EAM — Plant Maintenance / Enterprise Asset Management

**What the consultant cares about:**
- Notification (`QMEL`) → work order (`AUFK`/`AFKO`) → confirmation → settlement.
- Equipment / functional location hierarchy.
- Task lists, maintenance plans, maintenance items.
- Catalog (code / code group / catalog profile).

**Tables most likely to mention:**
- Notifications: `QMEL`, `QMIH`, `QMFE` (items), `QMUR` (causes), `QMMA` (activities), `QMSM` (tasks).
- Orders: `AUFK` (header), `AFKO` (PP/PM order header), `AFVC` (operations), `AFVV` (op-quantities), `RESB` (reservations).
- Equipment: `EQUI`, `EQKT`, `EQUZ` (usage period). Functional location: `IFLO`, `ILOA`.
- Confirmations: `AFRU`.

**Common BAPIs / FMs:**
- Notification: `BAPI_ALM_NOTIF_CREATE`, `BAPI_ALM_NOTIF_DATA_MODIFY`.
- Order: `BAPI_ALM_ORDER_MAINTAIN`.
- Confirmation: `BAPI_PRODORDCONF_CREATE_HDR`, `IWO_BAPI_CONF_CREATE`.

---

## PS — Project System

**What the consultant cares about:**
- Project definition → WBS elements → networks → activities.
- Budget vs commitments vs actuals; availability control (AVAC).
- Milestones, milestone billing.
- Settlement rules (WBS → cost center, AuC, etc.).

**Tables most likely to mention:**
- `PROJ` (definition), `PRPS` (WBS), `AUFK`+`AFKO`+`AFVC` (network), `JEST`/`JCDS` (system status).
- Budget: `BPGE`, `BPJA`. Settlement: `AUAK`, `AUAA`.

---

## PP — Production Planning

**What the consultant cares about:**
- Demand → planned order → production order → confirmation → goods movement.
- BOM (`STKO`/`STPO`), routing (`MAPL`/`PLPO`/`PLAS`), work centers (`CRHD`).
- MRP run (MD01 / MD02 / MD03), planning evaluation (MD04).
- Capacity planning, scheduling.

**Tables most likely to mention:**
- Headers: `AUFK`, `AFKO` (order), `PLAF` (planned order).
- BOM: `STKO` (header), `STPO` (item), `MAST` (assignment).
- Routing: `MAPL` (assignment), `PLKO` (header), `PLPO` (operations).
- Work center: `CRHD`, `CRCO`.

---

## HR / HCM

**What the consultant cares about:**
- Personnel number (`PERNR`) and infotypes — `PAxxxx` tables.
- Org structure: organizational units, positions, jobs (`HRP1000` etc.).
- Payroll periods, time-management types.
- Authorization: structural authorizations override standard auth-objects.

**Tables most likely to mention:**
- Master data: `PA0000`–`PA0999` (infotypes 0–999 per `PERNR`).
- Org management: `HRP1000`, `HRP1001`, `HRT1xxx`, `HRSP*`.
- Time / payroll: `PA2001`, `PA2002`, `PCL2` cluster.

**Common FMs:**
- `HR_READ_INFOTYPE` (read), `HR_INFOTYPE_OPERATION` (write).
- `BAPI_EMPLOYEE_ENQUEUE` / `_DEQUEUE`.

---

## VSS / Automotive Service (sector-specific add-on, e.g. DBE)

> If you encounter `/DBE/` or `/DBME/` partner namespace, that's the DBE Automotive Service Solution sitting on top of standard SD / PM. Treat behaviour in those namespaces as black-box partner code — document the **functional purpose / consumer / data domain**, not the implementation.

**What the consultant cares about:**
- Vehicle master: VIN, model, brand, body, trim, fuel type, colour.
- Service contracts (sales item types Z*-contract-categories).
- Branch / plant configuration; sales-org × distribution-channel × division × division-specific brands.
- Appointment booking, service-order (special PM order category).
- Buyback, trade-in, recall campaigns.

**Tables most likely to mention:**
- Vehicle master tables in the partner namespace (e.g. `/DBE/`) or a customer `Z*` namespace (installation-specific — confirm in the repo).
- SD contracts use `VBAK`/`VBAP` with item categories from the customer-specific table.

---

## Cross-cutting topics

### Workflows (SAP Business Workflow)
- Tasks: `TS` (standard), `WS` (template). Containers in workflow definitions.
- Definitions in `SWDD`. Inbox in `SBWP`. Logs in `SWI1`.
- Start-conditions: triggered by events (`SWEC` / `SWE2`).

### Enhancements (overview)
- **User exits / customer exits** (legacy — `SMOD` / `CMOD`) — function modules `EXIT_*` and `INCLUDE_*`.
- **BAdIs (classic & new)** — registered in `SE18` / implemented in `SE19`.
- **Implicit / explicit enhancement points (CLASENH / HOOK)** — managed in `SE80` enhancement framework.
- The skill's `enho.tsv` capture covers BAdI / Hook / CLASENH equally.

### Output management
- **NACE** (output determination) — connects an output type to a print program + form (SmartForm / SAPscript / Adobe form).
- For Z-print programs, the form is named in `TNAPR` and triggered via output condition records.

### Authorizations to call out in §7
- `S_TCODE` — always implied for T-Codes; mention only if there's a non-trivial fallback.
- `S_RFC` for RFC-callable FMs.
- `S_DEVELOP` if the code self-creates / debugs.
- Module-specific auth objects: `V_VBAK_VKO` (sales-area for SD doc), `M_BEST_BSA` (PO document type), `F_BKPF_BUK` (FI doc by company code), `I_*` (PM), `P_*` (HR — structural).
