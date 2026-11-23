#!/usr/bin/env python3
"""
abapGit Inventory Extractor — Phase 1 of the ABAP Documentation methodology.

Walks an abapGit-serialized repository, captures every substantive object family,
and emits one TSV per family into `docs/_index/raw/`.

Critically, every object family that hides its friendly business name behind an
SAP-generated identifier in the filename has BOTH columns extracted:
    - filename-derived "on-disk" name
    - the friendly logical name from inside the XML

No third-party dependencies. Runs against any abapGit `<package>/src/` layout.

Usage:
    python extract.py [--repo-root .] [--output docs/_index/raw]

Output:
    <output>/sicf.tsv      — SICF nodes (ICFALTNME alias; full handler chain)
    <output>/sush.tsv      — SU22/SU24 authorization defaults (hash-named on disk)
    <output>/iwsv.tsv      — OData service definitions
    <output>/iwsg.tsv      — OData service-group registrations
    <output>/iwmo.tsv      — OData model definitions
    <output>/iwom.tsv      — OData model assignments
    <output>/iwvb.tsv      — OData vocabulary bindings
    <output>/enho.tsv      — Enhancement implementations (with target spot)
    <output>/sxci.tsv      — Classic BAdI implementations (SXCI); unions with
                             enho.tsv by name in validate.py, so migrated
                             BAdIs registered in both families count once
    <output>/clas.tsv      — Classes (with superclass + DPC/MPC flag)
    <output>/intf.tsv      — Interfaces
    <output>/fugr.tsv      — Function groups
    <output>/fugr_fm.tsv   — Function modules per FG (with RFC flag)
    <output>/prog.tsv      — Programs (with descript)
    <output>/incl.tsv      — Include programs
    <output>/ddls.tsv      — CDS DDL views (with label)
    <output>/tabl.tsv      — Tables (transparent / pool / cluster)
    <output>/doma.tsv      — Domains
    <output>/dtel.tsv      — Data elements
    <output>/msag.tsv      — Message classes
    <output>/shlp.tsv      — Search helps
    <output>/sush.tsv      — Search-help bundles
    <output>/tobj.tsv      — Auth-object check entries
    <output>/tran.tsv      — T-Codes (with target program)
    <output>/summary.tsv   — Counts per family
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# XML helpers


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _findtext_any(root: ET.Element, *names: str) -> Optional[str]:
    """Return the text of the first element whose local-name matches any given name."""
    targets = {n.upper() for n in names}
    for el in root.iter():
        if _strip_ns(el.tag).upper() in targets:
            txt = (el.text or "").strip()
            if txt:
                return txt
    return None


def _findall_any(root: ET.Element, name: str) -> list[ET.Element]:
    target = name.upper()
    return [el for el in root.iter() if _strip_ns(el.tag).upper() == target]


def _parse(path: Path) -> Optional[ET.Element]:
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as e:
        print(f"  ! parse error in {path}: {e}", file=sys.stderr)
        return None
    except OSError as e:
        print(f"  ! io error in {path}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Per-family extractors


def _handlers(root: ET.Element) -> list[str]:
    """Every ICFHANDLER *field* (leaf) under a node, in document order.

    <ICFHANDLER> names both the row wrapper and the field inside it, so a naive
    search returns wrappers too. A wrapper has children; the field does not.
    """
    out = []
    for el in _findall_any(root, "ICFHANDLER"):
        if len(el) == 0 and (el.text or "").strip():
            out.append((el.text or "").strip())
    return out


def extract_sicf(path: Path) -> Optional[dict]:
    root = _parse(path)
    if root is None:
        return None
    return {
        "icf_name": _findtext_any(root, "ICF_NAME") or "",
        "icf_altnme": _findtext_any(root, "ICFALTNME") or "",
        "icf_docu": _findtext_any(root, "ICF_DOCU") or "",
        # A SICF node holds a handler TABLE, not one handler, and the serialized XML
        # reuses <ICFHANDLER> as BOTH the row wrapper and the field inside the row.
        # Taking "the" handler returns only the first and silently discards the rest;
        # handler chains (ICFORDER 02, 03...) then become invisible, which can hide a
        # handler class that fronts many nodes. Collect the leaf occurrences -- those
        # whose element has no children -- and keep the first separately so existing
        # consumers of the `handler` column keep working.
        "handler": (_handlers(root)[0] if _handlers(root) else ""),
        "handlers": ",".join(_handlers(root)),
        "handler_count": str(len(_handlers(root))),
    }


def extract_bdef(path: Path) -> Optional[dict]:
    """RAP behaviour definition (*.bdef.asbdef) -- plain text, not XML.

    This is where a RAP application's WRITE surface is declared. `create`/`update`/
    `delete` here are the operations an OData V4 client may perform; `managed` vs
    `unmanaged` says who implements them; `authorization master` names the entity that
    owns the authorization decision. A repo can contain a whole modern transactional
    surface that no SEGW artefact mentions.
    """
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    live = "\n".join(l for l in txt.splitlines() if not l.strip().startswith("//"))
    m = re.search(r"define\s+behavior\s+for\s+([A-Za-z0-9_/]+)", live)
    impl = re.search(r"implementation\s+in\s+class\s+([A-Za-z0-9_/]+)", live)
    return {
        "bdef_name": path.name.split(".")[0].split(" ")[0].upper(),
        "for_entity": (m.group(1).upper() if m else ""),
        "impl_class": (impl.group(1).upper() if impl else ""),
        "kind": ("managed" if re.search(r"\bmanaged\b", live) else
                 "unmanaged" if re.search(r"\bunmanaged\b", live) else
                 "abstract" if re.search(r"\babstract\b", live) else ""),
        "operations": ",".join(sorted({o for o in ("create", "update", "delete")
                                       if re.search(r"^\s*%s\s*;" % o, live, re.M)})),
        "strict": "X" if re.search(r"\bstrict\b", live) else "",
    }


def _srvd_ref_name(root) -> str:
    """The service DEFINITION a RAP binding points at: <SRVD_REF><NAME>."""
    for el in root.iter():
        if el.tag.endswith("SRVD_REF"):
            for child in el.iter():
                if child.tag.endswith("NAME") and child.text and child.text.strip():
                    return child.text.strip()
    return ""


def extract_srvb(path: Path) -> Optional[dict]:
    """RAP service binding -- a PUBLISHED OData endpoint, independent of SEGW.

    BIND_TYPE/BIND_TYPE_VERSION distinguish OData V2 from V4 (and UI from Web API).
    These services never appear in *.iwsv.xml, so a repo's OData surface is the union
    of the two families, not the SEGW count alone.
    """
    root = _parse(path)
    if root is None:
        return None
    return {
        "srvb_name": _findtext_any(root, "NAME") or "",
        "descript": _findtext_any(root, "DESCRIPTION") or "",
        "bind_type": _findtext_any(root, "BIND_TYPE") or "",
        "bind_version": _findtext_any(root, "BIND_TYPE_VERSION") or "",
        "service_name": _findtext_any(root, "SERVICE_NAME") or "",
        # <SERVICE_NAME> is the OData service ALIAS (what the URL is built from).
        # <SRVD_REF><NAME> is the SERVICE DEFINITION -- the next hop when resolving a
        # binding's object closure. They coincide often enough to look identical in a
        # small sample and differ in a substantial minority; following the alias makes
        # the closure resolve to nothing, silently, for exactly those.
        "srvd_name": _srvd_ref_name(root),
        "published": _findtext_any(root, "PUBLISHED") or "",
        "release_state": _findtext_any(root, "RELEASE_STATE") or "",
    }


def extract_srvd(path: Path) -> Optional[dict]:
    """RAP service definition -- which CDS entities a binding exposes."""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        txt = ""
    return {
        "srvd_name": path.name.split(".")[0].split(" ")[0].upper(),
        "exposes": ",".join(sorted(set(re.findall(r"expose\s+([A-Za-z0-9_/]+)", txt)))),
    }


def extract_ddlx(path: Path) -> Optional[dict]:
    """CDS metadata extension -- UI annotations layered onto a view.

    Behaviour-free but presentation-defining: it decides which fields a Fiori app
    shows. Worth indexing because a view's doc is incomplete without knowing one exists.
    """
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        txt = ""
    m = re.search(r"annotate\s+(?:view|entity)\s+([A-Za-z0-9_/]+)", txt)
    return {
        "ddlx_name": path.name.split(".")[0].split(" ")[0].upper(),
        "annotates": (m.group(1).upper() if m else ""),
    }


def extract_suso(path: Path) -> Optional[dict]:
    """CUSTOM AUTHORIZATION OBJECT.

    The estate's own authorization vocabulary. Without this family, a reviewer cannot
    tell whether "no AUTHORITY-CHECK" means no control exists or means the check simply
    was not written -- and cannot tell which custom objects a role designer has to work
    with. Pairs with *.sush.xml (which objects guard what) and *.susc.xml (the classes).
    """
    root = _parse(path)
    if root is None:
        return None
    fields = [(_findtext_any(el, "FIEL%d" % i) or "") for el in [root] for i in range(1, 11)]
    return {
        "auth_object": _findtext_any(root, "OBJCT") or "",
        "auth_class": _findtext_any(root, "OCLSS") or "",
        "ttext": _findtext_any(root, "TTEXT") or "",
        "fields": ",".join([f for f in fields if f]),
    }


def extract_susc(path: Path) -> Optional[dict]:
    """Authorization object CLASS -- the grouping the objects above belong to."""
    root = _parse(path)
    if root is None:
        return None
    return {
        "auth_class": _findtext_any(root, "OCLSS") or "",
        "ttext": _findtext_any(root, "CTEXT", "TTEXT") or "",
    }


def extract_cmod(path: Path) -> Optional[dict]:
    """Classic customer enhancement PROJECT (CMOD).

    A THIRD enhancement family beyond *.enho.xml and *.sxci.xml. A CMOD project
    activates SMOD enhancements (customer exits); an inventory that indexes only ENHO
    and SXCI reports zero coverage for code that is live.
    """
    root = _parse(path)
    if root is None:
        return None
    return {
        "cmod_name": _findtext_any(root, "NAME", "MODNAME") or "",
        "descript": _findtext_any(root, "MODTEXT", "TEXT") or "",
        "status": _findtext_any(root, "STATUS") or "",
    }


def extract_enhc(path: Path) -> Optional[dict]:
    """Enhancement COMPOSITE (ENHC).

    A FOURTH enhancement family, beyond *.enho.xml, *.sxci.xml and *.cmod.xml. A
    composite is a transportable object that groups several enhancement implementations
    under one name and one short text -- it is where the *intent* of a cluster is
    recorded, and frequently the only place the members are listed together.

    Two reasons it must be indexed:

    1. Coverage. The members appear in enho.tsv, but the composite that names them does
       not appear anywhere, so the object that states what the cluster is for is
       invisible to the inventory and to the gap count.
    2. Grouping. Members of one composite are one subject and normally belong in one
       document. Without the composite you discover the grouping only by noticing that
       several implementations share a short text -- or you do not notice it at all and
       write N unrelated documents.

    The child list is the composite's whole point, so it is flattened into a single
    comma-separated column rather than dropped.
    """
    root = _parse(path)
    if root is None:
        return None
    children = [e.text.strip() for e in root.iter()
                if e.tag.endswith("ENHNAME") and e.text and e.text.strip()]
    return {
        "enhc_name": path.name.split(".")[0].upper(),
        "descript": _findtext_any(root, "SHORTTEXT", "TEXT", "DESCRIPT") or "",
        "child_count": str(len(children)),
        "children": ",".join(children),
    }


def extract_wdcc(path: Path) -> Optional[dict]:
    """Web Dynpro component configuration.

    Hash-named on disk. In modern systems these carry FIORI LAUNCHPAD page and tile
    configuration -- i.e. which transactions and apps users can actually launch, and
    under which catalog. That makes them the reachability answer for many objects whose
    own metadata says nothing about who can start them.
    """
    root = _parse(path)
    if root is None:
        return None
    return {
        "config_id": _findtext_any(root, "CONFIG_ID") or "",
        "config_type": _findtext_any(root, "CONFIG_TYPE") or "",
        "wda_component": _findtext_any(root, "WDA_COMPONENT") or "",
        "descript": _findtext_any(root, "DESCRIPTION", "DESCR") or "",
    }


def extract_ttyp(path: Path) -> Optional[dict]:
    """Table type -- minor DDIC, index-only per rule 9. Indexed so it is not a blind spot."""
    root = _parse(path)
    if root is None:
        return None
    return {
        "ttyp_name": _findtext_any(root, "TYPENAME") or path.name.split(".")[0].upper(),
        "rowtype": _findtext_any(root, "ROWTYPE") or "",
        "ddtext": _findtext_any(root, "DDTEXT") or "",
    }


def extract_sush(path: Path) -> Optional[dict]:
    """SU22/SU24 authorization defaults.

    These objects answer "which authorization object guards this externally-callable
    object" -- the question section 7 of the template exists for -- and they are the
    easiest family in a repo to miss, because the FILENAME IS AN OPAQUE HASH that
    contains no trace of what the object guards. The friendly identity lives only in
    <DISPLAY_NAME>, formatted "R3TR <TYPE> <NAME>" (IWSV = OData service, IWSG =
    service group, G4BA = gateway business application) -- or, for RFC-enabled
    function modules, a bare module name with the type carried in <TYPE> as "RF".

    Fields that matter downstream:
      okflag  'X' on a USOBX row  -> the check IS performed at runtime
      pr_text 'No'                -> SU24 proposes NO default values, so role
                                     maintenance is handed an empty proposal. The
                                     check is enforced but nobody is told how to
                                     populate it, which is the usual route to a
                                     blanket grant. Worth flagging on its own.
    """
    root = _parse(path)
    if root is None:
        return None
    display = _findtext_any(root, "DISPLAY_NAME") or ""
    parts = display.split()
    if len(parts) >= 3 and parts[0].upper() == "R3TR":
        guarded_type, guarded_name = parts[1], parts[2]
    else:
        guarded_type = _findtext_any(root, "TYPE") or ""
        guarded_name = parts[0] if parts else ""
    objects, okflags, proposals = [], [], []
    for item in _findall_any(root, "item"):
        obj = _findtext_any(item, "OBJECT") or ""
        if not obj:
            continue
        objects.append(obj)
        okflags.append(_findtext_any(item, "OKFLAG") or "")
        proposals.append(_findtext_any(item, "PR_TEXT") or "")
    if not objects:
        for usobx in _findall_any(root, "USOBX"):
            obj = _findtext_any(usobx, "OBJECT") or ""
            if obj:
                objects.append(obj)
                okflags.append(_findtext_any(usobx, "OKFLAG") or "")
                proposals.append("")
    return {
        "sush_hash": _findtext_any(root, "NAME") or "",
        "display_name": display,
        "guarded_type": guarded_type,
        "guarded_name": guarded_name,
        "auth_objects": ",".join(sorted(set(objects))),
        "okflag": ",".join(okflags),
        "proposal": ",".join(proposals),
    }


def extract_iwsv(path: Path) -> Optional[dict]:
    root = _parse(path)
    if root is None:
        return None
    return {
        "tech_service_name": _findtext_any(root, "TECH_SERVICE_NAME", "SERVICE_NAME") or "",
        "external_name": _findtext_any(root, "EXTERNAL_NAME") or "",
        "version": _findtext_any(root, "TECH_SERVICE_VERSION", "SERVICE_VERSION") or "",
    }


def extract_iwsg(path: Path) -> Optional[dict]:
    root = _parse(path)
    if root is None:
        return None
    return {
        "bep_service_name": _findtext_any(root, "BEP_SVC_SERVICE_NAME") or "",
        "bep_technical_name": _findtext_any(root, "BEP_SVC_TECHNICAL_NAME") or "",
        "service_version": _findtext_any(root, "SERVICE_VERSION") or "",
    }


def extract_iwmo(path: Path) -> Optional[dict]:
    root = _parse(path)
    if root is None:
        return None
    return {
        "model_name": _findtext_any(root, "MODEL_NAME", "TECH_MODEL_NAME") or "",
        "external_name": _findtext_any(root, "EXTERNAL_NAME") or "",
        "version": _findtext_any(root, "MODEL_VERSION") or "",
    }


def extract_iwom(path: Path) -> Optional[dict]:
    root = _parse(path)
    if root is None:
        return None
    return {
        "model_identifier": _findtext_any(root, "MODEL_IDENTIFIER") or "",
        "external_name": _findtext_any(root, "EXTERNAL_NAME") or "",
        "sap_system": _findtext_any(root, "SAP_SYSTEM") or "",
    }


def extract_iwvb(path: Path) -> Optional[dict]:
    root = _parse(path)
    if root is None:
        return None
    return {
        "anno_tech_name": _findtext_any(root, "ANNO_TECH_NAME") or "",
        "serv_tech_name": _findtext_any(root, "SERV_TECH_NAME") or "",
    }


def extract_enho(path: Path) -> Optional[dict]:
    root = _parse(path)
    if root is None:
        return None
    return {
        "enh_name": _findtext_any(root, "ENHNAME", "ENH_NAME") or path.stem.split(".")[0].upper(),
        "enh_type": _findtext_any(root, "ENHTYPE", "ENH_TYPE") or "",
        "badi_def": _findtext_any(root, "BADI_DEF") or "",
        "spot_name": _findtext_any(root, "SPOT_NAME", "ENHSPOT_NAME") or "",
        "hook_target": _findtext_any(root, "TGTNAME", "HOOK_TARGET") or "",
        "impl_class": _findtext_any(root, "IMPL_CLASS", "CLASS_NAME") or "",
        # Migrated classic BAdI: names the SXCI implementation this ENHO
        # supersedes. THE TWO NAMES OFTEN DIFFER -- e.g. ENHO
        # ZXX_ORDER_UPDATE_CHECK carries MIG_BADI_IMPL = ZXX_ORDER_RELEASE.
        # Deduplicating the enho/sxci union on name alone therefore misses
        # most of the twins; dedupe on this column.
        "mig_badi_impl": _findtext_any(root, "MIG_BADI_IMPL") or "",
    }


def extract_sxci(path: Path) -> Optional[dict]:
    """Classic BAdI implementation (SXCI).

    A migrated classic BAdI is serialized TWICE: once here and once as an
    *.enho.xml carrying the same implementation name. validate.py unions the
    two families by name, so the duplicate collapses automatically and the
    total is the count of distinct implementations, not the sum of the files.

    SXCI-only rows -- real code with no ENHO twin -- are the reason this
    extractor exists: without it their docs are reported as orphans forever.
    """
    root = _parse(path)
    if root is None:
        return None
    return {
        "sxci_name": _findtext_any(root, "IMP_NAME") or path.stem.split(".")[0].upper(),
        "exit_name": _findtext_any(root, "EXIT_NAME") or "",
        "impl_class": _findtext_any(root, "IMP_CLASS") or "",
        "inter_name": _findtext_any(root, "INTER_NAME") or "",
        "descript": _findtext_any(root, "TEXT") or "",
    }


def extract_clas(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    clsname = _findtext_any(root, "CLSNAME") or path_xml.stem.split(".")[0].upper()
    superclass = _findtext_any(root, "REFCLSNAME") or ""
    descript = _findtext_any(root, "DESCRIPT") or ""
    # Heuristic: DPC / MPC BASE classes (auto-generated by Gateway).
    #
    # Match ONLY the base classes. A regex like r"_(DPC|MPC)(_EXT)?$" also
    # matches the _EXT classes, and validate.py uses this flag to put them OUT
    # OF SCOPE as generated. But *_DPC_EXT / *_MPC_EXT are the hand-written
    # extension classes: they are exactly where all custom Gateway logic lives
    # -- often thousands of lines carrying real defects. Flagged as generated,
    # such a class can never be reported as a coverage gap, and the doc written
    # for it is reported as an orphan.
    is_dpc_mpc = bool(re.search(r"_(DPC|MPC)$", clsname))
    return {
        "clsname": clsname,
        "superclass": superclass,
        "descript": descript,
        "is_dpc_mpc": "X" if is_dpc_mpc else "",
    }


def extract_intf(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "intf_name": _findtext_any(root, "CLSNAME") or path_xml.stem.split(".")[0].upper(),
        "descript": _findtext_any(root, "DESCRIPT") or "",
    }


def extract_fugr(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "fugr_name": _findtext_any(root, "AREA") or path_xml.stem.split(".")[0].upper(),
        "descript": _findtext_any(root, "AREAT", "DESCRIPT") or "",
    }


_RFC_RE = re.compile(r"^\s*\*?#?.*REMOTE-ENABLED", re.IGNORECASE | re.MULTILINE)


def extract_fugr_fm(fm_abap: Path) -> Optional[dict]:
    """Detect RFC-enabled FMs by scanning the FM's .abap file head."""
    try:
        head = fm_abap.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return None
    # `<grp>.fugr.<member>.abap` -> stem is `<grp>.fugr.<member>`, so the member
    # is the LAST dot-component. split(".", 1) takes the *first* split and
    # leaves every row prefixed "FUGR.", which makes this column useless for
    # any lookup by function-module name.
    fm_name = fm_abap.stem.rsplit(".", 1)[-1] if "." in fm_abap.stem else fm_abap.stem
    return {
        "fm_name": fm_name.upper(),
        "is_rfc": "X" if _RFC_RE.search(head) else "",
    }


def classify_fugr_member(fugr_name: str, member: str) -> str:
    """Is this *.fugr.<member>.abap a function module, or an include?

    abapGit serializes a function group's INCLUDES into the same
    `<grp>.fugr.<member>.abap` filename shape as its function modules, so a
    naive row count over fugr_fm.tsv over-states the number of function
    modules -- a group can easily show half again as many rows as it has
    function modules.

    Four kinds. The authority for "is this a function module" is the group's
    own <FUNCNAME> list in <grp>.fugr.xml; this classification is designed to
    reproduce it exactly (check it against <FUNCNAME> on a new repo):
      FUNC          a hand-written function module
      FUNC_GEN      a GENERATED table/view-maintenance function module
                    -- TABLEPROC_/TABLEFRAME_/VIEWPROC_/VIEWFRAME_. All four
                    prefixes appear in <FUNCNAME>, so all four are function
                    modules despite "FRAME" sounding like an include.
      INCL_GEN      the group's own generated shell -- SAPL<GRP>, L<GRP>TOP,
                    L<GRP>U01, L<GRP>F01 ...
      INCL_FOREIGN  an include that belongs to a DIFFERENT (usually SAP
                    standard) function group, pulled in by an INCLUDE
                    statement and serialized here as though it were ours
                    (e.g. SAP's LCOKO* includes inside a custom PP group,
                    byte-identical to SAP's own). These inflate any "lines
                    of custom code" figure.
    """
    g = (fugr_name or "").upper()
    m = (member or "").upper()
    if m == "SAPL" + g or (g and m.startswith("L" + g)):
        return "INCL_GEN"
    if m.startswith(("TABLEFRAME_", "TABLEPROC_", "VIEWFRAME_", "VIEWPROC_")):
        return "FUNC_GEN"
    if m.startswith("SAPL") or (m.startswith("L") and not m.startswith(("Z", "Y"))):
        return "INCL_FOREIGN"
    return "FUNC"


def extract_prog(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    progname = _findtext_any(root, "NAME", "PROGNAME") or path_xml.stem.split(".")[0].upper()
    return {
        "progname": progname,
        "descript": _findtext_any(root, "DESCRIPT", "TEXT") or "",
        "subc": _findtext_any(root, "SUBC") or "",  # 1=executable, I=include, M=module-pool, S=subroutine-pool
    }


def extract_ddls(path: Path) -> Optional[dict]:
    """Pull view name + label from .asddls (annotation-driven, not XML)."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return None
    name = ""
    # `DEFINE VIEW ENTITY <name>` is the modern syntax. Without `entity` in the
    # optional group the regex captures the KEYWORD as the view name, so every
    # view-entity source lands in the index as "ENTITY" and is unfindable by
    # name. Also handle `EXTEND VIEW [ENTITY] <name>`,
    # which is an enhancement of an SAP view rather than a view of its own.
    m = re.search(
        r"(?:define|extend)\s+(?:root\s+)?(?:abstract\s+)?"
        r"(?:view|hierarchy)\s+(?:entity\s+)?(\w+)",
        head, re.IGNORECASE)
    if m and m.group(1).upper() != "ENTITY":
        name = m.group(1).upper()
    else:
        name = path.stem.split(".")[0].upper()
    label = ""
    m = re.search(r"@EndUserText\.label\s*:\s*'([^']+)'", head)
    if m:
        label = m.group(1)
    return {"view_name": name, "label": label}


def extract_tabl(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "tabname": _findtext_any(root, "TABNAME") or path_xml.stem.split(".")[0].upper(),
        "ddtext": _findtext_any(root, "DDTEXT") or "",
        "tabclass": _findtext_any(root, "TABCLASS") or "",  # TRANSP/POOL/CLUSTER
    }


def extract_doma(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "domname": _findtext_any(root, "DOMNAME") or path_xml.stem.split(".")[0].upper(),
        "ddtext": _findtext_any(root, "DDTEXT") or "",
    }


def extract_dtel(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "rollname": _findtext_any(root, "ROLLNAME") or path_xml.stem.split(".")[0].upper(),
        "ddtext": _findtext_any(root, "DDTEXT") or "",
    }


def extract_msag(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "arbgb": _findtext_any(root, "ARBGB") or path_xml.stem.split(".")[0].upper(),
        "stext": _findtext_any(root, "STEXT", "DDTEXT") or "",
    }


def extract_shlp(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "shlpname": _findtext_any(root, "SHLPNAME") or path_xml.stem.split(".")[0].upper(),
        "ddtext": _findtext_any(root, "DDTEXT") or "",
    }


def extract_tobj(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "object": _findtext_any(root, "OBJECT") or path_xml.stem.split(".")[0].upper(),
        "ttext": _findtext_any(root, "TTEXT", "STEXT") or "",
    }


def extract_tran(path_xml: Path) -> Optional[dict]:
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "tcode": _findtext_any(root, "TCODE") or path_xml.stem.split(".")[0].upper(),
        "ttext": _findtext_any(root, "TTEXT") or "",
        "pgmna": _findtext_any(root, "PGMNA", "PROGRAM") or "",
        "dypno": _findtext_any(root, "DYPNO") or "",
    }


def extract_sfpf(path_xml: Path) -> Optional[dict]:
    """Adobe Form (layout). The INTERFACE field is the driver-to-layout contract."""
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "form_name": path_xml.stem.split(".")[0].upper(),
        "interface": _findtext_any(root, "INTERFACE") or "",
        "text": _findtext_any(root, "TEXT") or "",
    }


def extract_sfpi(path_xml: Path) -> Optional[dict]:
    """Adobe Form interface -- the contract shared by every form that binds it."""
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "interface_name": path_xml.stem.split(".")[0].upper(),
        "text": _findtext_any(root, "TEXT") or "",
    }


def extract_ssfo(path_xml: Path) -> Optional[dict]:
    """Smart Form."""
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "form_name": _findtext_any(root, "FORMNAME") or path_xml.stem.split(".")[0].upper(),
        "interface": _findtext_any(root, "INTERFACE") or "",
        "caption": _findtext_any(root, "CAPTION") or "",
    }


def extract_form(path_xml: Path) -> Optional[dict]:
    """SAPscript form."""
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "form_name": _findtext_any(root, "TDFORM") or path_xml.stem.split(".")[0].upper(),
        "orig_lang": _findtext_any(root, "TDOSPRAS") or "",
        "text": _findtext_any(root, "TDTEXT") or "",
    }


def extract_pdts(path_xml: Path) -> Optional[dict]:
    """Workflow task (TS*). CLSNAM/CLSMET name the ABAP the task actually runs --
    that is the drill target, and it is invisible from the filename, which is
    the bare task number."""
    root = _parse(path_xml)
    if root is None:
        return None
    otype = _findtext_any(root, "OTYPE") or "TS"
    objid = _findtext_any(root, "OBJID") or path_xml.stem.split(".")[0]
    return {
        "task_id": f"{otype}{objid}",
        "short_text": _findtext_any(root, "SHORT_TEXT") or "",
        "impl_class": _findtext_any(root, "CLSNAM") or "",
        "impl_method": _findtext_any(root, "CLSMET") or "",
        "meth_type": _findtext_any(root, "METHTYPE") or "",
        "background": _findtext_any(root, "BACKGROUND") or "",
        "rel_status": _findtext_any(root, "TSKRELSTAT") or "",
    }


_DCL_GRANT_RE = re.compile(r"\bgrant\s+select\s+on\s+([A-Za-z0-9_/]+)", re.IGNORECASE)


def extract_dcls(path_xml: Path) -> Optional[dict]:
    """CDS access control (DCL).

    Two traps this extractor exists to remove:
      1. The source extension is `.dcls.asdcls`, NOT `.dcls.asddls` -- two
         transposed letters from the CDS *view* extension `.ddls.asddls`.
         Searching for the view extension returns a false zero, and that has
         already produced published "no DCL exists anywhere" claims that were
         wrong.
      2. The XML carries only the name and label. The fact that matters --
         which view the role actually grants on -- lives in the .asdcls source,
         so read the sibling file for it.
    """
    root = _parse(path_xml)
    if root is None:
        return None
    src = path_xml.parent / (path_xml.name[: -len(".dcls.xml")] + ".dcls.asdcls")
    grants = ""
    if src.exists():
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            grants = ";".join(sorted({m.group(1).upper() for m in _DCL_GRANT_RE.finditer(text)}))
        except OSError:
            grants = ""
    return {
        "dcl_name": _findtext_any(root, "DCLNAME") or path_xml.stem.split(".")[0].upper(),
        "grants_on": grants,
        "ddtext": _findtext_any(root, "DDTEXT") or "",
    }


def extract_sobj(path_xml: Path) -> Optional[dict]:
    """BOR object type -- a HOST family (it has its own program and behaviour).

    The file repeats OBJTYPE once per element, so take the first. `TOJTB-PARENT`
    is the decisive field: set = a SUBTYPE that inherits its supertype's
    implementation (and can be a delegation target); empty on a Z type = a
    stand-alone type, often a full COPY of an SAP type whose program is then
    frozen SAP code. `SWOTDV-VERBTYPE` counts the elements: M method,
    A attribute, E event, K key field.
    """
    root = _parse(path_xml)
    if root is None:
        return None
    ifaces = sorted({(el.text or "").strip() for el in root.iter()
                     if _strip_ns(el.tag).upper() == "INTERFACE" and (el.text or "").strip()})
    kinds = {"M": 0, "A": 0, "E": 0, "K": 0}
    for el in root.iter():
        if _strip_ns(el.tag).upper() == "VERBTYPE":
            k = (el.text or "").strip().upper()
            if k in kinds:
                kinds[k] += 1
    parent = ""
    for el in root.iter():
        if _strip_ns(el.tag).upper() == "TOJTB":
            for ch in el:
                if _strip_ns(ch.tag).upper() == "PARENT" and (ch.text or "").strip():
                    parent = ch.text.strip()
    return {
        "obj_type": _findtext_any(root, "OBJTYPE", "NAME") or path_xml.stem.split(".")[0].upper(),
        "program": _findtext_any(root, "PROGNAME") or "",
        "parent": parent,
        "kind": ("subtype of " + parent) if parent else "stand-alone (no supertype)",
        "methods": str(kinds["M"]),
        "attributes": str(kinds["A"]),
        "events": str(kinds["E"]),
        "text": _findtext_any(root, "NTEXT", "STEXT") or "",
        "interfaces": ";".join(ifaces),
        "interface_count": str(len(ifaces)),
    }


def extract_smtg(path_xml: Path) -> Optional[dict]:
    """E-mail template (S/4HANA "Maintain Email Templates") -- a HOST family.

    The template ID lives in <HEADER><ID> and may contain SPACES and HYPHENS
    (`ZZ1_PO APPROVAL`); the filename keeps only the part before the first
    space, so never key a template by its filename. <CDS_VIEW> is the data
    source the placeholders are read from; <PARENT_ID> is the SAP template it
    was copied from -- the process it belongs to.
    """
    root = _parse(path_xml)
    if root is None:
        return None
    return {
        "template_id": _findtext_any(root, "ID") or path_xml.name.split(".")[0].upper(),
        "cds_view": _findtext_any(root, "CDS_VIEW") or "",
        "parent_id": _findtext_any(root, "PARENT_ID", "ORIGINAL_ID") or "",
        "name": _findtext_any(root, "NAME") or "",
    }


def extract_aqqu(path_xml: Path) -> Optional[dict]:
    """SAP Query (SQ01) -- a HOST family, serialized by abapGit (AQQU).

    Filename form is `<user group><spaces><query>.aqqu.xml`; inside,
    AQGQCAT-NUM = user group, -QNUM = query, -CLAS = InfoSet (`*.aqsg.xml`,
    the data source, a satellite). The title is the AQGTQ text with HEAD = X.
    A transaction whose PARAM reads `REPORTTYPE=AQ` launches one of these.
    """
    root = _parse(path_xml)
    if root is None:
        return None
    title = ""
    for el in root.iter():
        if _strip_ns(el.tag).upper() == "AQGTQ":
            f = {_strip_ns(c.tag).upper(): (c.text or "").strip() for c in el}
            if f.get("HEAD") == "X" and f.get("TEXT"):
                title = f["TEXT"]
                break
    parts = path_xml.name[:-len(".aqqu.xml")].split()
    return {
        "query": _findtext_any(root, "QNUM") or (parts[-1].upper() if parts else ""),
        "user_group": _findtext_any(root, "NUM") or (parts[0].upper() if parts else ""),
        "infoset": _findtext_any(root, "CLAS") or "",
        "title": title,
    }


def extract_wapa(path_xml: Path) -> Optional[dict]:
    """BSP application -- a HOST family; today almost always a deployed UI5 /
    Fiori app (`APPLCLAS = /UI5/CL_UI5_BSP_APPLICATION`).

    Every page is a sibling file `<app>.wapa.<page>`; the one that matters is
    `<app>.wapa.manifest.json`, whose `sap.app.id` is the app id and whose
    `dataSources[*].uri` names the OData service(s) the app calls -- the link
    from the front end to its back-end host. Reachability is the launchpad
    (`*.wdcc.xml` target mappings), not this file.
    """
    root = _parse(path_xml)
    if root is None:
        return None
    pages = [(_strip_ns(el.tag), (el.text or "").strip()) for el in root.iter()
             if _strip_ns(el.tag).upper() == "PAGEKEY"]
    app = _findtext_any(root, "APPLNAME") or path_xml.name.split(".")[0].upper()
    app_id, services = "", []
    man = path_xml.with_name(path_xml.name.split(".")[0] + ".wapa.manifest.json")
    if man.exists():
        try:
            import json
            j = json.loads(man.read_text(encoding="utf-8-sig", errors="replace"))
            app_id = ((j.get("sap.app") or {}).get("id") or "")
            for ds in ((j.get("sap.app") or {}).get("dataSources") or {}).values():
                uri = (ds or {}).get("uri") or ""
                if uri and (ds or {}).get("type", "OData") == "OData":
                    services.append(uri)
        except (OSError, ValueError, AttributeError):
            pass
    return {
        "app_name": app,
        "app_class": _findtext_any(root, "APPLCLAS") or "",
        "text": _findtext_any(root, "TEXT") or "",
        "page_count": str(len(pages)),
        "app_id": app_id,
        "odata_services": ";".join(sorted(set(services))),
    }


# ---------------------------------------------------------------------------
# Family configuration


# (glob, extractor, output_filename, columns)
FAMILIES = [
    ("*.sicf.xml", extract_sicf, "sicf.tsv",
     ["package", "icf_name", "icf_altnme", "handler", "handlers", "handler_count",
      "icf_docu", "file"]),
    ("*.iwsv.xml", extract_iwsv, "iwsv.tsv",
     ["package", "tech_service_name", "external_name", "version", "file"]),
    ("*.iwsg.xml", extract_iwsg, "iwsg.tsv",
     ["package", "bep_service_name", "bep_technical_name", "service_version", "file"]),
    ("*.iwmo.xml", extract_iwmo, "iwmo.tsv",
     ["package", "model_name", "external_name", "version", "file"]),
    ("*.iwom.xml", extract_iwom, "iwom.tsv",
     ["package", "model_identifier", "external_name", "sap_system", "file"]),
    ("*.iwvb.xml", extract_iwvb, "iwvb.tsv",
     ["package", "anno_tech_name", "serv_tech_name", "file"]),
    ("*.enho.xml", extract_enho, "enho.tsv",
     ["package", "enh_name", "enh_type", "badi_def", "spot_name", "hook_target", "impl_class", "mig_badi_impl", "file"]),
    ("*.enhc.xml", extract_enhc, "enhc.tsv",
     ["package", "enhc_name", "descript", "child_count", "children", "file"]),
    ("*.sxci.xml", extract_sxci, "sxci.tsv",
     ["package", "sxci_name", "exit_name", "impl_class", "inter_name", "descript", "file"]),
    ("*.clas.xml", extract_clas, "clas.tsv",
     ["package", "clsname", "superclass", "is_dpc_mpc", "descript", "file"]),
    ("*.intf.xml", extract_intf, "intf.tsv",
     ["package", "intf_name", "descript", "file"]),
    ("*.fugr.xml", extract_fugr, "fugr.tsv",
     ["package", "fugr_name", "descript", "file"]),
    ("*.prog.xml", extract_prog, "prog.tsv",
     ["package", "progname", "subc", "descript", "file"]),
    ("*.ddls.asddls", extract_ddls, "ddls.tsv",
     ["package", "view_name", "label", "file"]),
    ("*.tabl.xml", extract_tabl, "tabl.tsv",
     ["package", "tabname", "tabclass", "ddtext", "file"]),
    ("*.doma.xml", extract_doma, "doma.tsv",
     ["package", "domname", "ddtext", "file"]),
    ("*.dtel.xml", extract_dtel, "dtel.tsv",
     ["package", "rollname", "ddtext", "file"]),
    ("*.msag.xml", extract_msag, "msag.tsv",
     ["package", "arbgb", "stext", "file"]),
    ("*.shlp.xml", extract_shlp, "shlp.tsv",
     ["package", "shlpname", "ddtext", "file"]),
    ("*.tobj.xml", extract_tobj, "tobj.tsv",
     ["package", "object", "ttext", "file"]),
    ("*.tran.xml", extract_tran, "tran.tsv",
     ["package", "tcode", "pgmna", "dypno", "ttext", "file"]),
    # --- print / output families -------------------------------------------
    ("*.sfpf.xml", extract_sfpf, "sfpf.tsv",
     ["package", "form_name", "interface", "text", "file"]),
    ("*.sfpi.xml", extract_sfpi, "sfpi.tsv",
     ["package", "interface_name", "text", "file"]),
    ("*.ssfo.xml", extract_ssfo, "ssfo.tsv",
     ["package", "form_name", "interface", "caption", "file"]),
    ("*.form.xml", extract_form, "form.tsv",
     ["package", "form_name", "orig_lang", "text", "file"]),
    # --- workflow ----------------------------------------------------------
    ("*.pdts.xml", extract_pdts, "pdts.tsv",
     ["package", "task_id", "short_text", "impl_class", "impl_method",
      "meth_type", "background", "rel_status", "file"]),
    ("*.sobj.xml", extract_sobj, "sobj.tsv",
     ["package", "obj_type", "program", "kind", "methods", "attributes", "events",
      "interface_count", "interfaces", "text", "file"]),
    # --- host families without ABAP files of their own --------------------------
    ("*.smtg.xml", extract_smtg, "smtg.tsv",
     ["package", "template_id", "name", "cds_view", "parent_id", "file"]),
    ("*.aqqu.xml", extract_aqqu, "aqqu.tsv",
     ["package", "query", "user_group", "infoset", "title", "file"]),
    ("*.wapa.xml", extract_wapa, "wapa.tsv",
     ["package", "app_name", "app_id", "app_class", "text", "page_count", "odata_services", "file"]),
    # --- CDS authorization -------------------------------------------------
    ("*.dcls.xml", extract_dcls, "dcls.tsv",
     ["package", "dcl_name", "grants_on", "ddtext", "file"]),
    # Authorization defaults. Hash-named on disk -- see extract_sush.
    ("*.sush.xml", extract_sush, "sush.tsv",
     ["package", "sush_hash", "display_name", "guarded_type", "guarded_name",
      "auth_objects", "okflag", "proposal", "file"]),
    # --- RAP: a transactional OData surface that no SEGW artefact mentions ---
    ("*.bdef.asbdef", extract_bdef, "bdef.tsv",
     ["package", "bdef_name", "for_entity", "impl_class", "kind", "operations", "strict", "file"]),
    ("*.srvb.xml", extract_srvb, "srvb.tsv",
     ["package", "srvb_name", "descript", "bind_type", "bind_version", "service_name",
      "srvd_name", "published", "release_state", "file"]),
    ("*.srvd.srvdsrv", extract_srvd, "srvd.tsv",
     ["package", "srvd_name", "exposes", "file"]),
    ("*.ddlx.asddlxs", extract_ddlx, "ddlx.tsv",
     ["package", "ddlx_name", "annotates", "file"]),
    # --- the estate's own authorization vocabulary ---
    ("*.suso.xml", extract_suso, "suso.tsv",
     ["package", "auth_object", "auth_class", "ttext", "fields", "file"]),
    ("*.susc.xml", extract_susc, "susc.tsv",
     ["package", "auth_class", "ttext", "file"]),
    # --- a third enhancement family, beyond ENHO and SXCI ---
    ("*.cmod.xml", extract_cmod, "cmod.tsv",
     ["package", "cmod_name", "descript", "status", "file"]),
    # --- launchpad / tile configuration: who can actually start things ---
    ("*.wdcc.xml", extract_wdcc, "wdcc.tsv",
     ["package", "config_id", "config_type", "wda_component", "descript", "file"]),
    # --- minor DDIC, index-only per rule 9, indexed so it is not a blind spot ---
    ("*.ttyp.xml", extract_ttyp, "ttyp.tsv",
     ["package", "ttyp_name", "rowtype", "ddtext", "file"]),
]


# ---------------------------------------------------------------------------
# Repo walk


def find_packages(repo_root: Path) -> list[Path]:
    """A package is any directory containing a `src/package.devc.xml` (abapGit convention)."""
    pkgs = []
    for devc in repo_root.glob("*/src/package.devc.xml"):
        pkgs.append(devc.parent.parent)
    return sorted(pkgs)


def collect_fugr_fms(repo_root: Path, output_dir: Path) -> int:
    """FUGR FMs live one level deeper: `<package>/src/<fugr>/<fugr>.fugr.<fm>.abap`."""
    rows = []
    for pkg in find_packages(repo_root):
        for fm_abap in pkg.glob("src/**/*.fugr.*.abap"):
            rec = extract_fugr_fm(fm_abap)
            if rec is None:
                continue
            # parent dir under src/ is the FUGR folder
            try:
                rel = fm_abap.relative_to(repo_root)
            except ValueError:
                rel = fm_abap
            fugr_name = ""
            m = re.match(r"([^.]+)\.fugr\.([^.]+)\.abap", fm_abap.name, re.IGNORECASE)
            if m:
                fugr_name = m.group(1).upper()
            rows.append({
                "package": pkg.name,
                "fugr_name": fugr_name,
                "fm_name": rec["fm_name"],
                "kind": classify_fugr_member(fugr_name, rec["fm_name"]),
                "is_rfc": rec["is_rfc"],
                "file": str(rel).replace("\\", "/"),
            })
    out = output_dir / "fugr_fm.tsv"
    cols = ["package", "fugr_name", "fm_name", "kind", "is_rfc", "file"]
    _write_tsv(out, cols, rows)
    return len(rows)


def collect_includes(repo_root: Path, output_dir: Path) -> int:
    """Include programs — .prog.xml with SUBC='I'."""
    rows = []
    for pkg in find_packages(repo_root):
        for prog_xml in pkg.glob("src/**/*.prog.xml"):
            root = _parse(prog_xml)
            if root is None:
                continue
            subc = _findtext_any(root, "SUBC") or ""
            if subc != "I":
                continue
            try:
                rel = prog_xml.relative_to(repo_root)
            except ValueError:
                rel = prog_xml
            rows.append({
                "package": pkg.name,
                "include_name": _findtext_any(root, "NAME", "PROGNAME") or prog_xml.stem.split(".")[0].upper(),
                "descript": _findtext_any(root, "DESCRIPT", "TEXT") or "",
                "file": str(rel).replace("\\", "/"),
            })
    out = output_dir / "incl.tsv"
    cols = ["package", "include_name", "descript", "file"]
    _write_tsv(out, cols, rows)
    return len(rows)


def _write_tsv(out_path: Path, columns: list[str], rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in sorted(rows, key=lambda x: tuple(str(x.get(c, "")) for c in columns)):
            w.writerow({c: r.get(c, "") for c in columns})


def collect_family(repo_root: Path, output_dir: Path, glob: str, extractor, out_name: str, columns: list[str]) -> int:
    rows = []
    for pkg in find_packages(repo_root):
        for path in pkg.glob(f"src/**/{glob}"):
            # Skip the FUGR FM .abap files when matching *.prog.xml etc. — they have multi-dot stems.
            rec = extractor(path)
            if rec is None:
                continue
            try:
                rel = path.relative_to(repo_root)
            except ValueError:
                rel = path
            rec["package"] = pkg.name
            rec["file"] = str(rel).replace("\\", "/")
            rows.append(rec)
    _write_tsv(output_dir / out_name, columns, rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Main


def main() -> int:
    ap = argparse.ArgumentParser(description="abapGit inventory extractor for ABAP-Documentation skill.")
    ap.add_argument("--repo-root", default=".", help="Repo root containing <package>/src/ folders.")
    ap.add_argument("--output", default="docs/_index/raw", help="Output directory for TSVs (relative to repo-root).")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    output_dir = (repo_root / args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pkgs = find_packages(repo_root)
    if not pkgs:
        print(f"ERROR: no abapGit packages found under {repo_root} (expected <pkg>/src/package.devc.xml).", file=sys.stderr)
        return 2
    print(f"Found {len(pkgs)} packages: {', '.join(p.name for p in pkgs)}")

    summary_rows = []

    for glob, extractor, out_name, cols in FAMILIES:
        n = collect_family(repo_root, output_dir, glob, extractor, out_name, cols)
        print(f"  {out_name}: {n} rows")
        summary_rows.append({"family": out_name.replace(".tsv", ""), "count": n})

    n_fm = collect_fugr_fms(repo_root, output_dir)
    print(f"  fugr_fm.tsv: {n_fm} rows")
    summary_rows.append({"family": "fugr_fm", "count": n_fm})

    n_inc = collect_includes(repo_root, output_dir)
    print(f"  incl.tsv: {n_inc} rows")
    summary_rows.append({"family": "incl", "count": n_inc})

    _write_tsv(output_dir / "summary.tsv", ["family", "count"], summary_rows)
    print(f"\nDone. Output: {output_dir}")

    # Hidden-alias quick report
    print("\nHidden-alias check (objects whose on-disk name != logical name):")
    _report_hidden(output_dir / "sicf.tsv", "icf_name", "icf_altnme", "SICF")
    _report_hidden(output_dir / "sush.tsv", "sush_hash", "guarded_name", "SUSH")
    _report_hidden(output_dir / "iwom.tsv", "model_identifier", "external_name", "IWOM")
    _report_hidden(output_dir / "iwvb.tsv", "anno_tech_name", "serv_tech_name", "IWVB")
    return 0


def _report_hidden(tsv: Path, disk_col: str, alias_col: str, label: str) -> None:
    if not tsv.exists():
        return
    hidden = []
    with tsv.open(encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            disk = (row.get(disk_col) or "").strip()
            alias = (row.get(alias_col) or "").strip()
            if disk and alias and disk != alias:
                hidden.append((disk, alias, row.get("file", "")))
    if not hidden:
        print(f"  {label}: 0 hidden aliases.")
        return
    print(f"  {label}: {len(hidden)} hidden aliases:")
    for disk, alias, file in hidden[:20]:
        print(f"    {disk:<35} -> {alias}  ({file})")
    if len(hidden) > 20:
        print(f"    ... and {len(hidden) - 20} more.")


if __name__ == "__main__":
    sys.exit(main())
