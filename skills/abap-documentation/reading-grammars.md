# Reading Grammars — where to start reading, per object flavor

> Deterministic reading order for every entry-point flavor. Use this at the
> start of every drill (Phase 3 / tree walk) to decide WHICH file to open
> FIRST and in what order to follow the chain. Following the wrong grammar is
> a root cause of hollow docs — an agent that starts in the wrong file ends up
> paraphrasing metadata instead of behaviour.

---

## 0. First move: classify the entry point BEFORE reading code

Never open the `.abap` file first. Open the **metadata XML** first — it tells
you which grammar applies:

| Entry point | Metadata to read first | Field that decides the grammar |
|---|---|---|
| T-Code | `*.tran.xml` | Transaction type + target (program / T-Code / class.method) |
| OData service | `*.iwsv.xml` + SICF node | Classic SEGW vs RAP (RAP has service binding `*.srvb.xml` instead) |
| SICF node | `*.sicf.xml` | Handler class list (`<ICFHANDLER>`) — the handler IS the entry point |
| Enhancement | `*.enho.xml` | Target spot (`ENH_BADI` / `ENH_HOOK` / `TGTNAME`) |
| RFC API | `*.fugr.<fm>.abap` with `REMOTE-ENABLED` | The FM signature is the contract |

---

## 1. Classic ABAP — T-Code grammar (five flavors)

The `.tran.xml` transaction type determines the true start:

### 1a. Report transaction (type: report/program with selection screen)
```
T-Code → program (*.prog.abap)
       → event blocks IN ORDER: INITIALIZATION → AT SELECTION-SCREEN →
         START-OF-SELECTION → (GET events) → END-OF-SELECTION
       → INCLUDEs (each may contain FORMs used by the main flow)
       → PERFORMs (local FORMs, or external: PERFORM f IN PROGRAM p)
       → CALL FUNCTION → function module → its function group → recurse
       → CALL METHOD / static class calls → class → recurse
       → SUBMIT <other program> → recurse into that program
```
Read the event blocks in runtime order, not file order — behaviour reads
top-down only if you follow the event sequence.

### 1b. Dialog transaction (module pool + dynpro)
```
T-Code → program (SAPM* / module pool)
       → screen flow logic (dynpro): PBO modules → PAI modules
       → each MODULE lives in an include (usually *_O01/*_I01 naming)
       → recurse into FMs / classes called from modules
```
**The dynpro flow logic is part of the behaviour.** A dialog-transaction doc
whose §4 only covers the TOP include has missed the screen logic — field
checks, CHAIN/ENDCHAIN validation, and OK-code dispatch all live there.

### 1c. Parameter transaction
```
T-Code (PGMNA empty) -> read TSTCP-PARAM from the *.tran.xml -- it names the target
  /*SM30 VIEWNAME=<v>;UPDATE=X|SHOW=X;   -> table / view maintenance
  /*SM34 VIEWCLUSTER=<vc>;               -> view-cluster maintenance
  /*START_REPORT ...REPORTTYPE=AQ;...    -> an SAP Query, NOT a program
  /*<TCODE> <field>=<value>;             -> parameter txn onto another T-Code
```
Do NOT chase a program — there isn't one of yours. For the maintenance forms the
reading order is:

1. `*.tran.xml` → `<PARAM>` → the view name (**often unrelated to the T-Code name,
   and sometimes lower-case** — take it from the parameter string, not the T-Code).
2. `*.tabl.xml` / `*.view.xml` → fields, keys, delivery class (`CONTFLAG`), base tables.
3. **`*.tobj.xml` — the maintenance object.** `TDDAT-CCLASS` is the table authorization
   class and belongs in §7; `TVIMF` (EVENT + FORMNAME) lists the TMG events that are
   actually wired and belongs in §4.
4. The generated maintenance function group. Read the wired event routines — and
   **enumerate the whole group**, because hand-written function modules are commonly
   parked in it. Those are reached by RFC or BAdI, never by the dialog.
5. Who *reads* the maintained table at runtime (`grep -ril <table>`) — a config table
   means nothing without its consumers, and that list is the real §1.

Two things not to write: `SHOW=X` is a default mode, not an access control; and a form
routine is neither live nor dead until you have checked *both* the `TVIMF` wiring and a
`PERFORM <form>` grep.

### 1d. Variant transaction
```
T-Code → target T-Code + variant → document as a THIN doc pointing at the
target T-Code's doc, listing what the variant pre-fills/hides and why.
```

### 1e. OO transaction
```
T-Code → class.method directly (no program)
       → read the method, then the class constructor + attributes it relies on
       → recurse into called methods / FMs
```

### Classic side doors (check in EVERY classic drill)
Behaviour hides outside the visible call chain. Grep the program + includes for:
- `SUBMIT` / `CALL TRANSACTION` — chains into other programs/T-Codes.
- `CALL CUSTOMER-FUNCTION` — user exit; the real code is in the EXIT_* FM's Z-include.
- `ENHANCEMENT-POINT` / `ENHANCEMENT-SECTION` — implicit/explicit enhancements.
- BAdI calls (`GET BADI` / `CALL BADI` / `cl_exithandler=>get_instance`).
- VOFM routines (`FRM_KONDI_WERT`, requirement/formula numbers) in SD pricing/output contexts.
- BTE / open FI events (`OPEN_FI_PERFORM_*`) in FI contexts.
- `PERFORM ... IN PROGRAM ...` — external subroutine calls that grep-by-FORM-name misses.

---

## 2. Classic SEGW OData — read BACKWARDS from the _EXT classes

```
SICF node (*.sicf.xml — get the handler + alias)
  → service registration (*.iwsv.xml → technical/external name)
  → MPC_EXT class: only if model is modified in code (rare) — else skip
  → DPC_EXT class ← START READING HERE
      → redefined methods only: *_GET_ENTITYSET, *_GET_ENTITY,
        *_CREATE_ENTITY, *_UPDATE_ENTITY, *_DELETE_ENTITY,
        /IWBEP/IF_MGW_APPL_SRV_RUNTIME~* (deep entity, batch, function imports)
      → helper classes / FMs the redefinitions call → recurse
      → CDS views or SELECTs they read → data model
```
The generated DPC/MPC **base** classes are noise — never document them
(rule 9); every behaviour lives in the `_EXT` redefinitions. If a DPC_EXT has
NO redefined methods, the service is either pure-CDS-mapped (check the MPC for
mapped CDS) or dead (flag in §9 Quirks).

---

## 3. RAP (ABAP RESTful Application Programming) grammar

```
Service binding (*.srvb.xml — OData V2/V4, UI/API)
  → service definition (*.srvd.*) — which entities are exposed
  → projection CDS views (*.ddls.asddls, usually C_* consumption views)
  → behavior definition (*.bdef.*) — managed/unmanaged, actions,
    determinations, validations, draft
  → behavior implementation class (the class named in the BDEF)
      → LOCAL HANDLER CLASSES inside the class's local-types include:
        lhc_* (handler: methods FOR MODIFY / FOR READ / actions /
        determinations / validations) and lsc_* (saver, unmanaged)
        ← THE BEHAVIOUR LIVES HERE, not in the global class
  → base CDS views (I_* / R_*) → tables
```
Also read the **projection behavior definition** (`use create` / `use action` —
the service's real write surface), the **metadata extensions** (`.ddlx`) and any
**access controls** (`.dcls`). One service definition with all its bindings is
one application and one document — see *RAP applications* in `SKILL.md`.

**The #1 RAP reading mistake:** opening the global behavior-implementation
class, seeing an empty public section, and concluding "no logic". The logic
is in the **local classes** (`lhc_*`/`lsc_*`) serialized in the class's
includes. Always read the local-types include.

---

## 4. CDS view grammar

```
Consumption view (C_*) → composite/interface views (I_*) → basic views → tables
```
- Read annotations first (`@OData.publish`, `@ObjectModel`, authorization
  `@AccessControl` + the DCL role if `#CHECK`) — they ARE behaviour.
- Follow associations only when exposed/used; note cardinality quirks in §9.
- Table functions → the AMDP class → SQLScript body (document in §4; flag
  HANA-only logic in §9).

---

## 5. Enhancement grammar

```
*.enho.xml → target spot (which BAdI definition / hook / spot)
  → the implementing class or hook include
  → read the TARGET's context first (what standard flow calls this spot,
    which parameters arrive) — the caller's context is what makes the
    impl's End-User Story writable
  → then the implementation code
```

---

## 6. Plain OO class grammar (load-bearing Z-classes)

```
Class → public interface first (public methods + interfaces implemented)
      → constructor (what state is built, what config is read at instantiation)
      → each public method in dependency order
      → protected/private only where public methods delegate into them
      → static factory patterns: find who calls the factory to learn the
        real consumers (grep the class name repo-wide)
```

---

## 7. Host families without ABAP files

```
E-mail template (*.smtg.xml)
      -> <HEADER><ID> (spaces/hyphens allowed), <PARENT_ID> = the SAP template copied
      -> <CDS_VIEW>: the placeholder data source
      -> subject / body: placeholders, and EVERY link (hard-coded hosts?)
      -> who sends it: search workflow tasks, classes and config for the ID

SAP query (<group> <query>.aqqu.xml)
      -> AQGQCAT: user group (NUM), query (QNUM), InfoSet (CLAS)
      -> the InfoSet (*.aqsg.xml): tables, joins, InfoSet coding
      -> selection and output texts (AQGTQ)
      -> the launching T-Code: a *.tran.xml whose PARAM has REPORTTYPE=AQ

BSP / UI5 app (<app>.wapa.xml)
      -> <app>.wapa.manifest.json: sap.app.id, dataSources -> the OData service
      -> continue with that service's grammar (2 or 3); the app is its UI
      -> reachability: launchpad target mapping (*.wdcc.xml) for the app id

BOR object type (<type>.sobj.xml)
      -> TOJTB-PARENT: subtype (read only its redefinitions) or stand-alone
      -> TOJTB-PROGNAME: the BOR program; read its BEGIN_METHOD blocks
      -> stand-alone copy of an SAP type? SAP note markers, German comments,
         no Z calls = frozen SAP code
      -> users: workflow tasks (*.pdts.xml), classes, event linkages naming the type
```

---

## Rule of thumb

If after applying the grammar you still can't say **who calls this and why**,
you started in the wrong file — go one level UP the grammar, not down.
Upstream context before downstream detail (this is also tree-walk
anti-pattern: never drill a callee before its caller).
