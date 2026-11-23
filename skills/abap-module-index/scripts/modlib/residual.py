"""
residual.py -- close the gap between "every UNIT is attributed" and "every OBJECT is".

The unit deliverable answers a consultant's question, but it does not answer the
owner's: *is every object in my estate accounted for?* Those are different questions,
and the difference was hiding a real hole.

A unit is an entry point plus its closure, so an object reaches a module in one of two
ways -- it is a root, or it is folded into one. Everything else lands in Unattached,
where the reason column said things like "DDIC / config (attributed via its consumer)".
That sentence is true of a data element used by an attributed table. It is simply false
when nothing references the object at all -- and that can be hundreds of objects:
every domain, table type and authorisation object in the repository, plus classic
user-exit includes and whole custom HR infotypes. All of them get reported as covered,
and none of them is.

Two causes, and the reason column concealed both:

  no edges existed      A DDIC object holds no ABAP, so the only facts it has are the
                        objects it is composed OF -- table -> data element -> domain,
                        table type -> row type, view -> base tables. The scanner never
                        read them, so every leaf had in-degree zero. Fixed in scan.py
                        (the DDIC_* edge family); this module consumes them.
  the rules never ran   An unattached object was never put through the ladder at all,
                        however obvious its name. 'MP900010' matches an HR family rule
                        that was already in the config, 'ZXM06U41' is a purchasing exit
                        include with an entry in the knowledge base, and neither was
                        ever tested against them.

So this step does three things, in this order, because each feeds the next:

  1. inherit    a component takes the modules of whatever uses it, iterated to a fixed
                point: programs attribute their tables, tables their data elements,
                data elements their domains. Container types (an enhancement composite,
                a Query user group) inherit the other way, from their children.
  2. attribute  whatever is still empty goes through a per-object ladder -- the same
                rules, read from the object's own name, text and content.
  3. inherit    again, because step 2 seeds objects that step 1 could not reach.

Confidence is deliberately capped: an inherited tick is LOW unless every consumer
agrees, because "the table that uses this domain is MM" is weaker evidence than
anything in the unit ladder. The point is not to claim certainty. It is that no object
is silently reported as covered when nothing is known about it, and that the ones
genuinely undecidable from source arrive as a short, reviewable list with a stated
reason instead of hiding inside a 300-row "attributed via its consumer".

Outputs
  coverage_by_object.tsv   one row per scanned object: how it reached a module, on what
                           evidence, at what confidence -- or why it did not
  module_matrix.residual.tsv  the unit matrix with ticks added ONLY to rows that had
                           none, from objects that reference the unit's root
  residual.json            the counts the narrative and the coverage gate quote
"""

import collections
import csv
import json

from . import rules as R

csv.field_size_limit(10_000_000)

MAX_ITERATIONS = 12

COLUMNS = ["object_name", "object_type", "package", "text", "how", "modules",
           "confidence", "rules_fired", "evidence", "unit_ids", "consumers", "note"]


class Cov:
    """What is known about one object's module attribution."""

    __slots__ = ("name", "otype", "package", "text", "how", "mods", "authority",
                 "rules", "evidence", "units", "consumers", "note", "suppressed")

    def __init__(self, name, otype, package, text):
        self.name, self.otype, self.package, self.text = name, otype, package, text
        self.how = ""
        self.mods = {}          # module -> authority
        self.rules = []
        self.evidence = []
        self.units = []
        self.consumers = 0
        self.note = ""
        # Modules a human explicitly ruled out. An object whose ONLY answer is a
        # ruled-out module is not unknown -- it is a decision that was already taken,
        # and reporting it as a gap invites someone to take it again.
        self.suppressed = set()

    @property
    def confidence(self):
        if not self.mods:
            return "NONE"
        return R.CONFIDENCE[max(self.mods.values(), key=lambda a: R._RANK[a])]

    def add(self, mod, authority, rule, evidence):
        cur = self.mods.get(mod)
        if cur is None or R._RANK[authority] > R._RANK[cur]:
            self.mods[mod] = authority
        if rule and rule not in self.rules:
            self.rules.append(rule)
        if evidence and evidence not in self.evidence:
            self.evidence.append(evidence)

    def row(self, cfg):
        return [self.name, self.otype, self.package, self.text, self.how or "GAP",
                ";".join(m for m in cfg.all_modules if m in self.mods),
                self.confidence, ";".join(self.rules), "; ".join(self.evidence[:6]),
                ";".join(sorted(set(self.units))[:4]), self.consumers, self.note]


def _best_type(cfg, name, sig):
    """The type a consultant would name for an object that exists as several.

    A generated table-maintenance dialog is a table, a function group and a T-Code
    under one name; type_priority already encodes which of those to lead with.
    """
    return sig.get("object_type", "")


# --- the per-object ladder ------------------------------------------------------------
def object_rules(cfg, cov, sig, fanin, anchors=()):
    """Run the ladder against ONE object's own name, text and content.

    This is not a second, weaker copy of attribute.py. It is the same rule set applied
    to a different subject: attribute.py asks "what does this entry point and its whole
    closure say", and gets to use package membership, resolved entry programs and
    enhancement anchors. Here there is no closure -- one object, whatever it is called,
    whatever its short text says, and whatever tables its own definition names.

    Rules that only make sense for a unit (R2 resolved entry, R3 anchor, R7D deep
    content, the hop and breadth machinery) are absent. Rules that only make sense for
    a lone object -- the infotype family, appends, IDoc naming, function-group includes,
    the stub test -- are here and not there, except where attribute.py also gained them.
    """
    name, otype = cov.name, cov.otype
    text = cov.text or ""
    sig = sig or {}
    # The accumulator, not cov.add, so a hit naming an unconfigured module lands in the
    # proposal register and a hit naming a ruled-out one is counted as suppressed --
    # the open-vocabulary guarantee has to hold here too, or the residual pass becomes
    # the one place in the pipeline where evidence is silently dropped.
    att = R.Attribution(cfg)

    for mod in cfg.package_modules.get(cov.package, []):
        att.add(mod, R.AUTHORITATIVE, "R1", f"pkg:{cov.package}")

    # R9 on what the object is a variant OF, before anything about the object itself.
    # Inheritance could not use these targets because most of them are STANDARD objects
    # and standard objects are not in the repository: a transaction variant of IH09
    # has exactly one fact attached to it, and that fact is IH09. The edge came from
    # serialised metadata (<TCODE>, <PGMNA>, <PARAM>), so it is authoritative -- a
    # variant of IH09 cannot exist without IH09.
    for a in anchors:
        hits = R.wrapper_hits(cfg, a) or R.std_anchor_hits(cfg, a)
        if hits:
            att.add_many([(m, f"{ev} (variant of {a})") for m, ev in hits],
                         R.AUTHORITATIVE, "R9")
            break

    for mod, ev in R.exit_include_hits(cfg, name):
        att.add(mod, R.AUTHORITATIVE, "R4", ev)

    written = [t for t in (sig.get("std_tables_written") or "").split("|") if t]
    for mod, ev in R.write_hits(cfg, written):
        att.add(mod, R.AUTHORITATIVE, "R10", ev)

    for mod, ev in R.infotype_hits(cfg, name, text):
        att.add(mod, R.STRONG, "R12", ev)

    for mod, ev in R.append_hits(cfg, name, text):
        att.add(mod, R.STRONG, "R13", ev)

    # A short text may name the message type outright -- 'Extension to Vendor Master
    # (CREMAS)'. Words from the text are offered to R14 alongside the code references,
    # because a DDIC object has no code at all and this is the only place it can speak.
    refs = [t for t in (sig.get("idoc_refs") or "").split("|") if t]
    for mod, ev in R.idoc_hits(cfg, name, otype, text, refs, R.text_words(text)):
        att.add(mod, R.STRONG, "R14", ev)

    for mod, ev in R.fugr_include_hits(cfg, name):
        att.add(mod, R.STRONG, "R15", ev)

    for mod, ev in R.wrapper_hits(cfg, name):
        att.add(mod, R.STRONG, "R9", ev)

    for mod, ev in R.family_hits(cfg, name):
        att.add(mod, R.STRONG, "R6", ev)

    for mod, ev in R.name_tokens(cfg, name, otype):
        att.add(mod, R.STRONG, "R5", ev)

    # R18: the data elements the fields are typed with, and this estate's own naming
    # convention read off the custom ones -- the same trick that already reads custom
    # TABLE names, applied one level down.
    elements = [e for e in (sig.get("data_elements") or "").split("|") if e]
    for mod, ev in R.data_element_hits(cfg, elements):
        att.add(mod, R.STRONG, "R18", ev)
    for el in elements:
        for mod, _ev in R.family_hits(cfg, el) or R.name_tokens(cfg, el):
            att.add(mod, R.INFERRED, "R18", f"field-type:{el}")
    for fn in (f for f in (sig.get("field_names") or "").split("|") if f):
        for mod, _ev in R.family_hits(cfg, fn):
            att.add(mod, R.INFERRED, "R18", f"field-name:{fn}")

    # Content. For a DDIC object the table set is not a set of reads -- it is the
    # object's own base tables and foreign keys, which is a much sharper fact than a
    # SELECT somewhere in a 1,000-line program. It is still only INFERRED, and still
    # only the leading module, so a structure with keys into three modules does not tick
    # three columns off a definition alone.
    if not cfg.is_infrastructure(name, fanin.get(name, 0)):
        tabs = [t for t in (sig.get("std_tables") or "").split("|") if t]
        counts = collections.Counter()
        for t in tabs:
            mod = cfg.table_to_module.get(t)
            if mod:
                counts[mod] += 1
        if counts:
            top = max(sorted(counts.items()), key=lambda kv: kv[1])
            att.add(top[0], R.INFERRED, "R7",
                    f"tables:{top[0]}({top[1]} of {len(tabs)})")

    for mod, ev in R.text_names_standard(cfg, text):
        att.add(mod, R.INFERRED, "R8s", ev)

    for mod, ev in R.text_hits(cfg, text) \
            or R.text_hits(cfg, sig.get("text_all", "")):
        att.add(mod, R.WEAK, "R8", ev)

    # Only when nothing at all was named. An object whose evidence named a module the
    # config rules OUT is not unknown -- it is out of scope, and saying "stub, no data
    # access" over the top of that loses the decision and invites someone to re-take
    # it. Four SAP sample forms for QM and PM were reported as empty technical assets
    # while the ladder had correctly identified them.
    if not att.best and not att.suppressed:
        for mod, ev in _no_business_content(cfg, cov, sig):
            att.add(mod, R.INFERRED, "R16", ev)

    for mod, authority in att.best.items():
        cov.add(mod, authority, "", "")
    cov.rules = list(att.rules)
    cov.evidence = list(att.evidence)
    cov.suppressed = set(att.suppressed)
    return cov


def _no_business_content(cfg, cov, sig):
    """"There is nothing here" is an answer, and a better one than silence.

    Three shapes, all of them real and all of them technical:

      a stub        a four-line include holding a `BREAK <username>`, a report whose
                    body is `WRITE 'Hi'`. Dead code and a cleanup candidate -- saying
                    so is actionable, where leaving it blank reads as a failure of the
                    index.
      a formatting  a SmartStyle, a page format, a MIME logo. No logic to read and no
      asset         naming convention to match; the type itself is the whole answer.
      unreferenced  a data element typed CHAR30 that nothing in the estate uses. It has
      DDIC          no owner because it has no use, which is worth reporting as such.

    All three go to the technical bucket at LOW confidence with the reason recorded, and
    if the site configured no technical bucket the reason is written to the note instead
    -- never forced into a business module.
    """
    reason = ""
    if cov.otype in cfg.presentation_types:
        reason = f"formatting/media asset ({cov.otype}), no business logic"
    elif cov.otype in ("PROG", "FUGR", "CLAS", "INTF"):
        reason = _stub_reason(cfg, cov, sig)
    elif cov.otype in ("DTEL", "DOMA", "TTYP", "TABL", "VIEW") \
            and not cov.consumers:
        reason = f"unreferenced {cov.otype}, no business signal in name or text"
    elif cov.otype in ("FORM", "SSFO", "SFPF") and not cov.consumers \
            and not (cov.text or "").strip():
        # A form with no short text, no consumer and no content -- SAP's own
        # Y-namespace sample forms sit in customer packages like this. Nothing to
        # attribute, and saying so beats an invented module.
        reason = f"{cov.otype} with no short text, no content and no consumer"
    if not reason:
        return []
    bucket = cfg.technical_bucket or cfg.integration_bucket
    if bucket:
        return [(bucket, reason)]
    cov.note = reason
    return []


def _stub_reason(cfg, cov, sig):
    """'This object does nothing' is an answer, and a better one than silence.

    A four-line include holding a `BREAK <username>`, or a report whose body is
    `WRITE 'Hi'`, has no module because it has no behaviour. Saying so is honest and
    actionable -- it is dead code and a cleanup candidate -- where leaving it
    unclassified reads as a failure of the index. The test is deliberately strict: it
    must have source, be tiny, and touch no table, no form and no external call.
    """
    if cov.otype not in ("PROG", "FUGR", "CLAS", "INTF"):
        return ""
    try:
        loc = int(sig.get("loc") or 0)
    except ValueError:
        return ""
    if loc == 0 or loc > cfg.tuning["stub_max_loc"]:
        return ""
    for field in ("std_tables", "custom_tables", "std_calls", "forms", "external_comm",
                  "idoc_refs", "std_tables_written"):
        if (sig.get(field) or "").strip():
            return ""
    return f"stub: {loc} lines, no data access, no calls"


# --- inheritance ----------------------------------------------------------------------
def _inherit(cfg, cov, sources, kind, edge_label):
    """Give an empty object the modules of the objects around it.

    Union, then narrow: if the consumers between them name more modules than the
    breadth cap allows, only those a majority of them agree on survive. A domain shared
    by an MM table and an FI table is genuinely both; a domain reached from nine
    different modules is evidence of nothing and must not tick nine columns.
    """
    counts = collections.Counter()
    contributors = 0
    for src in sources:
        mods = src.mods
        if not mods:
            continue
        contributors += 1
        for mod in mods:
            counts[mod] += 1
    if not contributors:
        return False
    cap = cfg.tuning["breadth_cap"]
    mods = list(counts)
    if len(mods) > cap:
        # The majority test only means anything with more than one donor. Applied to a
        # single donor it demanded two votes that could never exist, so an object whose
        # one donor was itself multi-module -- a maintenance object over a five-module
        # table -- inherited NOTHING and was reported as a gap. Fall through to the
        # leading modules instead of returning empty.
        if contributors > 1:
            need = (contributors + 1) // 2
            mods = [m for m in mods if counts[m] >= need]
        if not mods or len(mods) > cap:
            mods = [m for m, _ in counts.most_common(cap)]
    if not mods:
        return False
    # Unanimous inheritance from a single named consumer is worth more than a vote
    # across many, so it keeps STRONG; anything else is LOW by construction.
    unanimous = contributors == 1 or all(counts[m] == contributors for m in mods)
    authority = R.STRONG if unanimous and len(mods) <= 2 else R.INFERRED
    for mod in mods:
        cov.add(mod, authority, "R17",
                f"{edge_label}:{contributors} {kind}")
    cov.how = kind
    return True


def _inherited_primary(donors, unit_primary, mods):
    """Owner for a unit whose ticks came from somewhere else: ask that somewhere else.

    Falling back on mods[0] means the config's module list decides the owner, which is
    both arbitrary and invisible -- a variant of a PM transaction was reported as MM
    purely because MM is typed first under modules.core. Where a donor already carries a
    primary that this unit also ticks, that verdict is the answer; it was reached with
    the donor's full evidence, which is more than this unit has by definition.
    """
    for d in donors:
        for uid in getattr(d, "units", ()):
            p = unit_primary.get(uid, "")
            if p in mods:
                return p
    return mods[0]


def run(cfg, verbose=True):
    # One row per (name, type), but edges are keyed by name alone and so is coverage:
    # 'ZXX_TM_SCHEDULE' is a table, a maintenance function group and a T-Code, all the same
    # thing to a consultant. Keeping only the first row silently threw away the table's
    # field types -- the only evidence any of the three had -- and left all three
    # unattributed. So the rows are MERGED per name: pipe-joined signals are unioned,
    # the first non-empty text wins, and loc is summed.
    JOINED = ("std_tables", "std_tables_written", "std_calls", "custom_tables",
              "idoc_refs", "data_elements", "field_names", "forms", "msg_classes",
              "auth_objects")
    signals, fanin = {}, collections.Counter()
    with cfg.work("object_signals.tsv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            cur = signals.get(row["object_name"])
            if cur is None:
                signals[row["object_name"]] = dict(row)
                continue
            for col in JOINED:
                merged = {v for v in (cur.get(col) or "").split("|") if v}
                merged |= {v for v in (row.get(col) or "").split("|") if v}
                cur[col] = "|".join(sorted(merged))
            for col in ("text_primary", "text_secondary", "text_all",
                        "progname", "param"):
                if not (cur.get(col) or "").strip():
                    cur[col] = row.get(col, "")
            try:
                cur["loc"] = str(int(cur.get("loc") or 0) + int(row.get("loc") or 0))
            except ValueError:
                pass

    fpath = cfg.work("fanin.tsv")
    if fpath.exists():
        with fpath.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                name, n = line.rstrip("\n").split("\t")
                fanin[name] = int(n)

    packages = {}
    pmap = cfg.work("object_package_map.tsv")
    if pmap.exists():
        with pmap.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                packages.setdefault(row["object_name"], row["package"])

    unatt_reason = {}
    upath = cfg.work("unattached.tsv")
    if upath.exists():
        with upath.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                unatt_reason[row["object_name"]] = row.get("reason", "")

    # --- the objects -----------------------------------------------------------------
    cov = {}
    for name, sig in signals.items():
        c = Cov(name, sig["object_type"], packages.get(name, ""),
                (sig.get("text_primary") or "").strip())
        c.otype = _best_type(cfg, name, sig)
        c.note = unatt_reason.get(name, "")
        cov[name] = c

    # --- seed from the unit attribution ----------------------------------------------
    mpath = cfg.work("module_matrix.tsv")
    unit_rows, unit_cols = [], []
    with mpath.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        unit_cols = list(rd.fieldnames)
        unit_rows = list(rd)
    unit_mods, unit_primary = {}, {}
    for row in unit_rows:
        unit_mods[row["unit_id"]] = [m for m in cfg.all_modules
                                     if (row.get(m) or "").strip()]
        unit_primary[row["unit_id"]] = (row.get("primary_module") or "").strip()

    def seed(name, uid, how):
        c = cov.get(name)
        if c is None:
            return
        c.units.append(uid)
        mods = unit_mods.get(uid, [])
        if not mods:
            return
        if not c.mods:
            c.how = how
        for mod in mods:
            c.add(mod, R.AUTHORITATIVE if how == "unit-root" else R.STRONG,
                  "R0", f"{how}:{uid}")

    for row in unit_rows:
        seed(row["root_object"], row["unit_id"], "unit-root")
    with cfg.work("unit_members.tsv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            seed(row["member"], row["unit_id"], "unit-member")

    seeded = sum(1 for c in cov.values() if c.mods)

    # --- the graph, both directions ---------------------------------------------------
    consumers = collections.defaultdict(list)     # component -> [(src, edge_type)]
    children = collections.defaultdict(list)      # container -> [tgt]
    with cfg.work("edges.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            src, tgt, et = (row["source_object"], row["target_object"],
                            row["edge_type"])
            consumers[tgt].append((src, et))
            children[src].append((tgt, et))
    for name, c in cov.items():
        c.consumers = len(consumers.get(name, ()))

    # What each object is defined BY or entered THROUGH, including targets that were
    # never exported. Ordered longest-name-first so 'SAPLSVAR' loses to a real
    # transaction code when an object carries both.
    anchor_targets = {}
    for name in cov:
        seen, out = set(), []
        for tgt, et in children.get(name, ()):
            if et in cfg.definitional_edges or et in cfg.entry_edges:
                if tgt not in seen and tgt != name:
                    seen.add(tgt)
                    out.append(tgt)
        anchor_targets[name] = out

    # --- 1 & 3. inherit, to a fixed point ---------------------------------------------
    def propagate():
        filled = 0
        for _ in range(MAX_ITERATIONS):
            changed = 0
            for name in sorted(cov):
                c = cov[name]
                if c.mods:
                    continue
                # Definitional first: "this object IS that object" (a table type
                # is its row type, a maintenance object is about its table, a screen
                # variant is a variant of its program) beats "something that uses this
                # object is MM". Six table types and three maintenance objects reach a
                # module only this way -- they have no consumers at all, because what
                # they point at is their own definition.
                defn = [cov[t] for t, et in children.get(name, ())
                        if t in cov and et in cfg.definitional_edges]
                if _inherit(cfg, c, defn, "via-definition", "defined-by"):
                    changed += 1
                    continue
                if c.otype in cfg.container_types:
                    kids = [cov[t] for t, _et in children.get(name, ())
                            if t in cov]
                    if _inherit(cfg, c, kids, "via-children", "children"):
                        changed += 1
                        continue
                    # A Query user group is named BY its queries, not the other way
                    # round -- the edge runs query -> group -- so a container with no
                    # children still has members, on its inbound side.
                    members_in = [cov[s] for s, _et in consumers.get(name, ())
                                  if s in cov]
                    if _inherit(cfg, c, members_in, "via-children", "members"):
                        changed += 1
                    continue
                comp = [cov[s] for s, et in consumers.get(name, ())
                        if s in cov and et in cfg.composition_edges]
                if _inherit(cfg, c, comp, "via-consumer", "used-by"):
                    changed += 1
                    continue
                any_in = [cov[s] for s, _et in consumers.get(name, ()) if s in cov]
                if _inherit(cfg, c, any_in, "via-reference", "referenced-by"):
                    changed += 1
            filled += changed
            if not changed:
                break
        return filled

    by_inherit_1 = propagate()

    # --- 2. the per-object ladder -----------------------------------------------------
    by_rules = 0
    for name in sorted(cov):
        c = cov[name]
        if c.mods:
            continue
        object_rules(cfg, c, signals.get(name), fanin,
                     anchor_targets.get(name, ()))
        if c.mods:
            c.how = "own-evidence"
            by_rules += 1

    by_inherit_2 = propagate()

    # A ruled-out decision travels down the chain too. 'ZVAR12_0500' is a screen
    # variant inside transaction variant 'ZVAR12', which is a variant of IH09, which is
    # Plant Maintenance -- and PM is declared not in scope. Without this the leaf reads
    # as an unexplained gap while its own parent carries a recorded decision, which
    # invites someone to make the decision a second time.
    for _ in range(MAX_ITERATIONS):
        changed = 0
        for name in sorted(cov):
            c = cov[name]
            if c.mods or c.suppressed:
                continue
            donors = [cov[t] for t, et in children.get(name, ())
                      if t in cov and et in cfg.definitional_edges]
            donors += [cov[s_] for s_, et in consumers.get(name, ())
                       if s_ in cov and et in cfg.composition_edges]
            inherited = set()
            for d in donors:
                if d.mods:
                    inherited.clear()
                    break
                inherited |= d.suppressed
            if inherited:
                c.suppressed = inherited
                changed += 1
        if not changed:
            break

    # --- units that ended with no tick at all -----------------------------------------
    # A unit is unclassified when nothing inside it spoke. Whatever REFERENCES its root
    # still might: the logon exit that calls a T-Code names the T-Code's module even
    # though the T-Code's own name and screen say nothing. Recorded as its own rule so
    # the workbook never shows an inherited tick as if a real signal had fired.
    added_units = 0
    for row in unit_rows:
        if unit_mods.get(row["unit_id"]):
            continue
        root = row["root_object"]
        c = cov.get(root)
        donors = [cov[t] for t, et in children.get(root, ())
                  if t in cov and et in cfg.definitional_edges] \
            or [cov[s] for s, _et in consumers.get(root, ()) if s in cov]
        # The real short text, not "". Built empty, this Cov could not fire a single
        # text rule and reported "no short text" on objects whose title was right
        # there -- one of them read 'Certificate of Origin EU'.
        tmp = Cov(root, row["root_type"], row.get("package", ""),
                  (signals.get(root, {}).get("text_primary") or "").strip())
        tmp.consumers = len(consumers.get(root, ()))
        if not _inherit(cfg, tmp, donors, "via-consumer", "referenced-by"):
            object_rules(cfg, tmp, signals.get(root), fanin,
                         anchor_targets.get(root, ()))
            if tmp.mods:
                pass
            elif c is not None and c.mods and c.rules != ["R0"]:
                tmp.mods, tmp.rules, tmp.evidence = c.mods, c.rules, c.evidence
            else:
                continue
        mods = [m for m in cfg.all_modules if m in tmp.mods]
        if not mods:
            continue
        for m in mods:
            row[m] = "X"
        row["UNCLASSIFIED"] = ""
        row["module_count"] = str(len(mods))
        row["primary_module"] = _inherited_primary(donors, unit_primary, mods)
        row["confidence"] = R.CONFIDENCE[max(tmp.mods.values(),
                                             key=lambda a: R._RANK[a])]
        row["rules_fired"] = ";".join(tmp.rules)
        row["evidence"] = "; ".join(tmp.evidence[:6])
        note = (row.get("notes") or "").strip()
        row["notes"] = (note + "; " if note else "") + "attributed by residual pass"
        if c is not None:
            c.mods, c.rules, c.evidence = tmp.mods, tmp.rules, tmp.evidence
            # tmp.how first: a rescued unit whose ticks were INHERITED must not be
            # labelled "own-evidence" while carrying an inheritance evidence clause.
            c.how = c.how or tmp.how or "own-evidence"
        added_units += 1

    out_matrix = cfg.work("module_matrix.residual.tsv")
    with out_matrix.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=unit_cols, delimiter="\t",
                           lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(unit_rows)

    # Label the ruled-out rows BEFORE writing, not after. Running this after the write
    # left the deliverable saying GAP on rows the summary counted as decisions -- the
    # workbook and the validation report disagreeing about the same three objects, which
    # is worse than either answer alone.
    for c in cov.values():
        if not c.mods and c.suppressed:
            c.how = "ruled-out"
            c.note = "; ".join(
                f"only answer is {m}, which is out of scope: "
                f"{cfg.not_modules.get(m, 'declared not a module')}"
                for m in sorted(c.suppressed))

    # --- write -------------------------------------------------------------------------
    out = cfg.work("coverage_by_object.tsv")
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(COLUMNS)
        for name in sorted(cov):
            w.writerow(cov[name].row(cfg))

    covered = [c for c in cov.values() if c.mods]
    ruled_out = [c for c in cov.values() if not c.mods and c.suppressed]
    gaps = [c for c in cov.values() if not c.mods and not c.suppressed]
    by_how = collections.Counter(c.how or "GAP" for c in cov.values())
    stats = {
        "objects": len(cov),
        "covered": len(covered),
        "coverage_pct": round(100.0 * len(covered) / max(1, len(cov)), 1),
        "gaps": len(gaps),
        "ruled_out": len(ruled_out),
        "accounted_for": len(covered) + len(ruled_out),
        "accounted_pct": round(100.0 * (len(covered) + len(ruled_out))
                               / max(1, len(cov)), 1),
        "seeded_by_units": seeded,
        "filled_by_inheritance": by_inherit_1 + by_inherit_2,
        "filled_by_own_evidence": by_rules,
        "units_rescued": added_units,
        "by_how": dict(by_how),
        "by_confidence": dict(collections.Counter(c.confidence for c in covered)),
        "gap_types": dict(collections.Counter(c.otype for c in gaps)),
    }
    cfg.work("residual.json").write_text(json.dumps(stats, indent=2),
                                         encoding="utf-8")

    if verbose:
        print(f"objects {len(cov)} | ticked {len(covered)} "
              f"({stats['coverage_pct']}%) | ruled out {len(ruled_out)} | "
              f"unaccounted {len(gaps)}")
        print(f"  seeded by units          {seeded}")
        print(f"  filled by inheritance    {by_inherit_1 + by_inherit_2}")
        print(f"  filled by own evidence   {by_rules}")
        print(f"  unclassified units fixed {added_units}")
        print("\nhow each object reached a module:")
        for how, n in by_how.most_common():
            print(f"  {how:<16} {n:>5}")
        if gaps:
            print(f"\nstill unattributed ({len(gaps)}):")
            for c in sorted(gaps, key=lambda c: (c.otype, c.name))[:40]:
                print(f"  {c.otype:<5} {c.name:<32} {(c.note or c.text)[:52]}")
            if len(gaps) > 40:
                print(f"  ... and {len(gaps) - 40} more, in {cfg.rel(out)}")
        print(f"\nwrote {cfg.rel(out)}")
        print(f"wrote {cfg.rel(out_matrix)}")
    return stats
