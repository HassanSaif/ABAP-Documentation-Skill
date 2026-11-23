"""
units.py -- the entry-point unit model, and the sweep that builds it.

A UNIT is an entry point plus its entire nesting. Children get no row of their own;
they are folded into the root and contribute their evidence to it. This is the model a
functional consultant actually asks for:

    "the T-Code calls a program, and this program has include programs, and those may
     contain function modules and so on -- treat the whole nesting as ONE object
     related to the T-Code"

Root kinds, in resolution order. Order matters: everything reachable from a primary
root is a member, so orphan roots can only be claimed after the primary sweep.

  primary   TRAN, OData services, SICF (custom handler only), Web Dynpro, ENHO, SXCI,
            CMOD, CDS (only when not consumed by another CDS), RAP bindings, service
            proxies
  fallback  PROG/CLAS/FUGR/INTF reachable from nothing -- real code with no entry
            point, which is itself a finding, not a gap
  extra     forms and variants, which have no inbound edge in any static export
  demoted   DDIC, config, includes and generated twins (never earn a row)

The identity `roots + folded members + unattached == every object scanned` is asserted
at the end. If it does not close, something was silently dropped, and the deliverable
would be quietly incomplete rather than loudly wrong.
"""

import collections
import csv

from . import graph as G
from . import names as N

csv.field_size_limit(10_000_000)


class Unit:
    __slots__ = ("root", "root_type", "role", "members", "entry", "unit_id")

    def __init__(self, root, root_type, role):
        self.root = root
        self.root_type = root_type
        self.role = role
        self.members = []      # dicts: name, type, hop, parent, edge_type
        self.entry = ""
        self.unit_id = ""

    @property
    def member_names(self):
        return [m["name"] for m in self.members]


def role_rank(cfg, role):
    try:
        return cfg.role_order.index(role)
    except ValueError:
        return len(cfg.role_order)


def walk(root, graph, objects, cfg, claimed=None):
    """BFS from root over the fold-edges, returning members with parent/hop/edge_type.

    Standard-SAP targets are evidence, not members -- they are not custom objects and
    cannot be walked into. `claimed` excludes objects already owned as a primary root,
    so two roots can never absorb each other.
    """
    max_hops = cfg.tuning["max_hops"]
    members, seen = [], {root}
    frontier = collections.deque([(root, 0, "", "")])
    while frontier:
        name, hop, parent, etype = frontier.popleft()
        if hop:
            members.append({"name": name, "type": objects.get(name, "?"),
                            "hop": hop, "parent": parent, "edge_type": etype})
        if hop >= max_hops:
            continue
        for et, tgt, _tt in graph.adj.get(name, ()):
            if et not in cfg.fold_edges or tgt in seen:
                continue
            if not N.is_custom(tgt, cfg.custom_prefixes):
                continue
            if claimed and tgt in claimed:
                continue
            seen.add(tgt)
            frontier.append((tgt, hop + 1, name, et))
    return members


def entry_of(name, graph, cfg):
    """The object this unit enters through, by configured edge priority.

    A variant, a parameter transaction, a dialog module and a query all HAVE an entry
    point -- it is just not stated in <PGMNA>. Taking only TCODE_PGM leaves every one
    of them with no entry and therefore no attribution, which is exactly how most of an
    estate's screen variants end up UNCLASSIFIED.
    """
    by_edge = {}
    for et, tgt, _tt in graph.adj.get(name, ()):
        by_edge.setdefault(et, tgt)
    for et in cfg.entry_edges:
        if et in by_edge:
            return by_edge[et]
    return ""


def enumerate_roots(cfg, objects, signals, graph):
    """Decide which objects are roots, and with what role.

    Returns (roots, notes): roots is [(name, type, role)]; notes explains, per object,
    why something that looks like a root is not one -- that text ends up in the
    Unattached sheet, so a reader can always see the reason.
    """
    by_type = collections.defaultdict(list)
    for name, otype in objects.items():
        by_type[otype].append(name)

    roots, notes = [], {}

    for name in sorted(by_type.get("TRAN", [])):
        roots.append((name, "TRAN", "T-Code"))

    for t in ("IWSG", "IWSV", "IWPR"):
        for name in sorted(by_type.get(t, [])):
            roots.append((name, t, cfg.role_by_type.get(t, "OData service")))

    # SICF: only nodes with a CUSTOM handler. The overwhelming majority of ICF nodes in
    # a Gateway system are auto-generated OData twins pointing at /IWFND/ classes --
    # they are not custom endpoints and giving them rows drowns the real ones.
    for name in sorted(by_type.get("SICF", [])):
        handler = ((signals.get((name, "SICF")) or {}).get("icf_handler") or "").upper()
        if handler.startswith("/IWFND/"):
            notes[name] = "auto-generated OData ICF node"
        elif not handler:
            notes[name] = "ICF node with no handler"
        else:
            roots.append((name, "SICF", cfg.role_by_type.get("SICF",
                                                             "REST / ICF endpoint")))

    for name in sorted(by_type.get("ENHO", [])):
        tool = ((signals.get((name, "ENHO")) or {}).get("enho_tool") or "").upper()
        roots.append((name, "ENHO",
                      cfg.enho_roles.get(tool, "Enhancement implementation")))
    for t in ("SXCI", "CMOD"):
        for name in sorted(by_type.get(t, [])):
            roots.append((name, t, cfg.role_by_type.get(t, t)))

    # CDS: a view consumed by another CDS is a member of that one, not a root.
    consumed = set()
    for _src, out in graph.adj.items():
        for et, tgt, _tt in out:
            if et in ("CDS_FROM", "CDS_BASE", "CDS_ASSOCIATED"):
                consumed.add(tgt)
    for name in sorted(by_type.get("DDLS", [])):
        if name in consumed:
            notes[name] = "CDS view consumed by another CDS"
        else:
            roots.append((name, "DDLS", cfg.role_by_type.get("DDLS", "CDS view")))

    # Every remaining configured root type, generically -- so adding a root kind to the
    # knowledge base needs no code change here. The types handled above have their own
    # rules (a filter, a role lookup, or a consumed-by test) and are skipped.
    handled = {"TRAN", "IWSG", "IWSV", "IWPR", "SICF", "ENHO", "SXCI", "CMOD", "DDLS",
               "SPRX"}
    for t in cfg.root_types:
        if t in handled:
            continue
        for name in sorted(by_type.get(t, [])):
            roots.append((name, t, cfg.role_by_type.get(t, t)))

    # SPRX: the consumed service itself, not its generated DDIC sub-objects.
    for name in sorted(by_type.get("SPRX", [])):
        if name.upper().startswith("CLAS"):
            roots.append((name, "SPRX", cfg.role_by_type.get("SPRX",
                                                             "Consumed service proxy")))
        else:
            notes[name] = "service-proxy DDIC sub-object"

    return roots, notes


def classify_prog_role(cfg, subc, is_tcode_entry, reached):
    """Programs split four ways. <SUBC> is the axis a file-name inventory never sees."""
    if subc == "I":
        return None, "include"
    if is_tcode_entry:
        return "T-Code main program", None
    if not reached:
        return cfg.role_by_type.get("PROG", "Standalone program (no entry point)"), None
    return None, "subordinate program (reached from another unit)"


# --- build ----------------------------------------------------------------------------
def build(cfg, verbose=True):
    signals, types_by_name = {}, collections.defaultdict(set)
    with cfg.work("object_signals.tsv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            signals[(row["object_name"], row["object_type"])] = row
            types_by_name[row["object_name"]].add(row["object_type"])
    objects = {}
    for name, ts in types_by_name.items():
        objects[name] = next((t for t in cfg.type_priority if t in ts), sorted(ts)[0])

    packages = {}
    pmap = cfg.work("object_package_map.tsv")
    if pmap.exists():
        with pmap.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                packages.setdefault(row["object_name"], row["package"])

    graph = G.Graph.load(cfg)

    # Third-party code gets no row and is never folded into a unit. Left in, abap2xlsx
    # alone puts ~78 UNCLASSIFIED ZCL_EXCEL* classes on sheet 1.
    excluded = {n for n, p in packages.items() if p in cfg.excluded_packages}
    excluded |= {n for n in objects if cfg.is_third_party_name(n)}
    if verbose:
        print(f"objects {len(objects)} | signals {len(signals)} | "
              f"edge sources {len(graph.adj)} | third-party excluded {len(excluded)}")

    primary, notes = enumerate_roots(cfg, objects, signals, graph)
    primary = [(n, t, r) for n, t, r in primary if n not in excluded]
    primary_names = {n for n, _t, _r in primary}
    barrier = primary_names | excluded

    units, claimed = [], set()
    for name, otype, role in primary:
        u = Unit(name, otype, role)
        u.members = walk(name, graph, objects, cfg, claimed=barrier)
        u.entry = entry_of(name, graph, cfg)
        # A custom T-Code with no custom member is a parameterised entry into standard
        # SAP -- ZACC -> /NFB01 with a document type defaulted, ZBC01 -> RSUSR200.
        # That is customizing, not custom code, and saying so is far more useful to a
        # consultant than leaving the row looking like missing data.
        if otype == "TRAN" and not u.members:
            u.role = "T-Code (parameterised - no custom code)"
        units.append(u)
        claimed.update(u.member_names)

    # --- fallback roots: real code reachable from nothing ------------------------------
    tcode_entries = {u.entry for u in units if u.entry}
    fallback = []
    for name, otype in sorted(objects.items()):
        if otype not in ("PROG", "CLAS", "FUGR", "INTF"):
            continue
        if name in primary_names or name in claimed or name in excluded:
            continue
        if otype == "PROG":
            subc = ((signals.get((name, "PROG")) or {}).get("subc") or "").upper()
            role, why = classify_prog_role(cfg, subc, name in tcode_entries, False)
            if role is None:
                notes[name] = why
                continue
        else:
            role = cfg.role_by_type.get(otype, otype)
        fallback.append((name, otype, role))

    fallback_names = {n for n, _t, _r in fallback}
    for name, otype, role in fallback:
        u = Unit(name, otype, role)
        u.entry = entry_of(name, graph, cfg)
        u.members = walk(name, graph, objects, cfg,
                         claimed=(barrier | fallback_names) - {name})
        units.append(u)
        claimed.update(u.member_names)

    # --- forms and variants ------------------------------------------------------------
    # Form selection is config-driven (output determination / NAST), which no source
    # export contains, so most forms have no inbound edge and would vanish. They are
    # real objects a consultant owns -- give them a row.
    extra = []
    for name, otype in sorted(objects.items()):
        if otype not in cfg.unreferenced_deliverables:
            continue
        if name in primary_names or name in claimed or name in excluded:
            continue
        extra.append((name, otype, cfg.role_by_type.get(otype, otype)))
    for name, otype, role in extra:
        u = Unit(name, otype, role)
        # Variants live here, and their whole attribution comes from the standard or
        # custom object they are a variant OF.
        u.entry = entry_of(name, graph, cfg)
        u.members = walk(name, graph, objects, cfg, claimed=barrier)
        units.append(u)
        claimed.update(u.member_names)

    units.sort(key=lambda u: (role_rank(cfg, u.role), u.role, u.root))
    for i, u in enumerate(units, start=1):
        u.unit_id = f"U{i:04d}"
    root_names = {u.root for u in units}

    # --- unattached ---------------------------------------------------------------------
    unattached = []
    for name, otype in sorted(objects.items()):
        if name in root_names or name in claimed:
            continue
        demote_reasons = cfg.k.get("object_types", {}).get("demote_reasons", {})
        reason = ("third-party - out of scope" if name in excluded
                  else notes.get(name)
                  or demote_reasons.get(otype)
                  or ("DDIC / config (attributed via its consumer)"
                      if otype in cfg.demote_types
                      else "no inbound edge and not a root kind"))
        unattached.append((name, otype, packages.get(name, ""), reason))

    # --- write ---------------------------------------------------------------------------
    with cfg.work("units.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["unit_id", "root_object", "root_type", "role", "entry_program",
                    "member_count", "member_types"])
        for u in units:
            mt = collections.Counter(m["type"] for m in u.members)
            w.writerow([u.unit_id, u.root, u.root_type, u.role, u.entry,
                        len(u.members),
                        "; ".join(f"{t} {n}" for t, n in sorted(mt.items()))])

    with cfg.work("unit_members.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["unit_id", "root_object", "member", "type", "hop", "parent",
                    "edge_type"])
        for u in units:
            for m in sorted(u.members, key=lambda x: (x["hop"], x["name"])):
                w.writerow([u.unit_id, u.root, m["name"], m["type"], m["hop"],
                            m["parent"], m["edge_type"]])

    with cfg.work("unattached.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["object_name", "object_type", "package", "reason"])
        w.writerows(unattached)

    # Closures legitimately reach names that do NOT exist in the tree -- code
    # referencing packages that were never exported. Those are dangling references, not
    # members, and must not inflate the reconciliation. Supplying the missing package
    # is what shrinks this list.
    member_objs = claimed & set(objects)
    dangling = sorted(claimed - set(objects))
    with cfg.work("dangling_refs.tsv").open("w", encoding="utf-8",
                                            newline="\n") as fh:
        fh.write("referenced_object\n")
        for n in dangling:
            fh.write(n + "\n")

    total = len(root_names | member_objs) + len(unattached)
    ok = total == len(objects)
    if verbose:
        print(f"\nUNITS: {len(units)}")
        for role, n in collections.Counter(u.role for u in units).most_common():
            print(f"  {role:<44} {n:>5}")
        print("\nreconciliation")
        print(f"  unit roots            {len(root_names):>6}")
        print(f"  folded members        {len(member_objs):>6}")
        print(f"  unattached            {len(unattached):>6}")
        print(f"  ---------------------------------")
        print(f"  covered               {total:>6}")
        print(f"  objects scanned       {len(objects):>6}")
        print("  OK -- nothing lost" if ok else "  MISMATCH")
        print(f"\n  referenced but ABSENT from the tree: {len(dangling)} "
              "(code calls objects that were never exported)")
        for n in dangling[:8]:
            print(f"      {n}")
        sizes = [len(u.members) for u in units] or [0]
        print(f"\nunit size: max {max(sizes)}, mean {sum(sizes) / len(sizes):.1f}, "
              f"empty {sum(1 for s in sizes if s == 0)}")
    if not ok:
        raise AssertionError(
            f"RECONCILIATION FAILED: {len(root_names)} roots + {len(member_objs)} "
            f"members + {len(unattached)} unattached = {total}, but {len(objects)} "
            "objects were scanned. Something is being dropped silently -- do not ship "
            "this run.")
    return {"units": len(units), "roots": len(root_names),
            "folded_members": len(member_objs), "unattached": len(unattached),
            "dangling": len(dangling), "objects": len(objects)}
