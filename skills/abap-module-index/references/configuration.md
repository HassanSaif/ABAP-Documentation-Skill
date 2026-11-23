# Configuration

Two files, two lifetimes.

| File | Lives | Contains |
|---|---|---|
| `scripts/defaults/sap-knowledge.json` | with the skill | knowledge true of **any** SAP system: standard tables per module, BAdI spots, SMOD exit includes, object types, role labels, fold edges, framework ignore lists |
| `module-index.config.json` | in the target repo | everything true of **one customer**: paths, module vocabulary, package map, naming conventions, local-language keywords, exclusions, tuning, thresholds |

Merge rule, applied per key, so a site can extend the knowledge base without forking it:

- **dict** — site entries override the defaults key by key
- **list** — site entries are *appended* to the defaults (they are knowledge you rarely
  want to lose). To replace instead: `{"replace": true, "values": [...]}`
- **scalar** — site value wins

A `knowledge` block in the site config is merged over the shipped knowledge by the same
rule. Use it for a genuinely local fact (an in-house naming layer, a customer-built
"standard" table). Keys starting with `_` are ignored by the build — that is where
`discover --adopt` parks decisions it will not make for you.

## Layouts and package sources

R1 (home package) is the only authoritative signal, and abapGit strips `<DEVCLASS>`
from every object file — an object never states its own package. So the package map
has to be recovered, and where from depends entirely on the layout:

| Layout | Looks like | Package from |
|---|---|---|
| flat export | `<root>/src/*.prog.abap`, no folders | **zips only** — the tree carries nothing |
| package-per-folder | `<root>/<PKG>/src/...` | the folder above `src/` (`tree`) |
| abapGit repo | `<root>/src/<subpkg>/...` + `.abapgit.xml` | subfolder names, read with FOLDER_LOGIC (`tree`) |
| monorepo of repos | `<root>/<any>/<PKG>/src/...` | as package-per-folder |

Providers run in configured order; the first to claim an object wins, later ones fill
gaps. Claims for objects the scan never saw are counted and dropped — a single stray
`$TMP.zip` in an export folder can claim tens of thousands of objects and bury every
real package in the report.

```json
"packages": {
  "providers": [
    {"type": "tree"},
    {"type": "zips", "path": "PACKAGE_SOURCES", "strip_prefixes": ["ACME_"]},
    {"type": "csv", "path": "exports/objects.csv",
     "object_column": "object_name", "package_column": "package",
     "type_column": "object_type"}
  ],
  "root_package": "ZFOO",
  "map": {"ZFOO_SD": ["SD"], "ZFOO_EINV": ["FI", "X_EINV"]},
  "excluded": ["ZABAP2XLSX", "ZABAP2XLSX_DEMOS"]
}
```

- `strip_prefixes` removes a project label some teams prepend to every export name
  (`ACME_ZFOO_SD.zip` → `ZFOO_SD`); `init` guesses it and `detect` shows what it
  guessed. Timestamp suffixes (`_20260716_172441`) are stripped automatically.
- `root_package` names the package of a flat `src/` when no folder does.
- A sub-package folder that already looks like a package name is taken as-is;
  otherwise it is a suffix on its parent (`src/demos/` → `ZABAP2XLSX_DEMOS`). Reading
  `demos` as a package called `DEMOS` is how a third-party demo sub-package escapes its
  own exclusion rule.

## Modules

```json
"modules": {
  "core": ["SD", "MM", "FI", "CO", "WM", "PP", "QM", "PM"],
  "buckets": {
    "X_EINV":      {"label": "eINV",      "description": "e-invoicing / statutory reporting (co-ticks FI)"},
    "X_ANALYTICS": {"label": "ANALYTICS", "description": "CDS / Fiori / OData analytics"},
    "X_TECH":      {"label": "TECH",      "description": "Basis / developer utility / framework"}
  },
  "open": true,
  "not_modules": {"PS": "0 objects write any PS table; the ZPS_* objects are WBS-settlement helpers owned by CO"}
}
```

- `core` — the modules this customer actually runs, decided from the source (the
  standard tables the custom code writes), not from this example or the default list.
  Add every module the evidence shows; narrow only with a measured reason. A column
  nobody owns is worse than no column — and a module the code proves but the list lacks
  is worse still.
- `buckets` — concerns rather than SAP modules. Name them `X_*` so they read as
  visibly different; `label` is the short header shown on sheet 1.
- `open` (default true) — a rule naming a module outside this vocabulary produces a
  **proposal with evidence** instead of silence. Turning it off is a decision to be
  told less than the tool knows; there is almost never a good reason.
- `not_modules` — areas a human looked at and ruled out. The reason is the point: it is
  the difference between a decision and an omission. This is the only sanctioned way to
  make a signal disappear.

### `std_name_wrappers` may name several modules

A knowledge-base entry is `[pattern, module]` or `[pattern, [module, module, …]]`.
Use the list form when a standard transaction belongs to one module and displays
another's data — `["^IH09", ["PM", "MM"]]`. **The first entry is the owner** and ranks
first for `primary_module`; the rest have a stake.

This matters most when one of them is out of scope. On an estate that declares PM
`not_modules`, `IH09` resolving to PM alone leaves every object built on it with no
module at all; resolving to PM *and* MM suppresses PM, records that it was named, and
ticks MM. Patterns are tried in file order and the first match wins, so a specific code
must be listed **before** the family pattern it belongs to.

### `modules.technical_bucket` and `modules.integration_bucket`

Two optional pointers that tell universal SAP knowledge which of *your* buckets it means.
The knowledge base uses the tokens `@TECHNICAL` and `@INTEGRATION` for things that are
not SAP modules — a SUSR0001 logon exit, an IDoc segment, a SmartStyle, an unreferenced
`CHAR30` data element — so the skill never has to invent a bucket name for a customer.

```json
"modules": {
  "technical_bucket": "X_TECH",
  "integration_bucket": "X_INTF"
}
```

A token with no bucket configured makes the rule **not fire** rather than fall back to a
core module it cannot justify. Without `technical_bucket` the "there is nothing here"
verdicts land in the note column instead of a tick, which is honest but leaves the
per-object coverage figure lower.

Do not point `integration_bucket` at a bucket that means something else. Aiming it at a
Basis/technical bucket makes R11 tick that bucket on every RFC-enabled function group
and throws the multi-module rate far out. If an estate wants its
RFC surface as a column, it needs its own column.

## Naming

```json
"naming": {
  "segment_blacklist": ["ENT1", "ENT2", "GRP", "IM", "REST", "EXCEL"],
  "families": [
    {"pattern": "^Z(XX_)?_?RF_", "modules": ["WM"],           "label": "RF handheld scanning"},
    {"pattern": "^ZXX_EINV_|^ZXX_EDOC_", "modules": ["FI","X_EINV"], "label": "e-invoicing"},
    {"pattern": "^Z(DS|C|I)_",    "modules": ["X_ANALYTICS"], "label": "CDS view"}
  ]
}
```

The blacklist is the highest-leverage setting in the file. `naming.token_map` and
`module_segments` are knowledge-level (put overrides under `knowledge.naming`) —
`module_segments: [1, 2]` means "the module token is in segment 2 or 3 of
`Z_A_B_...`", which is how a shared-layer convention like `ZXX_GRP_SD_*` is read
correctly.

Family rules are for whole prefixes owned by one area regardless of member naming.
Keep the patterns anchored (`^`); an unanchored family rule is a smearing machine.

### `naming.infrastructure_objects`

Names (or prefixes) of objects that are plumbing. Listed objects contribute no name,
table or field evidence to the units that use them; they still get their own row and
still appear as members.

```json
"naming": {
  "infrastructure_objects": ["Z_SHARED_API"]
}
```

The `fanin_gate` finds most infrastructure automatically, but it fires at an absolute
in-degree and an estate's central utility can sit just under it. Reach for this when the
module-share gate fails and the evidence lines on the excess ticks all name the same
member. Write down *why* in a sibling `_note` key — a silent entry here is
indistinguishable from a thumb on the scale.

## Text

```json
"text": {
  "secondary_script": "cyrillic",
  "keywords": {"SD": ["ЗАКАЗ", "КЛИЕНТ"], "FI": ["СЧЕТ", "НДС"]}
}
```

`secondary_script` splits bilingual short texts into `description_primary` /
`description_secondary` columns, so a consultant reads the local-language text and a
reviewer reads the English. Presets: `greek`, `cyrillic`, `arabic`, `hebrew`, `cjk`,
`thai`, `any-non-latin`; a raw character range also works. Keywords extend the English
defaults and only feed R8 (WEAK).

## Tuning and thresholds

```json
"tuning": {"max_hops": 6, "fanin_gate": 40, "tick_max_hop": 2, "pkg_max_hop": 3, "breadth_cap": 4},
"validation": {
  "thresholds": {"min_ticked_pct": 97.0, "multi_module_band": [10.0, 30.0],
                 "max_module_share_pct": 35.0, "min_content_name_agreement_pct": 80.0},
  "held_out": {"csv": "exports/atc.csv", "object_column": "object_name", "package_column": "package"},
  "assertions": [
    {"name": "every RF handheld unit ticks WM", "when_name_matches": "_RF_", "must_tick": ["WM"]},
    {"name": "everything in the SD package ticks SD", "when_package": "ZFOO_SD", "must_tick": ["SD"]}
  ]
}
```

`min_content_name_agreement_pct` gates the one check that validates the RULES rather
than the output: where a naming rule and the standard tables an object touches both have
an opinion, they should mostly agree. Below the threshold, a naming family has drifted from what the code actually does — the validation
report lists every conflict.

Thresholds exist so the report can state what it was measured against. Moving one to
make a gate pass converts a finding into a lie; fix the rule instead.

Assertions are the cheapest defence against systemic error, and the useful ones are
always local knowledge — "every handheld transaction must tick warehousing" catches a
whole class of misattribution in one line. Filters: `when_name_matches` (regex),
`when_package`, `when_role_contains`; `on_fail` can soften one to `WARN`. An assertion
matching zero units reports WARN, because a stale assertion protects nothing.

`held_out` takes any SAP-side export carrying object and package columns — ATC results,
a cloud-readiness check, an SE80 download, a custom-code register. Its `package` column
is never an input to the attribution, which is exactly what makes it evidence. Without
it the deliverable states, in writing, that R1 is unvalidated.

## Paths

```json
"paths": {
  "source_roots": ["src"],
  "work_dir": "utilities/module-index",
  "out_dir": "utilities/module-index",
  "out_prefix": "appendix-module-index",
  "mirrors": ["docs/module-index"]
}
```

`work_dir` holds the cached intermediates and the override file; `out_dir` holds the
deliverable. `mirrors` copies the deliverable on every render — worth setting when
people open the workbook from a second location, because a hand-made copy goes stale
without anyone noticing.

## Steps, caching and staleness

```
scan → packages → graph → units → attribute → discover → overrides → render → validate
```

`scan` is the only step that reads the source tree. Each step records a fingerprint of
the config sections it depends on; starting mid-pipeline after changing an earlier
step's inputs is refused, with the step to restart from named. `--force` overrides.

Common restart points: changed a rule table or the module list → `--from attribute`;
changed exclusions or fold behaviour → `--from units`; changed the package map →
`--from packages`.
