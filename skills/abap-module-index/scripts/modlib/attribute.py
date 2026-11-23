"""
attribute.py -- run the rule ladder over every unit.

Rules fire in order and all contribute; the highest authority reached per
(unit, module) sets the confidence. The interesting engineering is not the rules, it is
the four BRAKES that stop additive rules from smearing every module across every unit:

  1. infrastructure gate  a member with in-degree >= fanin_gate contributes no
                          name/table evidence, only a note. It is plumbing, not
                          business meaning: the most-called object in an estate is
                          typically a logging or utility class used by everything.
  2. hop decay            hop 1 at full strength, hop 2 weak, deeper is evidence only.
                          Package evidence reaches one hop further than name evidence,
                          because a member's home package is an authoritative fact
                          about that member at any depth.
  3. breadth cap          if closure-derived rules alone reach breadth_cap+ core
                          modules, the unit is marked CROSS rather than ticking half
                          the estate.
  4. authority floor      R7/R8 may only REINFORCE a module some R1-R6 signal already
                          supports -- never invent one -- unless nothing at all is
                          known about the unit yet.

Remove any one of these and multi-module attribution climbs sharply, which reads to a
consultant as "the tool has no idea".

Outputs
  module_matrix.tsv       wide form: the tick matrix, one row per unit
  module_attribution.tsv  long form: unit, module, authority, rules, evidence
  proposals.tsv           evidence for modules with no tick column (open vocabulary)
"""

import collections
import csv

from . import rules as R

csv.field_size_limit(10_000_000)


def matrix_columns(cfg):
    return (["unit_id", "root_object", "root_type", "role", "description_primary",
             "description_secondary", "package", "entry_program", "member_count",
             "member_types", "loc_total", "inbound_refs"]
            + cfg.all_modules
            + ["CROSS", "UNCLASSIFIED", "module_count", "primary_module", "confidence",
               "rules_fired", "evidence", "proposed_modules", "notes", "members"])


def _pick(name, by_name):
    rows = by_name.get(name)
    return rows[0] if rows else None


def run(cfg, verbose=True):
    signals, by_name = {}, collections.defaultdict(list)
    with cfg.work("object_signals.tsv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            signals[(row["object_name"], row["object_type"])] = row
            by_name[row["object_name"]].append(row)

    packages = {}
    pmap = cfg.work("object_package_map.tsv")
    if pmap.exists():
        with pmap.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                packages.setdefault(row["object_name"], row["package"])

    fanin = collections.Counter()
    fpath = cfg.work("fanin.tsv")
    if fpath.exists():
        with fpath.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                name, n = line.rstrip("\n").split("\t")
                fanin[name] = int(n)

    anchors = collections.defaultdict(list)
    with cfg.work("edges.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["edge_type"] in cfg.anchor_edges:
                anchors[row["source_object"]].append(row["target_object"])

    units = {}
    with cfg.work("units.tsv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            row["members"] = []
            units[row["unit_id"]] = row
    with cfg.work("unit_members.tsv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            units[row["unit_id"]]["members"].append(
                {"name": row["member"], "type": row["type"], "hop": int(row["hop"]),
                 "parent": row["parent"], "edge_type": row["edge_type"]})

    if verbose:
        print(f"units {len(units)} | signals {len(signals)} | "
              f"packages {len(packages)}")

    rule_hits, marginal = collections.Counter(), collections.Counter()
    long_rows, matrix_rows, proposal_rows = [], [], []
    proposed_totals = collections.Counter()
    suppressed_totals = collections.Counter()

    for uid in sorted(units):
        u = units[uid]
        att, notes = attribute(cfg, u, signals, by_name, packages, fanin, anchors,
                               marginal)
        for mod in att.modules:
            long_rows.append([uid, u["root_object"], mod, att.best[mod],
                              ";".join(r for r in att.rules
                                       if r in att.support.get(mod, ())),
                              ";".join(att.rules), "; ".join(att.evidence)])
        for r in att.rules:
            rule_hits[r] += 1
        for mod, (authority, ev, rule) in sorted(att.proposed.items()):
            proposal_rows.append([uid, u["root_object"], u["role"], mod, authority,
                                  rule, ev])
            proposed_totals[mod] += 1
        for mod in att.suppressed:
            suppressed_totals[mod] += 1

        row = {
            "unit_id": uid, "root_object": u["root_object"],
            "root_type": u["root_type"], "role": u["role"],
            "entry_program": u["entry_program"],
            "member_count": u["member_count"], "member_types": u["member_types"],
            "package": packages.get(u["root_object"], ""),
            # How many objects point at this root. Decisive for the "no entry point"
            # rows: 0 means nothing in the repository references it (a dead-code
            # candidate), while >0 means it IS used, just only by code that itself has
            # no entry point -- mutually-referencing class pairs, or OData MPC/DPC
            # classes whose service registration points at a standard proxy and so
            # cannot be linked from source. Those are NOT dead code.
            "inbound_refs": fanin[u["root_object"]],
            # Set by the breadth trim above: this unit reached past the cap and
            # its excess core ticks were withheld. The notes name them.
            "CROSS": "X" if "cross-module:" in "; ".join(notes) else "",
            "UNCLASSIFIED": "" if att.best else "X",
            "module_count": len(att.modules),
            "primary_module": att.primary_module,
            "confidence": att.confidence,
            "rules_fired": ";".join(att.rules),
            "evidence": "; ".join(att.evidence),
            "proposed_modules": "; ".join(f"{m}({v[0][:4]})"
                                          for m, v in sorted(att.proposed.items())),
            "notes": "; ".join(notes[:3]),
            "members": "; ".join(m["name"] for m in
                                 sorted(u["members"],
                                        key=lambda x: (x["hop"], x["name"]))),
        }
        sig = signals.get((u["root_object"], u["root_type"]), {})
        row["description_primary"] = sig.get("text_primary", "")
        row["description_secondary"] = sig.get("text_secondary", "")
        row["loc_total"] = sum(int((_pick(m["name"], by_name) or {}).get("loc") or 0)
                               for m in u["members"]) + int(sig.get("loc") or 0)
        for mod in cfg.all_modules:
            row[mod] = "X" if mod in att.best else ""
        matrix_rows.append(row)

    with cfg.work("module_attribution.tsv").open("w", encoding="utf-8",
                                                 newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["unit_id", "root_object", "module", "authority",
                    "rules_for_this_module", "rules_for_the_unit", "evidence"])
        w.writerows(long_rows)

    cols = matrix_columns(cfg)
    with cfg.work("module_matrix.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for row in matrix_rows:
            w.writerow([row.get(c, "") for c in cols])

    with cfg.work("proposals.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["unit_id", "root_object", "role", "proposed_module", "authority",
                    "rule", "evidence"])
        w.writerows(proposal_rows)

    stats = report(cfg, matrix_rows, rule_hits, marginal, proposed_totals,
                   suppressed_totals, verbose)
    return stats


def _mutes_evidence(cfg, member):
    return member["edge_type"] in cfg.evidence_mute_edges


def attribute(cfg, u, signals, by_name, packages, fanin, anchors, marginal):
    att = R.Attribution(cfg)
    notes = []
    root, rtype = u["root_object"], u["root_type"]
    root_sig = signals.get((root, rtype), {}) or (_pick(root, by_name) or {})
    members = u["members"]
    entry = u["entry_program"]
    tick_hop = cfg.tuning["tick_max_hop"]
    pkg_hop = cfg.tuning["pkg_max_hop"]

    # --- R1 home package ---------------------------------------------------------------
    before = set(att.best)
    root_pkg = packages.get(root, "")
    if root_pkg in cfg.excluded_packages:
        notes.append(f"third-party package {root_pkg}")
    elif root_pkg:
        for mod in cfg.package_modules.get(root_pkg, []):
            att.add(mod, R.AUTHORITATIVE, "R1", f"pkg:{root_pkg}")
        if root_pkg not in cfg.package_modules:
            notes.append(f"package {root_pkg} has no module mapping")
    for m in members:
        if m["hop"] > pkg_hop or _mutes_evidence(cfg, m):
            continue
        p = packages.get(m["name"])
        if not p or p in cfg.excluded_packages or p == root_pkg:
            continue
        for mod in cfg.package_modules.get(p, []):
            att.add(mod, R.INFERRED, "R1", f"pkg-member:{p}(h{m['hop']})")
    marginal["R1"] += len(set(att.best) - before)

    # --- R2 resolved entry program -----------------------------------------------------
    before = set(att.best)
    if entry:
        hits = R.name_tokens(cfg, entry)
        if hits:
            att.add_many([(mod, f"tcode->prog:{root}->{entry}") for mod, _ in hits],
                         R.AUTHORITATIVE, "R2")
    marginal["R2"] += len(set(att.best) - before)

    # --- R3 enhancement anchor ---------------------------------------------------------
    before = set(att.best)
    cands = [root_sig.get("exit_name", ""), root_sig.get("spot_name", "")]
    cands += anchors.get(root, [])
    for a in cands:
        fired = False
        for part in str(a).split("|"):
            hits = R.badi_hits(cfg, part)
            if hits:
                att.add_many(hits, R.AUTHORITATIVE, "R3")
                fired = True
                break
        if fired:
            break
    # A HOOK_IMPL on a standard program is not a BAdI spot and so reaches none of the
    # table above, but it is just as authoritative about the module: an enhancement of
    # SAPLWPUE is POS-interface code whatever it calls itself.
    if not att.best:
        for a in cands:
            hits = R.std_anchor_hits(cfg, a)
            if hits:
                att.add_many(hits, R.STRONG, "R3")
                break
    marginal["R3"] += len(set(att.best) - before)

    # --- R4 classic exit include names -------------------------------------------------
    before = set(att.best)
    for cand in [root] + [m["name"] for m in members]:
        hits = R.exit_include_hits(cfg, cand)
        if hits:
            att.add_many(hits, R.AUTHORITATIVE, "R4")
            break
    marginal["R4"] += len(set(att.best) - before)

    # --- R10 content: standard tables this unit WRITES ---------------------------------
    # Placed with the authoritative rules, and deliberately NOT subject to the R7/R8
    # authority floor: measured against held-out truth it is the most accurate signal
    # in the ladder, so it is allowed to name a module nothing else supports.
    # It fires rarely -- good ABAP posts through APIs -- but where it fires it is close
    # to definitive, and it is the only rule that reads what the code DOES rather than
    # what it is called.
    before = set(att.best)
    for m in [{"name": root, "hop": 0, "edge_type": ""}] + members:
        if m["hop"] > tick_hop or cfg.is_infrastructure(m["name"], fanin[m["name"]]):
            continue
        sig = _pick(m["name"], by_name)
        if not sig:
            continue
        written = [t for t in (sig.get("std_tables_written") or "").split("|") if t]
        hits = R.write_hits(cfg, written)
        if hits:
            suffix = "" if m["hop"] == 0 else f"(h{m['hop']})"
            att.add_many([(mod, ev + suffix) for mod, ev in hits],
                         R.AUTHORITATIVE, "R10")
    marginal["R10"] += len(set(att.best) - before)

    # --- R12/R13/R14/R15 SAP's own naming families -------------------------------------
    # Four families where SAP, not the customer, chose the name -- so the name is a
    # fact, not a convention. All four were added because they were the ONLY thing that
    # could speak for a whole class of object:
    #
    #   R12 infotype        a custom HR infotype generates ten-plus DDIC objects
    #                       (P9000/PA9000/PS9000/MP900010) with no module token in any
    #                       of them, dispatched from T777D so nothing references them
    #   R13 append          'ZZMC11VA1ITM' and 'CI_BSIS' carry no business words, but
    #                       the base they append to IS the module, and SAP's generated
    #                       short text states it
    #   R14 IDoc            a segment type is a DDIC structure, so `TYPE e1kna1m` reads
    #                       as nothing to a table rule; a message type literal
    #                       ('WBBDLD') names the business process outright
    #   R15 fugr include    'ZLKED2TOP' is the TOP include of a clone of SAP's KED2
    #                       (CO-PA); it declares a FUNCTION-POOL and nothing else
    before = set(att.best)
    for cand in [root] + [m["name"] for m in members if m["hop"] <= tick_hop]:
        for mod, ev in R.infotype_hits(cfg, cand, root_sig.get("text_primary", "")):
            att.add(mod, R.STRONG, "R12", ev)
        for mod, ev in R.append_hits(cfg, cand, root_sig.get("text_primary", "")):
            att.add(mod, R.STRONG, "R13", ev)
        for mod, ev in R.fugr_include_hits(cfg, cand):
            att.add(mod, R.STRONG, "R15", ev)
    marginal["R12"] += len(set(att.best) - before)

    before = set(att.best)
    idoc_refs = set()
    for m in [{"name": root, "hop": 0, "edge_type": ""}] + members:
        if m["hop"] > tick_hop or cfg.is_infrastructure(m["name"], fanin[m["name"]]):
            continue
        sig = _pick(m["name"], by_name)
        if sig:
            idoc_refs.update(t for t in (sig.get("idoc_refs") or "").split("|") if t)
    hits = R.idoc_hits(cfg, root, rtype, root_sig.get("text_primary", ""), idoc_refs,
                       R.text_words(root_sig.get("text_primary", "")))
    if hits:
        att.add_many(hits, R.STRONG, "R14")
    marginal["R14"] += len(set(att.best) - before)

    # --- R5 name tokens across the unit ------------------------------------------------
    before = set(att.best)
    hits = R.name_tokens(cfg, root, rtype)
    if hits:
        att.add_many(hits, R.STRONG, "R5")
    for m in members:
        if m["hop"] > tick_hop or _mutes_evidence(cfg, m):
            continue
        if cfg.is_infrastructure(m["name"], fanin[m["name"]]):
            notes.append(f"shared-infra:{m['name']}"
                         f"(fan-in={fanin[m['name']]})")
            continue
        for mod, _ev in R.name_tokens(cfg, m["name"], m["type"]):
            att.add(mod, R.STRONG if m["hop"] == 1 else R.WEAK, "R5",
                    f"member-name:{m['name']}(h{m['hop']})")
    marginal["R5"] += len(set(att.best) - before)

    # The estate's own table names are name evidence about whatever uses them. Four
    # programs whose TRDIR title was copy-pasted ("Asset Master Data") touch exactly one
    # table, ZXX_WF_PR_CH1 -- the price-change workflow table -- and nothing was reading it.
    before = set(att.best)
    ztabs = set()
    for m in [{"name": root, "hop": 0, "edge_type": ""}] + members:
        if m["hop"] > 1 or cfg.is_infrastructure(m["name"], fanin[m["name"]]):
            continue
        sig = _pick(m["name"], by_name)
        if sig:
            ztabs.update(t for t in (sig.get("custom_tables") or "").split("|") if t)
    for tab in sorted(ztabs):
        for mod, _ev in R.name_tokens(cfg, tab):
            att.add(mod, R.STRONG, "R5", f"own-table:{tab}")
    marginal["R5"] += len(set(att.best) - before)

    # --- R6 special families -----------------------------------------------------------
    before = set(att.best)
    for cand in ([root, entry] + [m["name"] for m in members
                                  if m["hop"] <= tick_hop] + sorted(ztabs)):
        if not cand:
            continue
        hits = R.family_hits(cfg, cand)
        if hits:
            att.add_many(hits, R.STRONG, "R6")
            break
    marginal["R6"] += len(set(att.best) - before)

    # --- R9 standard-object name wrapper -----------------------------------------------
    # Runs with R5/R6 strength, on the root, on whatever the unit enters through, and on
    # hop-1 members. The entry may well be a STANDARD object (F-07, ME21N) -- that is
    # the whole point: the standard transaction being wrapped names the module even
    # when nothing custom in the unit does.
    # Authority depends on WHERE the standard name was found, and the difference is
    # real: an entry resolved from <TSTCP>, <PROGNAME> or <TCODE> is serialised
    # metadata -- the same class of fact as R2 -- and a screen variant of VA01 cannot
    # exist without VA01. The object's own name is only a convention, however reliable.
    before = set(att.best)
    if entry:
        hits = R.wrapper_hits(cfg, entry)
        if hits:
            att.add_many([(m, f"{ev} (resolved entry)") for m, ev in hits],
                         R.AUTHORITATIVE, "R9")
    if not att.best or "R9" not in att.rules:
        for cand in [root] + [m["name"] for m in members if m["hop"] <= 1]:
            hits = R.wrapper_hits(cfg, cand)
            if hits:
                att.add_many(hits, R.STRONG, "R9")
                break
    marginal["R9"] += len(set(att.best) - before)

    # --- R11 external API surface ------------------------------------------------------
    # An RFC-enabled function group is reachable from outside the system. That is a fact
    # from the object's own serialisation, not an inference, and in most estates it means
    # the integration team has a stake alongside whichever module owns the data.
    if cfg.integration_bucket:
        before = set(att.best)
        if rtype in ("WEBI", "SICF", "IWSG", "IWSV", "IWPR", "SRVB"):
            att.add(cfg.integration_bucket, R.STRONG, "R11",
                    f"external endpoint:{rtype}")
        for m in [{"name": root, "hop": 0}] + [x for x in members if x["hop"] <= 1]:
            sig = _pick(m["name"], by_name)
            if not sig:
                continue
            if (sig.get("rfc_fms") or "").strip():
                att.add(cfg.integration_bucket, R.STRONG, "R11",
                        f"rfc-enabled:{m['name']}({sig['rfc_fms']} FMs)")
                break
            if (sig.get("external_comm") or "").strip():
                att.add(cfg.integration_bucket, R.STRONG, "R11",
                        f"outbound:{sig['external_comm'][:40]}({m['name']})")
                break
        marginal["R11"] += len(set(att.best) - before)

    # The authority floor. One loosening was tried and rejected: letting content
    # evidence name a core module whenever only BUCKETS were supported, on the
    # reasoning that a bucket is a concern rather than an owner. It reads well and it
    # over-fires -- it let single table reads name a core module on hundreds of
    # interface units and pushed the leading module's share past the adversarial share
    # gate. A single table read is far too weak to name an owner, whatever else is or is
    # not already ticked.
    supported = set(att.best)

    # --- R18 the standard data elements the unit's own structures are built from -------
    # Under the floor, with R7, because it is the same KIND of evidence: what data the
    # code touches, not what the code is called. Above the floor it read as a naming
    # rule and started naming modules on its own -- a production-cost report grouping by
    # MATKL became an MM owner on the strength of one field type. It may reinforce a
    # module something else already supports, or speak when nothing else has spoken at
    # all, which is exactly the case the DDIC leaves need it for.
    before = set(att.best)
    elements = set()
    for m in [{"name": root, "hop": 0, "edge_type": ""}] + members:
        if m["hop"] > 1 or cfg.is_infrastructure(m["name"], fanin[m["name"]]):
            continue
        sig = _pick(m["name"], by_name)
        if sig:
            elements.update(e for e in (sig.get("data_elements") or "").split("|")
                            if e)
    for mod, ev in R.data_element_hits(cfg, elements):
        if not supported or mod in supported:
            att.add(mod, R.INFERRED, "R18", ev)
    marginal["R18"] += len(set(att.best) - before)


    # --- R7 closure fingerprint --------------------------------------------------------
    before = set(att.best)
    tables, calls = set(), set()
    for m in [{"name": root, "hop": 0, "edge_type": ""}] + members:
        if m["hop"] > tick_hop or _mutes_evidence(cfg, m) \
                or cfg.is_infrastructure(m["name"], fanin[m["name"]]):
            continue
        sig = _pick(m["name"], by_name)
        if not sig:
            continue
        tables.update(t for t in (sig.get("std_tables") or "").split("|") if t)
        calls.update(c for c in (sig.get("std_calls") or "").split("|") if c)
    # Sort before counting. Python randomises string hashing per process, so unsorted
    # set iteration makes Counter insertion order -- and therefore tie-breaking and
    # evidence ordering -- differ between runs. That silently breaks the "a rerun is
    # byte-identical" guarantee the deliverable depends on.
    tables, calls = sorted(tables), sorted(calls)
    tbl_mods = collections.Counter(cfg.table_to_module[t] for t in tables
                                   if t in cfg.table_to_module)
    call_mods = collections.Counter()
    for c in calls:
        mod = R.std_call_module(cfg, c)
        if mod:
            call_mods[mod] += 1

    # --- R7D deep content: many of one module's tables, corroborated by a call -------
    # The authority floor exists because a single table read says almost nothing. But
    # read evidence scales, measured against held-out truth: accuracy climbs steadily
    # with the number of ONE module's tables read -- one table is little better than a
    # coin toss, 5+ tables is good, and 5+ tables plus an agreeing standard call is
    # very good. At that top tier content rivals naming, so it is allowed to name a module
    # nothing else supports -- at STRONG, not AUTHORITATIVE. This is what attributes an
    # RFC API layer whose NAME says nothing: 7 sales tables plus
    # BAPI_SALESORDER_CREATEFROMDAT2 is not ambiguous, whatever the object is called.
    deep_n = cfg.tuning.get("content_deep_tables", 5)
    needs_call = cfg.tuning.get("content_deep_needs_call", True)
    before = set(att.best)
    # ONE module only: the accuracy was measured on the module with the most tables,
    # and implementing "every module with 5+ tables" instead is a different, weaker
    # claim. It also smears: on a large estate it pushed many units onto four or five
    # core modules at once, which the breadth gate correctly refused to ship. Deep content
    # says what a unit looks most like, not everything it touches.
    if tbl_mods:
        mod, cnt = max(sorted(tbl_mods.items()), key=lambda kv: kv[1])
        already = len(att.core_modules)
        room = mod in att.best or mod not in cfg.core             or already < cfg.tuning["breadth_cap"]
        if cnt >= deep_n and (not needs_call or call_mods.get(mod)) and room:
            ev = f"tables-deep:{cnt} {mod} tables"
            if call_mods.get(mod):
                ev += f" + {call_mods[mod]} agreeing call(s)"
            att.add(mod, R.STRONG, "R7D", ev)
        elif cnt >= deep_n and not room:
            notes.append(f"deep-content:{mod} withheld (breadth cap)")
    marginal["R7D"] += len(set(att.best) - before)

    def r7_apply(counter, kind, pool):
        chosen = sorted(m for m, n in counter.items() if n >= 2) or (
            [counter.most_common(1)[0][0]] if counter else [])
        if not chosen or len(chosen) > 2:
            return
        allowed = sorted(m for m in chosen if m in supported) or (
            [] if supported else sorted(chosen))
        if not allowed:
            return
        ev = f"{kind}:" + ",".join(sorted(x for x in pool
                                          if _module_of(cfg, x, kind) in allowed)[:6])
        att.add_many([(m, ev) for m in allowed], R.INFERRED, "R7")

    r7_apply(tbl_mods, "tables", tables)
    r7_apply(call_mods, "std-calls", calls)
    marginal["R7"] += len(set(att.best) - before)

    # --- R8 tie-breakers, only when still empty ----------------------------------------
    before = set(att.best)
    if not att.best:
        appl = root_sig.get("appl") or (
            (_pick(entry, by_name) or {}).get("appl", "") if entry else "")
        if appl in cfg.appl_modules:
            att.add(cfg.appl_modules[appl], R.WEAK, "R8", f"appl:{appl}")
        for cand in (root_sig.get("text_primary", ""),
                     root_sig.get("text_secondary", "")):
            hits = R.text_names_standard(cfg, cand)
            if hits:
                att.add_many(hits, R.INFERRED, "R8s")
                break
        for cand in (root_sig.get("text_primary", ""),
                     root_sig.get("text_secondary", ""),
                     root_sig.get("text_all", "")):
            hits = R.text_hits(cfg, cand)
            if hits:
                att.add_many(hits, R.WEAK, "R8")
                break
    marginal["R8"] += len(set(att.best) - before)

    breadth = len(att.core_modules)
    if breadth > cfg.tuning["breadth_cap"]:
        dropped = att.trim_core_breadth()
        notes.append(f"cross-module: {breadth} core modules, "
                     f"kept {cfg.tuning['breadth_cap']}"
                     + (f", withheld {','.join(dropped)}" if dropped else ""))
    if att.proposed:
        notes.append("proposed: " + ",".join(sorted(att.proposed)))
    # A module a human ruled out was still NAMED by the evidence, and the row must say
    # so. Without this a transaction whose owning module is out of scope shows only its
    # secondary tick, with nothing to explain why -- a reviewer sees 'MM' on a Plant
    # Maintenance transaction and has no way to tell whether the tool missed PM or the
    # config excluded it. Counting it in the summary is not the same as saying it on
    # the row.
    if att.suppressed:
        notes.append("evidence also named " + ",".join(sorted(att.suppressed))
                     + " (ruled out of scope)")

    return att, notes


def _module_of(cfg, name, kind):
    return cfg.table_to_module.get(name) if kind == "tables" \
        else R.std_call_module(cfg, name)


def report(cfg, rows, rule_hits, marginal, proposed, suppressed, verbose=True):
    n = len(rows) or 1
    ticked = sum(1 for r in rows if r["module_count"])
    multi = sum(1 for r in rows if r["module_count"] >= 2)
    conf = collections.Counter(r["confidence"] for r in rows)
    per_module = {m: sum(1 for r in rows if r[m]) for m in cfg.all_modules}
    stats = {
        "units": len(rows), "ticked": ticked, "unclassified": len(rows) - ticked,
        "multi_module": multi, "confidence": dict(conf),
        "per_module": per_module,
        "proposed_modules": dict(proposed.most_common()),
        "suppressed_modules": dict(suppressed.most_common()),
        "rule_hits": dict(rule_hits), "marginal": dict(marginal),
    }
    if not verbose:
        return stats
    print(f"\nUNITS: {len(rows)}")
    print(f"  with >=1 module tick   {ticked:>5}  ({100 * ticked / n:.1f}%)")
    print(f"  UNCLASSIFIED           {len(rows) - ticked:>5}  "
          f"({100 * (len(rows) - ticked) / n:.1f}%)")
    print(f"  module_count >= 2      {multi:>5}  ({100 * multi / n:.1f}%)")
    print(f"  CROSS                  {sum(1 for r in rows if r['CROSS']):>5}")
    print("\nconfidence:")
    for c in ("HIGH", "MEDIUM", "LOW", "NONE"):
        if conf[c]:
            print(f"  {c:<8} {conf[c]:>5}  ({100 * conf[c] / n:.1f}%)")
    print("\nper-module unit counts:")
    for mod, c in per_module.items():
        if c:
            print(f"  {mod:<14} {c:>5}  ({100 * c / n:.1f}%)")
    print("\nrule participation / marginal new ticks:")
    for r in ("R1", "R2", "R3", "R4", "R10", "R5", "R6", "R9", "R11", "R7D", "R7", "R8"):
        print(f"  {r}  fired on {rule_hits[r]:>5} units, "
              f"added {marginal[r]:>5} module ticks no earlier rule had")
    if proposed:
        print("\nPROPOSED modules -- evidence found for areas with no tick column:")
        for mod, c in proposed.most_common():
            print(f"  {mod:<14} {c:>5} units   (run `discover` for the evidence)")
        print("  Adopt them in modules.core/modules.buckets, or rule them out in "
              "modules.not_modules with a reason.")
    if suppressed:
        print("\nsuppressed (declared not modules): "
              + ", ".join(f"{m}={c}" for m, c in suppressed.most_common()))
    return stats
