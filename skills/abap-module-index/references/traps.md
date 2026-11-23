# Traps

Every entry here is a defect that has shipped in a deliverable that looked fine. They
are all implemented correctly in `scripts/` — this file exists so you can recognise the
symptom if you extend the pipeline, port it, or are handed output from something else
that claims to do the same job.

They share one property: **they fail quietly**. Nothing crashes; the numbers are simply
wrong, and plausible.

## Parsing the tree

**1. Filenames containing spaces.** abapGit pads compound keys to a fixed width:

```
'extsys         cb50d03f8d24d7ab730ac7522.sicf.xml'
'zc_mm_po_budget_approval_cds       0001.iwsv.xml'
```

Any parser that splits on whitespace (`ls | awk '{print $NF}'`, `.split()`) turns those
into object names like `cb50d03f8d24d7ab730ac7522` and `0001`. That is how SICF nodes
and OData services end up in an inventory under hash names — a couple of hundred files
in a typical estate. **Rule: object names cannot contain a dot, and abapGit always emits
`<name>.<type>[.<subtype>].<ext>`. The type is the second dot-token, unconditionally;
the name is the first, spaces included.**

**2. Opaque names.** For `sicf`, `iatu`, `iwsv`, `iwmo`, `iwvb`, `sush`, `tobj`, `xinx`,
`iarp` the on-disk name is a padded compound key or a generated hash. The human-readable
name has to come from the XML payload (`ICF_NAME`, `SERVICE_NAME`, `TEMPLATE_NAME`, …).

**3. Nested XML tags that share their leaf's name.** This one is vicious:

```xml
<ICFHANDLER_TABLE>
  <ICFHANDLER>                                       <!-- wrapper -->
    <ICF_NAME>EXTSYS</ICF_NAME>
    <ICFHANDLER>ZCL_EXT_REST_HANDLER</ICFHANDLER> <!-- leaf -->
  </ICFHANDLER>
```

A non-greedy `<ICFHANDLER>(.*?)</ICFHANDLER>` matches from the *wrapper's* open tag to
the *leaf's* close tag and captures an XML blob — and because `findall` does not
backtrack into a consumed match, the leaf is then never seen at all. The blob is truthy,
so it gets emitted as an edge target and as the OData-twin discriminator, both silently
wrong. **Fix: `<TAG>([^<]*)</TAG>`. A leaf value never contains `<`, so the wrapper
simply does not match and the leaf does.**

**4. Encoding.** A plain `open()` uses the platform default (cp1252 on Windows) and
raises on any file containing non-Latin text — hundreds of files in a localised estate.
Read bytes, try `utf-8-sig` then `utf-8`, fall back to `latin-1` with replacement.

**5. Mirrored sub-package folders.** Some teams extract a sub-package export *into* the
parent's `src/`, leaving a byte-identical copy of files already there. Counting both
doubles LOC and file counts. Dedupe by filename — and *report* the count, because a
silent duplicate is how double-counting starts.

**6. `package.devc.xml` is not an object.** Parsed naively it becomes an object called
`PACKAGE` of type `DEVC`, once per folder, and then appears in the reconciliation as an
object with no package.

## Building the graph

**7. `.abap`-only extraction.** In a typical estate `.abap` files are a minority of the
tree, so an `.abap`-only sweep produces **zero** edges for CDS views, SICF nodes, OData
services, SmartForms, enhancements, screen variants and parameter transactions — whole
families then report no resolvable entry point. All of those facts live in XML,
`.asddls` and `.baseinfo` files.

**8. Commented-out code.** Strip full-line (`*`) and trailing (`"`) comments before
matching, or dead lines produce phantom `STATIC_CALL` edges.

**9. Self-loops.** A function group "including" its own `LZ<name>TOP` is not a
relationship, and such self-includes are usually the large majority of include-edges.
But the test must be **exact**: a loose prefix or substring test also eats real edges —
`ZC_..._0001 → ZC_..._0001_BE` (the OData frontend/backend twin) and any
`ZXX_FOO → ZXX_FOO_HELPER` call look like self-references to a substring check.

**10. One row per call site.** A class calling another on forty lines produces forty
rows, and a whole estate's call rows outnumber its distinct edges many times over. A
graph wants distinct edges; evidence wants the call sites. Keep both: dedupe to
`(source, type, target)` and carry `first_site` + `occurrences`.

**11. Function modules are not objects.** `CALL FUNCTION 'Z_FOO'` names an FM; the
object is its function group. Without the `FUNCNAME → AREA` alias from `fugr.xml`, every
custom FM call dangles and function groups look unreferenced.

**12. `FORM = '...'` also matches ALV callbacks.** `I_CALLBACK_PF_STATUS_SET` and friends
are subroutine names, not forms. Restrict the pattern to custom-namespace names, then
resolve against the form objects that actually exist — that is what stops a scan
"finding" forms called `ALV_PF_STATUS_SET` and `TOP_OF_PAGE`.

**13. Names routed through a variable.** The highest-yield edge pattern in a typical
estate, and keyword-anchored regexes miss all of it:

```abap
lv_formname = 'ZXX_WM_002_BINLAB'.   " then passed to SSF_FUNCTION_MODULE_NAME
CALL FUNCTION lv_fmname.             " assigned from a literal earlier
lo_router->attach( iv_handler_class = 'ZCL_EXT_INBDEL_REST_RSRC' ).
```

Collect every custom-namespace string literal and resolve it against the set of objects
that exist. A literal naming no real object costs nothing. Without this, an audit will
report large numbers of call sites as "permanently unreachable dynamic calls" when many
are only *keyword* unreachable — the target is right there as a literal.

**14. OO references.** A `ZCL_FOO=>` regex alone misses a class used through a reference
variable, a superclass, or an implemented interface. A meaningful share of objects
reported "unreferenced" turn out to be reachable via `TYPE REF TO`, `TYPE`,
`INHERITING FROM` or `INTERFACES`. `INTERFACES` may list several names before the
period, so it needs a two-stage pass.

**15. Parameter transactions.** A parameter transaction has no `<PGMNA>` at all; its
target is encoded in `<TSTCP><PARAM>` as `/*SM30 VIEWNAME=X`, `/NFBZ1 BKPF-BLART=CA` or
`@@FB50 ZFB50`. Without decoding those three forms, a large share of an estate's T-Codes
appear to have no entry point.

**15a. `WEBI` is a Web Service Definition, not a Web Dynpro application.** abapGit's
`webi` type is a SOAP endpoint published over function modules (`LCL_OBJECT_WEBI`,
payload `VEPHEADER`/`VEPFUNCTION`/`VEPPARAMETER` with `<IS_EXPOSED>`). Web Dynpro is
`wdyn`/`wdya`. Mislabelling it hides a live external API surface and attributes each
service by its own name instead of by the function modules it exposes. The
`<FUNCTION>` entries are the attribution: a web service IS what it publishes.

**15b. RFC-enabled function modules cannot be found by grepping the ABAP.** The literal
`REMOTE-ENABLED` is a comment abapGit does not serialise, so a body grep reports zero
RFC-enabled FMs in an estate that has dozens. The authoritative marker is
`<REMOTE_CALL>R` inside each `<item>` block of the function group's `*.fugr.xml`.

**15c. Custom table usage is invisible to a call-graph extractor.** `TABLES: ZXX_WF_TAB1.`
and `SELECT ... FROM zxx_wf_tab1` create no call edge, no literal and no OO reference,
so the estate's own data model contributes nothing. It should contribute twice: the
table becomes reachable instead of sitting in Unattached, and its NAME carries the
estate's naming convention. See trap 24a for what that costs.

## Attribution

**16. Non-discriminating tables.** Material, customer and company-code tables are read
by everything — `MARA`, `KNA1` and `T001` typically top the hit counts by a wide margin.
Leave them in the fingerprint and every unit ticks the same module.

**17. Framework noise.** `LSVIM*` (SM30 table maintenance) is typically the single
most-called standard target in an estate. Left in the call fingerprint, it misclassifies
the function group of every maintained table. There is a validation gate specifically for
this: framework names must never appear in the evidence of a ticked unit.

**18. Look-alike name segments.** Two-letter tokens in the module position are very often
legal entities, plants, brands or architectural layers — not modules. Confirm each from
the objects' own short texts and blacklist the ones that are not modules. This is the
most common cause of one module owning half the estate.

**18a. A person's name is not a module signal.** A family rule matching developer names
(`ZDEVNAME`, "Devname") and the word `TEST` can label an estate's general-purpose
external RFC API — function modules doing sales orders, deliveries, PGI, FI down
payments and HR absences — as "developer scratch code", while the extracted content
(`BAPI_SALESORDER_CREATEFROMDAT2`, many discriminating tables) sits right there and the
name rule simply wins. Match on what an object DOES, never on who wrote it.

**18b. `LFA1` is not an FI table.** Vendor *general* master data is read by purchasing,
by sales for freight vendors, and by every form that prints a vendor address. Measured
against held-out truth, dropping it from the FI table set leaves read accuracy
essentially unchanged while removing the sole reason many objects get called FI. `LFB1`
(vendor company-code data) is genuinely FI and stays. The same argument already applies
to `KNA1`.

**19. Third-party code.** Vendored open source (abap2xlsx — several hundred objects —
abapGit, mocking frameworks) is not custom business code. Left in, abap2xlsx alone puts
dozens of UNCLASSIFIED `ZCL_EXCEL*` classes on sheet 1.

**20. A stray `$TMP.zip`.** One local-objects export sitting in a package-export folder
can claim tens of thousands of objects and bury every real package in the report. Drop
claims for objects the scan never saw.

**21. Sub-package folder logic.** `src/demos/` under `ACME_ZABAP2XLSX.zip` is
`ZABAP2XLSX_DEMOS`, not a package called `DEMOS`. Getting it wrong is how a third-party
demo sub-package escapes its own exclusion rule.

**21a. Change-API calls look like strong content evidence. They are not.** It is
tempting to treat `CALL FUNCTION 'BAPI_SALESORDER_CREATEFROMDAT2'` as proof of SD
ownership. Measured against held-out truth it is no better than table reads, and the
misses show why. A production confirmation posts goods movements (MM) and accounting
documents (FI); an SD utility posts through FI; a CO reposting calls the FI poster.
Calling a module's change API means "I trigger that process", not "I belong to it". Only
direct table *writes* earn authoritative status.

**21b. Write patterns match internal tables.** `INSERT lt_items`, `MODIFY it_data` and
`DELETE lt_rows` are the overwhelming majority of INSERT/MODIFY/DELETE statements in any
ABAP program. Intersecting the matches with the known standard-table set is what makes
the rule usable at all — without it, it fires on everything ever written.

**21c. A DDIC object has no edges, so it has no evidence — and the reason column lies
about it.** Data elements, domains, table types and authorisation objects contain no
ABAP, so an `.abap`-only extractor gives every one of them in-degree zero. They then land
in Unattached under "DDIC / config (attributed via its consumer)", which is true of a
data element used by an attributed table and **false when nothing references it at
all** — and that sentence can end up covering hundreds of objects that are neither
attributed nor referenced. The composition is right there in the XML — `<ROLLNAME>` per
field, `<DOMNAME>`, `<ROWTYPE>`, `<TABNAME>` in a view's `DD26V`, `<CHECKTABLE>` per
foreign key — it simply has to be read. Check the consumer count before believing a
reason string that claims a consumer.

**21d. Edge direction is not one thing.** A domain inherits from its **consumers** (the
data elements that use it). A table type inherits from its **children** (its row type),
because a table type *is* its row type. Get it backwards and table types and maintenance
objects stay unattributed forever — they have no consumers at all, since what they point
at is their own definition. Definitional edges also have to be tried first: "this object
is that object" outranks "something that uses this object is MM".

**21e. Inheriting from a single donor can never satisfy a majority test.** A breadth
narrowing that asks for `max(2, (contributors+1)//2)` votes demands, with one donor, two
votes that cannot exist — so an object whose one donor is itself multi-module (a
maintenance object over a five-module table) inherits *nothing* and is reported as an
unexplained gap. Guard majority tests with `contributors > 1`.

**21f. `ORDERS` is an English word.** It is also a real SAP IDoc message type, so
resolving message types out of short texts attributes programs about production orders,
payment orders and sales orders to purchasing — each with the evidence line
`idoc-message:ORDERS`, each wrong, and the rule the only support for the tick. Read
message types from CODE only, where the literal sits next to `MESTYP`. Segment names are
safe from text because `E1KNA1M` cannot be anything else; the SHAPE is what makes it
safe, not the source.

**21g. Master data and customizing are not module evidence; documents are.** The rule
that demoted MARA, KNA1 and LFA1 applies to every table, and it is easy to forget when
adding a batch. Adding the sales-org and transportation *customizing* tables (TVKO,
TVTW, TSPA, TTDS, TZONE, TVRO) as discriminating fixes one report and tips R7D over its
five-table threshold on many others, each gaining a spurious SD tick. The shipment
*document* tables (VTTK, VTTP, VFKP) are the opposite and stay. A table can sit in
`std_tables` under a module AND in `non_discriminating_tables`: that combination says
"reading it proves nothing, but a structure NAMED after it is that module", which is
exactly what the name rules need.

**21h. One object, several types.** A generated table-maintenance dialog is a table, a
function group and a T-Code under one name. Coverage is keyed by name, so reading only
the first signal row throws away the table's field types — the only evidence any of the
three has — and leaves all three unattributed. Merge the rows per name.

## Reporting

**22. Dangling references inflate the reconciliation.** Closures legitimately reach names
that do not exist in the tree — code referencing packages that were never exported.
Intersect member sets with the scanned universe before counting, or the identity
overshoots by exactly the dangling count.

**23. Hardcoded numbers in prose.** Zip counts, file counts and "N-of-N" figures typed
into a legend go stale the moment a package is added. Compute every figure in the legend
and narrative from the pipeline's own stats files.

**24. A metric that measures the wrong thing.** A multi-module "healthy band" guessed
before any data exists will mislead. As edge extraction improves, objects that stood as
their own single-tick rows are correctly folded into units, so the *denominator* shrinks
while the multi-module count actually *falls* — and the ratio rises. The ratio goes up on
**better** attribution. The real over-attribution test is the breadth distribution (how
many core modules a single unit ticks); the band survives only as a loose sanity bound.

**25. A stale copy of the deliverable.** A hand-made copy in a second folder goes stale
without anyone noticing — wrong unit counts, a missing package — while the canonical copy
moves on. Mirror on every render, or keep exactly one copy.

**25a. Silence must count as silence.** A content/name cross-check that scores an empty
"content opinion" (a unit whose table evidence is a single hit on a single table) as a
*disagreement* instead of skipping it reports agreement far below the true figure. A
cross-check that counts no-opinion as conflict will always look broken, and will be
ignored — which costs you the check.

**24a. A program's title and header comment are often copied from another program.**
Programs titled "Asset Master Data", whose header comments claim to be other programs,
can turn out to touch exactly one custom table — a workflow table — and be
workflow-status programs, with the description, the TRDIR application area and the
header comment all wrong together. Where a row rests only on a description it belongs at
LOW confidence, and the estate's own table names are the better evidence.

**25b. The first module in `modules.core` silently wins every tie.** If `primary_module`
breaks ties on `-all_modules.index(m)`, whichever module a consultant happened to type
first becomes the owner of every genuinely two-sided unit. The symptom is a leading
module whose *primary* share sits within a point of its *tick* share, which cannot be
true of real code. Break ties on how many distinct rules named the module instead:
order-independent, and two agreeing signals really are better evidence than one.

**25e. Text keywords must be anchored at a word START.** A plain substring test matches
the keyword `API` inside the German word *Papiere*, filing an SAP quality-management
sample form under external interfaces. Anchor the START only, never the end: keyword
lists hold word STEMS so they catch inflected forms — a German list holds `BESTELL` to
match `BESTELLUNG` and `BESTELLUNGEN`, and a trailing boundary would break every one.

**25f. A form's title is extracted and then thrown away.** `<TDTITLE>` is not obviously
a description, so it is easy to leave out of the tag map — and then every SAPscript form
in the estate reports "no short text" and falls into "nothing here", even when a title
such as **"Certificate of Origin EU"** or **"RFDUZI00 Interest Calculation"** names the
form's purpose or its own print program, and thereby its module. Two follow-ons: the
languages cannot be paired by zipping `<TDSPRAS>` with `<TDTITLE>` (the header block
carries a language key of its own, so the lists differ in length and zipping returns
another language's title for `E`) — find the first title *after* the matching key. And
among ASCII fallbacks the SHORTEST wins, because a keyword list is far likelier to hold
the English words than, say, the Norwegian ones.

**25g. Only the first short text reaches the rules.** Objects routinely carry several,
and the first is often the least useful: a SAP Query InfoSet is named after itself and
describes its data sources in the field-group texts ("Conditions (Header)", "Change
document header"). Collect them all — but read them from the LAST-resort rule only, or a
long text starts outweighing real signals.

**25d. A standard transaction can OWN one module and DISPLAY another's data.** `^IH\d`
→ PM is right about the owner and silently loses the subject. `IH09` is *Display
Material*: its program is `RIMARA20`, a report over MARA. It is genuinely a Plant
Maintenance transaction — that is why it offers branches to the maintenance order
(`AUFK`) and the notification (`MELD`) — and what it puts on the screen is the material
master, which MM maintains through `MM01/02/03`. Both facts matter, and a rule table
that allows one module per pattern can only keep one of them.

The failure mode is not a wrong tick, it is **no tick at all**: on an estate that rules
PM out of scope, a parameter transaction over `IH09` and its variants resolving to PM
only are all reported as "out of scope by decision" and carry no module. Naming both —
owner first — makes PM suppressed and MM ticked, and the objects survive either way.

Two habits follow. Resolve the **program**, not the T-Code: a transaction variant
carries `<GUI_PROG>`, and a standard program name embeds its table (`RIMARA20` → MARA,
`RIEQUI20` → EQUI) where four characters cannot. And when you add a T-Code family
pattern, check the members that do something different and list those exact codes ahead
of the family — the first match wins.

**25c. The infrastructure gate is an absolute number.** A fixed `fanin_gate` finds the
logging class in a large estate and misses a general-purpose RFC API with a few dozen
callers in a smaller one — which then lends its standard tables to every caller through
R7/R7D. Symptom: the module-share gate fails and the evidence lines on the excess ticks
all name the same member. `naming.infrastructure_objects` declares what the counter
missed.

## Engineering

**29b. A rule measured on one estate is not measured.** A rule change can look right on
the estate it was written for and smear another: R7D as "every module with 5+ tables"
when the accuracy was measured on the top module only; the customizing tables above;
R18 as a STRONG rule (a production-cost report becomes an MM owner on one field type).
Run `scripts/regress.py` over at least two estates before shipping a rule change —
defects of this kind are invisible from one estate.

**29c. The frozen deliverable is not a baseline.** Comparing a new run against the last
shipped workbook only works if the shipped workbook came from the same rule set. A
shipped CSV whose `rules_fired` column names fewer rules than the current ladder
predates those rules, and the apparent jump in multi-module attribution is almost
entirely their doing. Check which rules produced a baseline before drawing a conclusion
from it.

**29d. A regex holding a literal control character never matches, and nothing
complains.** This is the worst failure mode in the whole tool because it is completely
silent, and JSON hands it to you: the two-character escape for backspace is
backslash-b, so a word boundary written the obvious way in a config pattern decodes to
chr(8) while the file on disk looks perfectly innocent. It must be written with a
DOUBLED backslash. A shell heredoc does the same thing to Python source.

Patterns dead this way can go unnoticed for a whole project: custom-table detection from
`SELECT...FROM`, from `INSERT/MODIFY/UPDATE` and from `DELETE FROM`; outbound
`CALL FUNCTION ... DESTINATION`; and tokens inside family rules. Reviving them multiplies
the custom-table references found and surfaces outbound RFC calls previously reported as
zero.

Two consequences worth internalising. `check_no_control_chars` refuses to load such a
pattern — but scan the DECODED values, never the file bytes: a check that reads raw text
finds none of them, because on disk they are an innocuous backslash and a b. And when a
dead token comes back to life, expect the gates to move: revived tokens can turn out to
be far too broad and need narrowing, which nobody could know while they never fired.

**29e. Whitespace in a T-Code parameter string.** `/*SM30 VIEWNAME= ZFOO;` — one space
after the equals — parses as nothing, so the T-Code has no members, the table it
maintains is never linked, and the row carries no evidence at all, while its sibling
written without the space resolves fine. Allow optional whitespace around every `=` in
TSTCP decoding.

**26. Non-determinism from set iteration.** Python randomises string hashing per process,
so iterating a `set` into a `Counter` makes insertion order — and therefore tie-breaking
and evidence-clause order — differ between runs. `sorted()` before counting. Without it,
"a rerun is byte-identical" quietly stops being true, which is what a consultant's
diff-based review depends on.

**27. `csv.field_size_limit`.** The `members` and `evidence` columns exceed Python's
default field limit on large units, and the failure is an exception mid-read, not a
truncation. Raise it in every module that reads these files.

**28. Stale intermediates on a mid-pipeline restart.** The caching that makes rule tuning
take seconds also means changing an early-step input and restarting late silently builds
on out-of-date files: change `packages.excluded`, restart at `attribute`, and third-party
rows survive into an otherwise clean-validating workbook — caught only by the
adversarial third-party check. Hence the fingerprint stamps: each step records the
config sections it depended on, and a later step refuses to start on inputs that have
since changed.

**29. Two places computing the same number.** When the held-out agreement is computed
independently by the step that builds the package map and the step that validates it,
the two can disagree — because one resolves an object name to its first package and the
other to its last. A few object *names* legitimately belong to two packages under
different object types. Define the comparison once, import it in both places, and make
the rule explicit: a name agrees if **any** package it maps to matches **any** package
the held-out source reports.

---

## 30. `modules.not_modules` is a sentence no gate reads

Ruling a module out is the one config decision that can *destroy* an answer rather than
redirect it, and its whole justification is free text a human typed once.

A config may say:

```json
"QM": "1 object touches a QM table; no quality-management process in scope"
```

while the estate actually holds several QM units — smart forms, an inspection-results
printout, a rejection report. Every one is identified correctly by the ladder and then
has its answer discarded, because a ruled-out module has no column to tick. They ship at
**zero ticks and NONE confidence**, which any reader takes to mean *the tool could not
work it out*. The truth is the opposite: the tool had an answer and the workbook had
nowhere to put it.

Worse, the same decision can silently reverse an explicit instruction. A custom copy of
`IH09` that should tick PM as owner and MM as stakeholder (see §2a in `method.md`) has
its PM tick computed, dropped for being out of scope, and ships as MM alone — the exact
verdict the owner had corrected.

**The gate.** `a ruled-out module never silences a unit` — FAIL when a unit ends with no
tick at all and its notes name a ruled-out module.

Choosing that trigger needs care, because the obvious trigger is wrong. Ruled-out
modules are named *routinely and harmlessly* on units that have another module anyway —
which is precisely what such reasons claim ("the objects touching RESB/STKO/STPO are
bundle BOMs, ticked MM"). So a mention count cries wolf. A unit left at **zero** ticks is
the unambiguous signal: there the exclusion did not reclassify the object, it silenced
it.

Two smaller defects come from the same decision:

**30a.** Family rules *labelled* `"SAP sample form: quality inspection (QM not in
scope)"`. A rule's label describes the rule; scope is a separate decision, and baking it
in means the evidence column contradicts the tick beside it the moment the decision
changes. Never put a scope verdict in a rule name.

**30b.** `primary_module` must not break ties on config list order (trap 25b) — and the
residual pass must not either. A transaction variant that inherits MM + PM from its
transaction must not name **MM** primary merely because MM is typed first under
`modules.core`, contradicting the very unit it inherited from. A unit whose ticks came
from a donor must take the **donor's** primary where it also ticks it: the donor reached
that verdict with its full evidence, which is by definition more than the inheriting unit
has.
