# Method — units, the rule ladder, and the brakes

## 1. The unit model

A **unit** is an entry point plus its entire nesting. Members are found by BFS over
"this target is part of my implementation" edges, up to `tuning.max_hops` (default 6).

Root kinds, in resolution order. Order matters: everything reachable from a primary
root is a member, so orphan roots can only be claimed after the primary sweep.

| Class | Types | Notes |
|---|---|---|
| primary | TRAN, IWSG/IWSV/IWPR, SICF, ENHO, SXCI, CMOD, DDLS, DDLX, SRVB, SRVD, WEBI, WDYN, SPRX | the things a user or a system can actually enter through |
| fallback | PROG, CLAS, FUGR, INTF reachable from nothing | real code with no entry point — itself a finding, not a gap |
| extra | SSFO, FORM, SFPF, SFPI, XSLT, SCVI, STVI | no inbound edge in any static export; they would vanish |
| demoted | DDIC, config, includes, generated twins | never earn a row; attributed through their consumer |

Four root decisions carry real judgment, and all four are deliberate:

- **SICF nodes** earn a row only when the handler is custom. In a Gateway system the
  overwhelming majority are auto-generated OData twins pointing at `/IWFND/` classes;
  giving them rows drowns the real endpoints.
- **A CDS view consumed by another CDS** is a member of that one, not a root.
- **A T-Code with no custom member** is relabelled *"T-Code (parameterised — no custom
  code)"*. It is a parameterised or variant entry into standard SAP — customizing, not
  custom code. Saying so is far more useful than a row that looks like missing data.
- **`SUBC=I` includes never earn a row.** An include is part of its program.

### The reconciliation identity

```
unit roots  +  folded members  +  unattached  ==  every object scanned
```

Asserted at the end of the `units` step; a mismatch aborts the run. Closures also reach
names that do **not** exist in the tree — code referencing packages that were never
exported. Those are dangling references, not members: they are written to
`dangling_refs.tsv` and excluded from the identity, or it overshoots by exactly that
count.

## 2. The rule ladder

Rules are additive; all of them contribute. The highest authority reached per
(unit, module) sets the confidence.

| Rule | Signal | Authority | Confidence |
|---|---|---|---|
| R1 | home package | AUTHORITATIVE | HIGH |
| R2 | resolved entry program name | AUTHORITATIVE | HIGH |
| R3 | enhancement anchor (the standard object being enhanced) | AUTHORITATIVE | HIGH |
| R4 | classic SMOD exit include name | AUTHORITATIVE | HIGH |
| R10 | **content: standard tables the code WRITES** | AUTHORITATIVE | HIGH |
| R5 | name tokens | STRONG | MEDIUM |
| R6 | special families | STRONG | MEDIUM |
| R9 | custom name wrapping a standard transaction, program or BW DataSource | AUTHORITATIVE from a resolved entry, else STRONG | HIGH / MEDIUM |
| R12 | HR infotype naming (`P9000`, `PA9000`, `MP900010`) | STRONG | MEDIUM |
| R13 | append/extension of a standard object (`CI_BSIS`, `ZZMC11VA1ITM`) | STRONG | MEDIUM |
| R14 | IDoc segment or message type, from the name or from code | STRONG | MEDIUM |
| R15 | include named after the standard function group it belongs to | STRONG | MEDIUM |
| R7 | closure fingerprint (standard tables READ, standard calls) | INFERRED | LOW |
| R18 | standard data elements a structure's fields are typed with | INFERRED | LOW |
| R8 | tie-breakers (application area, description keywords) | WEAK | LOW |

Three more exist only in the residual pass, where the subject is a lone object rather
than a unit (see §2b):

| Rule | Signal | Authority | Confidence |
|---|---|---|---|
| R16 | there is nothing here: a stub, a formatting asset, an unreferenced DDIC leaf | INFERRED | LOW |
| R17 | inherited from what uses this object, or from what defines it | STRONG if one donor agrees, else INFERRED | MEDIUM / LOW |

**R1 — home package.** The strongest signal in the ladder, because it is a decision a
human made in SAP and a transport enforced. abapGit strips `<DEVCLASS>` from every
object file, so it must be recovered from folder structure, export zips or an explicit
list (see `configuration.md`). A member's package contributes at INFERRED strength, and
reaches one hop deeper than name evidence, because a member's home package is an
authoritative fact about *that member* at any depth.

**R2 — the entry program, never the T-Code.** Module tokens live in program names far
more often than in transaction codes; the workbook legend quotes both measured counts
so the reader can see it. A T-Code's target comes from `<PGMNA>`, or — when that is
empty — from decoding `<TSTCP><PARAM>`: `/*SM30 VIEWNAME=X`, `/NFBZ1 BKPF-BLART=CA`,
`@@FB50 ZFB50`. Without that decoding, a large share of an estate's transactions look
like they have no entry point at all.

**R3 — enhancement anchors.** For an enhancement, the standard SAP object being
enhanced names the module with certainty (`ACC_DOCUMENT` → FI, `ME_PROCESS_PO_CUST` →
MM). Prefer `<BADI_NAME>` over `<SPOT_NAME>`: the spot is much coarser, and several
unrelated implementations often share one.

**R5 — name tokens.** Read at the configured segment positions. The blacklist is what
makes it safe: two-letter tokens in the module position are very often legal entities,
plants, brands or architectural layers. Confirm each from the objects' own short texts.

**R10 — content: what the code changes.** The authorities in this ladder are measured,
not assumed. Measured against held-out truth (objects with an independently known
module), the signals rank like this, most reliable first:

| rank | signal | how far to trust it |
|---:|---|---|
| 1 | **writes** a module's standard tables | authoritative — fires rarely, almost never wrong |
| 2 | naming conventions (R5/R6/R9) | strong — fires often, mostly right once look-alike tokens are blacklisted |
| 3 | **reads** a module's standard tables | well behind — every module reads every other module's data |
| 4 | calls a module's change BAPIs | no better than reads — calling an API makes you its consumer |

Do not take this ranking on trust: `scripts/measure_signals.py` measures each signal's
accuracy and coverage on your own estate.

The asymmetry is the whole point. Every module reads every other module's data, and a
process that posts through another module's API is a *consumer* of it — a production
confirmation posts goods movements and accounting documents without being MM or FI. But
writing straight into a standard SAP table is invasive and rare, and it is almost always
done by the team that owns the table.

So R10 is AUTHORITATIVE and is deliberately **exempt from the authority floor**: it may
name a module nothing else supports. It also fires rarely — typically on a small
fraction of the estate — so its value is threefold: it attributes a
handful of units at HIGH confidence, it validates the naming rules everywhere else (see
the cross-check below), and a direct write to a standard SAP table is a governance
finding in its own right.

The write patterns match internal tables too (`INSERT lt_items`), so the result is
intersected with the known standard-table set. That intersection *is* the filter.

**R7D -- deep content.** The authority floor stops R7 inventing modules, because a
single table read is nearly worthless. But read evidence scales: accuracy climbs with
the number of distinct tables of one module the unit reads. One or two tables are close
to a coin flip; five or more are good; **five or more plus an agreeing standard call** is
the strongest read evidence there is.

At that top tier content rivals naming, so R7D fires at STRONG and is exempt from the
floor: `tuning.content_deep_tables` (default 5) distinct tables of one module plus a
corroborating standard call (`content_deep_needs_call`). This is what attributes an API
layer whose name says nothing -- 7 sales tables plus `BAPI_SALESORDER_CREATEFROMDAT2` is
not ambiguous, whatever the object is called.

**R11 -- external API surface.** Facts from the object's own serialisation, not
inferences: an RFC-enabled function group (`<REMOTE_CALL>R`), a SOAP web-service
definition, an ICF/OData endpoint, or code that talks outward (`EXEC SQL`, ADBC, HTTP
and REST clients, `CALL FUNCTION ... DESTINATION`). When `modules.integration_bucket`
names a bucket, these tick it. On a typical estate this surfaces RFC-enabled function
groups, SOAP services and objects reaching an external database through native SQL --
none of it visible before.

**Custom table names as name evidence.** A unit's own `Z*`/`Y*` tables are evaluated by
R5 and R6 exactly like object names, because a table name carries the estate's naming
convention. This is what rescues objects whose titles were copy-pasted from whatever
program they were cloned from.

**R12/R13/R14/R15 — the families SAP names for you.** Four cases where the customer
did not choose the name, so the name is a fact rather than a convention. Each was added
because it was the *only* thing that could speak for a whole class of object:

| Rule | The class it rescues | Why nothing else reaches it |
|---|---|---|
| R12 | a custom HR infotype: `P9000`, `PA9000`, `PS9000`, `P9000_AF`, `MP900010`, plus its screen structure | ten-plus generated objects, no module token in any name, dispatched from T777D so nothing references them |
| R13 | append structures: `CI_BSIS`, `ZZMC11VA1ITM`, `ZBW_CE3XXXX`, `ZT023` | no business words at all — but the base they append to *is* the module, and SAP's generated short text says it outright ("Append for MC11VA1ITM", "Fields from BSEG") |
| R14 | IDoc segments and the code that processes them | a segment type is a DDIC structure, so `TYPE e1kna1m` reads as nothing to a table rule |
| R15 | `ZLKED2TOP` — the TOP include of a clone of SAP's KED2 | declares a FUNCTION-POOL and some data; nothing to fingerprint, no inbound edge |

**R14 reads message types from CODE only, never from a short text**, and the reason is
`ORDERS`. It is a real SAP message type and also an ordinary English word, so scanning
descriptions for message types attributes programs about production orders,
payment orders and sales orders to purchasing — every one of them wrong, with R14 the
only rule supporting the tick. A literal next to `MESTYP` is an assignment; a word in a
sentence is a word in a sentence. Segment names from a short text stay allowed, because
`E1KNA1M` cannot be anything else.

**R18 — the data elements the fields are typed with.** The last signal a DDIC object
has, and often the only one. A custom table's short text is frequently just its own name
repeated, its check tables are all non-discriminating, and nothing in the estate
references it — but its fields are typed from SAP's dictionary, and those names say what
it is for:

| Object | Field types | Module |
|---|---|---|
| `ZXX_PAYROLL_FIELDS` | `PAE_SNAMT`, `PAE_SNACT` | HR (payroll) |
| `ZXX_OFFSET_DESC` | `GKONT_LTXT` | FI (offsetting G/L account) |
| `ZXX_TM_SCHEDULE` | `TPLST`, `LZONE`, `ROUTE` | SD (transportation) |

Only the leading module is returned — a structure typed from three modules' fields is a
join, not a three-way owner. R18 sits **under the authority floor with R7**, because it
is the same kind of evidence: what data the code touches, not what the code is called.
At STRONG it starts naming modules on its own — a production-cost report grouping by
`MATKL` becomes an MM owner on the strength of a single field type.

**R7 — closure fingerprint.** Discriminating standard tables and standard call targets
anywhere in the unit. Two exclusion lists do the real work: near-universal tables
(material, customer, company code) carry no signal and would tick one module on
everything; table-maintenance framework calls (`LSVIM*` and friends) would misclassify
the function group of every maintained table.

**R8 — last resort.** Fires only when nothing else did.

## 2a. Two modules, one object: which one owns it

Ticks are additive, so an object with two stakeholders gets two ticks and both teams see
it. `primary_module` still has to pick one, and picking it by authority alone is not
enough when two rules agree at the same strength.

The rule that works: **the owner is the module that has no transaction of its own for
the job.**

`IH09` is the worked example. It displays the material master, and it is filed under
Plant Maintenance:

- MM has a stake — it is the material master, and MM's tables.
- PM has a stake — it is a PM transaction, which is why it offers branches to the
  maintenance order (`AUFK`) and the notification (`MELD`).
- **MM already owns `MM01/02/03`** for maintaining that master. PM has nothing else.
  A planner reaching for material data reaches for `IH09` because it is the only door
  PM gives them.

So PM is the owner and MM the stakeholder, and `std_name_wrappers` records that by
listing PM first. Reading it the other way round — MM as owner because the data is
material master — loses the reason the transaction exists.

The same test settles the rest of the family: a POS interface exit that posts a goods
movement belongs to POS, not MM, because MM has `MIGO`; an e-invoicing report over
billing documents belongs to e-invoicing, not SD, because SD has `VF03`. **Ask which
module would have no way to do this job otherwise.**

Where one of the two is out of scope, this matters more than it looks. Naming only the
owner leaves the object with *no tick at all* once that module is ruled out — which is
what happens to a parameter transaction over `IH09` (and its variants) on an estate
that does not run PM. Naming both suppresses PM, records that it was named, and ticks
MM.

## 2b. The residual pass — every OBJECT, not just every unit

Sheet 1 answers a consultant's question: *which of these units is mine?* An owner asks a
different one: *is every object in my estate accounted for?* Those come apart, and the
difference can hide a real hole.

An object reaches a module in one of two ways — it is a unit root, or it is folded into
one. Everything else lands in Unattached, where the reason column said things like
"DDIC / config (attributed via its consumer)". That sentence is true of a data element
used by an attributed table. It is simply false when nothing references the object at
all — which can be every domain, table type and authorisation object in a repository,
plus classic user-exit includes and whole custom HR infotypes, all reported as covered
when none is.

Two causes, and the reason column conceals both:

- **No edges exist.** A DDIC object holds no ABAP, so its only facts are the objects
  it is composed *of* — table → data element → domain, table type → row type, view →
  base tables, maintenance object → table. A scanner that does not read them leaves
  every leaf at in-degree zero. The `DDIC_*` edge family fixes that, and the check tables it also
  picks up are content evidence about the DDIC object itself.
- **The rules never run.** An unattached object is not put through the ladder at all,
  however obvious its name. `MP900010` would match an HR family rule already in the
  config; `ZXM06U41` is a purchasing exit include with an entry in the knowledge base.
  Without a residual pass neither is ever tested against them.

So the `residual` step does three things, in this order, because each feeds the next:

1. **inherit** — a component takes the modules of whatever uses it, iterated to a fixed
   point: programs attribute their tables, tables their data elements, data elements
   their domains.
2. **attribute** — whatever is still empty goes through a per-object ladder: the same
   rules, read from the object's own name, text and content.
3. **inherit again** — because step 2 seeds objects step 1 could not reach.

Two directions matter, and getting them backwards leaves objects stranded:

- **composition** — the target is *part of* the source, so a component inherits from its
  **consumers**. Data elements, domains, forms, tables.
- **definitional** — the source *is defined by* the target, so the object inherits from
  its **children**, and this is tried first because "this object is that object" is a
  stronger claim than "something that uses this object is MM". A table type is its row
  type; a maintenance object is about the table it maintains; a screen variant is a
  variant of its program.

Definitional targets are also offered to R9 directly, because most of them are
*standard* objects and standard objects are not in the repository: a transaction variant
of `IH09` has exactly one fact attached to it, and inheritance can never see it.

### Three outcomes, not two

The residue is not one bucket. Reporting it as one makes the hole invisible:

| Outcome | Meaning |
|---|---|
| **ticked** | at least one module, with evidence and a confidence |
| **ruled out** | the only answer is a module the config declares out of scope. A decision that was already taken — reporting it as a gap invites someone to take it again. Ruled-out status travels down the chain, so a screen variant inside a transaction variant of a PM transaction inherits the PM decision |
| **unaccounted** | genuinely nothing known. This is the number the coverage gate holds at zero |

"There is nothing here" is an answer too, and a better one than silence — R16 covers a
four-line include holding a `BREAK <username>`, a SmartStyle or page format with no
logic to read, and a `CHAR30` data element nothing uses. All three go to the technical
bucket at LOW confidence with the reason recorded, and if the site configured no
technical bucket the reason is written to the note instead, never forced into a business
module.

With the residual pass in place, every scanned object ends ticked or ruled out, and
unaccounted stays at zero. Without it, a sizeable share of the estate is typically
reported as covered when it is not.

## 3. The four brakes

Additive rules smear without brakes. Remove any one of these and multi-module
attribution climbs sharply, which reads to a consultant as "the tool has no idea".

1. **Infrastructure gate** — a member with in-degree ≥ `fanin_gate` (default 40)
   contributes a note, never a tick. The most-called object in an estate is a logging or
   utility class used by everything; it is plumbing, not business meaning.

   The threshold is absolute, and an estate's central utility can sit just under it
   while still being called from everywhere. A general-purpose RFC API with a few dozen
   callers — creating sales orders, posting goods issues and booking FI down payments —
   lends its standard tables to every caller through R7/R7D and can push the leading
   module's share past the adversarial gate.
   `naming.infrastructure_objects` lets a human declare what the counter missed. Listed
   objects still get their own row and still appear as members; they just stop lending
   their tables to their callers. Reach for it when the module-share gate fails and the
   evidence lines on the excess ticks all name the same member.
2. **Hop decay** — hop 1 full strength, hop 2 weak, deeper is evidence only.
   `tick_max_hop` (2) for names and tables, `pkg_max_hop` (3) for packages.
3. **Breadth cap** — closure-derived rules reaching `breadth_cap`+ core modules mark the
   unit CROSS instead of ticking half the estate.
4. **Authority floor** — R7, R18 and R8 may only *reinforce* a module some earlier
   signal already supports, never invent one, unless nothing at all is known about the
   unit yet. R10 is deliberately exempt: it is the most accurate rule in the ladder.

There is a fifth brake that is not a rule at all. `primary_module` must not break ties
on list order (`-all_modules.index(m)`): then **the first entry in `modules.core` wins
every tie** — whichever module a consultant happened to type first becomes the owner of
every genuinely two-sided unit, and its share of the estate is inflated by an artefact
of list order. The tell-tale sign is a leading module whose primary share sits within a
point of its tick share, which cannot be true of real code. Ties go to the module the
most *distinct rules* named: two independent signals agreeing is evidence of ownership where
one is not, and it does not depend on how the config was typed.

An **inherited** primary is settled differently again. A unit whose ticks came from a
donor takes the donor's primary wherever it also ticks it, and only falls back on the
tie-break when it does not. Ranking its own modules from scratch means re-deciding an
ownership question with strictly less evidence than the donor had -- and it lets a
transaction variant name a different owner from the transaction it is a variant of.

There is also an **evidence mute list**: edges strong enough to prove an object exists in
a unit but too weak to say who owns it. `TYPE zsome_struct` is the clearest case —
declaring a structure that happens to live in the MM package does not make a program MM.
These still count for reachability, so the object is not mislabelled "no entry point".

## 3a. The content/name cross-check

Name evidence reads what an object is *called*; content evidence reads which modules'
standard tables it *touches*. They are independent, which makes their agreement a real
test of the rules rather than of the output. On a healthy rule table they mostly agree,
and the gate fails below `min_content_name_agreement_pct` (default 80%).

Run `scripts/measure_signals.py` to reproduce all of this on your own estate.

The disagreements are the most useful list the build produces. A typical catch: a
master-data family ticking MM on the asset master, the chart of accounts, the vendor
master and cost-centre master — all of which are FI or CO, as the tables say. Two things they are *not*: a BW extractor reading MM tables is correctly
ANALYTICS, and an e-invoice report reading sales and purchasing documents is correctly
FI. Read each one before changing a rule.

## 3b. Validating an estate that has no held-out export

When there is no ATC or cloud-readiness export, rule R1 has no independent check -- and
the deliverable must say so. But three other checks usually exist, in descending order
of what they prove:

1. **Existing per-object documentation.** If the repo carries prose docs (a previous
   documentation pass, a custom-code register, a wiki export), each one that states a
   module is held-out truth written by a human reading the source -- often stronger
   evidence than a package column. Look for a `Module:`-style line and compare OVERLAP, not equality: a doc
   saying "MM + FI (read)" matches a unit ticked MM and FI.
2. **Reading the source**, one unit at a time. Definitive, and the only option for the
   residue.
3. **Content evidence** -- independent of naming, and already computed (see 3a).

A lane or team assignment produced by an earlier project is NOT independent if you
seeded your family patterns from its rules. Report it separately and label it weaker, or
it will flatter the index.

## 4. Diagnosing a bad index

| Symptom | Likely cause | Fix |
|---|---|---|
| UNCLASSIFIED above a few percent | packages unmapped, or no package source at all | map them; check `packages_without_module_mapping` in the stats |
| One module over ~35% of rows | a look-alike segment is not blacklisted, or a package maps to too many modules | blacklist the token; narrow the package map |
| Multi-module above the band | brakes disabled, or a family rule that is too broad | check `tuning`; tighten the family pattern |
| Confidence mostly MEDIUM/LOW | rule R1 is not firing — no package source | supply zips or an object→package CSV |
| Everything ticks one module | a non-discriminating table crept into `std_tables` | remove it, or add it to `non_discriminating_tables` |
| Content/name agreement below ~85% | a naming family is broader than what the code does | read the conflict list in the validation report; the tables are usually right about master data |
| Many "no entry point" rows with `inbound_refs > 0` | normal — mutually-referencing pairs and OData MPC/DPC classes | explain it in the legend, do not "fix" it |
| Units far larger than ~120 members | an edge type is folding a peer, not a child | review `fold_edges` |

Two columns exist purely for triage and are worth reading before changing anything:
`rules_fired` (which rules touched this unit) and `evidence` (the actual clauses). The
`marginal` line in the attribution report says how many ticks each rule added that no
earlier rule had — a rule contributing near zero is either redundant or misconfigured.

## 5. What static analysis cannot do

State these in the deliverable rather than letting a reader discover them:

- **Dynamic calls.** `CALL FUNCTION <var>`, `SUBMIT (<var>)`, `PERFORM (<var>)`,
  `CALL TRANSACTION <var>`. This is the hard ceiling on closure completeness. Literal
  resolution recovers a large share of it (names routed through a variable are usually
  assigned from a literal somewhere), but not all.
- **Form selection.** Driven by output determination / NAST customizing, which no source
  export contains. Forms are attributed by package and name.
- **Objects referenced but never exported.** Real references, absent code. Supplying the
  missing package is what shrinks the list.
- **Transactions that resolve to nothing.** Neither `<PGMNA>` nor `<TSTCP>` names a
  followable target. They still carry a row and their package attribution.
