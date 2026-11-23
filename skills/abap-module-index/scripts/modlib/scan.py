"""
scan.py -- ONE pass over the source tree, producing every signal and every edge.

Why one pass, and why Python rather than grep: the tree is typically on a synced drive
(OneDrive/Dropbox/network share) where repeated walks dominate the runtime, and a
grep-per-pattern sweep re-reads every file once per pattern. Everything downstream
works from the cached TSVs this writes, so re-tuning the rule tables never touches
src/ again.

Two families of signal used to be extracted by two different tools:

  *.abap only          call-graph edges (SUBMIT / INCLUDE / CALL FUNCTION / =>)
  everything else      never read at all

That second gap is the expensive one. In a typical estate .abap is a minority of the
files, so an .abap-only extractor produces ZERO edges for CDS views, SICF nodes, OData
services, SmartForms, enhancements, screen variants and parameter transactions --
hundreds of objects, plus every T-Code without a <PGMNA>, left with no resolvable entry
point. All of those facts live in XML, .asddls and .baseinfo files.

Outputs (all in the work dir)
  object_signals.tsv   one row per (object, type)
  edges_raw.csv        every edge, both origins, before dedupe
  object_files.tsv     object -> the files it is serialised into (for spot-checks)
"""

import collections
import csv
import json
import pathlib
import re
import sys

from . import names as N

# --- XML tag extraction ---------------------------------------------------------------
SINGLE_TAGS = {
    "tran": ["TCODE", "PGMNA", "PARAM", "TTEXT"],
    "prog": ["NAME", "SUBC", "APPL", "DBAPL"],
    "clas": ["CLSNAME", "DESCRIPT"],
    "intf": ["CLSNAME", "DESCRIPT"],
    "fugr": ["AREA", "AREAT"],
    "sxci": ["IMP_NAME", "TEXT", "IMP_CLASS", "EXIT_NAME", "INTER_NAME"],
    "enho": ["ENHNAME", "SPOT_NAME", "TOOL", "PROGRAMNAME", "SHORTTEXT", "TEXT"],
    "cmod": ["NAME", "TEXT"],
    "sicf": ["URL", "ICF_NAME", "ORIG_NAME", "ICF_DOCU", "ICFHANDLER"],
    "iwsg": ["SRV_IDENTIFIER", "MODEL_IDENTIFIER", "TECHNICAL_NAME", "SERVICE_NAME"],
    "iwom": ["MODEL_IDENTIFIER", "CLASS_NAME", "TECHNICAL_NAME"],
    "iwsv": ["SERVICE_NAME", "TECHNICAL_NAME"],
    "scvi": ["PROGNAME", "VARIANT", "TEXT", "DYNPRO"],
    "stvi": ["TCODE", "TCVARIANT", "TEXT", "GUI_PROG"],
    "ddls": ["DDLNAME", "DDTEXT", "SOURCE_TYPE"],
    "ddlx": ["NAME", "DDTEXT"],
    "ssfo": ["FORMNAME", "CAPTION", "TEXT"],
    "form": ["FORMNAME", "TDNAME", "CAPTION", "TDTITLE"],
    "webi": ["NAME", "TEXT", "SHORTTEXT"],
    "wdyn": ["COMPONENT_NAME", "DESCRIPTION"],
    "wdya": ["COMPONENT_NAME", "DESCRIPTION"],
    "msag": ["ARBGB", "STEXT"],
    "tabl": ["TABNAME", "DDTEXT", "TABCLASS"],
    "dtel": ["ROLLNAME", "DDTEXT", "DOMNAME"],
    "doma": ["DOMNAME", "DDTEXT"],
    "ttyp": ["TYPENAME", "DDTEXT", "ROWTYPE"],
    "view": ["VIEWNAME", "DDTEXT", "ROOTTAB"],
    "shlp": ["SHLPNAME", "DDTEXT", "SELMETHOD"],
    "srvd": ["NAME", "DDTEXT"],
    "srvb": ["NAME", "DDTEXT"],
    "sfpf": ["NAME", "TEXT"],
    "sfpi": ["NAME", "TEXT"],
    "tobj": ["OBJECT", "OBJECT_TEXT", "TEXT", "OBJECTNAME", "TABNAME"],
    "iatu": ["TEMPLATE_NAME", "PROGRAM"],
    "sprx": ["OBJECT_NAME", "TEXT"],
    # SAP Query family. The query file name is a padded compound key
    # '<usergroup>   <queryname>', so the real name comes from <QNUM>; <CLAS> names the
    # InfoSet it reads and <NUM> the user group that owns it.
    "aqqu": ["NUM", "QNUM", "CLAS", "TEXT"],
    "aqsg": ["CLAS", "NUM", "TEXT"],
    "aqbg": ["NUM", "TEXT"],
    "dial": ["DNAM", "PROG", "DYNR"],
    "enhc": ["ENHNAME", "SHORTTEXT"],
}
TEXT_TAGS = ("TTEXT", "DDTEXT", "DESCRIPT", "AREAT", "TEXT", "SHORTTEXT", "STEXT",
             "ENTRY", "ICF_DOCU", "CAPTION", "OBJECT_TEXT", "DESCRIPTION")
MULTI_TAGS = {
    "fugr": ["FUNCNAME", "SOBJ_NAME"],
    "cmod": ["MEMBER"],
    # New-style BAdI implementations carry the implementing class in
    # <IMPL><ENH_BADI_IMPL_DATA><IMPL_CLASS> and the precise BAdI in <BADI_NAME>.
    # <SPOT_NAME> alone is the enhancement SPOT, which is much coarser -- four
    # different implementations can share one spot while their BADI_NAMEs distinguish
    # them. One ENHO may hold several implementations, so these are multi-valued.
    "enho": ["SPOT_NAME", "PROGRAMNAME", "CLASS_NAME", "IMPL_CLASS", "BADI_NAME",
             "IMPL_NAME"],
    # A transaction variant records the standard PROGRAM it runs, once per GUI element
    # it changes, and that program is far more informative than the T-Code: 'IH09' says
    # only "filed under Plant Maintenance", while 'RIMARA20' says the report is over
    # MARA -- the material master, which is what the transaction actually displays.
    "stvi": ["GUI_PROG"],
    # A SAPscript form's title is repeated once per installed language, and the
    # <TDSPRAS> keys do not pair 1:1 with the titles (the header carries its own), so
    # they cannot simply be zipped. Collect them all and pick a readable one -- see
    # pick_readable_text. Without this a form reports NO short text at all, and SAP's
    # own sample forms then land in "nothing here": one of them turned out to be
    # 'Certificate of Origin EU' in twenty-one languages, another named its own print
    # program 'RFDUZI00' in the title.
    "form": ["TDTITLE"],
    "ssfo": ["TDTITLE", "CAPTION"],
    # An InfoSet lists the standard tables its queries read -- the only place in a
    # query's serialisation where the business meaning is stated at all.
    "aqsg": ["TAB"],
    "enhc": ["ENHNAME"],
    # DDIC composition. A structure/table lists one <ROLLNAME> per field and one
    # <CHECKTABLE> per foreign key; an .INCLUDE carries the included structure in
    # <PRECFIELD>. These are the only edges a DDIC object has -- it contains no code --
    # so without them every data element, domain and table type in the estate has zero
    # inbound references and lands in Unattached under "attributed via its consumer"
    # when in fact no consumer was ever recorded.
    "tabl": ["ROLLNAME", "PRECFIELD", "CHECKTABLE", "FIELDNAME"],
    "auth": ["ROLLNAME", "FIELDNAME"],
    "view": ["TABNAME", "CHECKTABLE"],
    "ttyp": ["ROWTYPE"],
    "tobj": ["TABNAME"],
}

COMMENT_LINE = re.compile(r"^\s*\*")
TRAILING_COMMENT = re.compile(r'".*$')

_TAG_CACHE = {}


def _tag_re(tag):
    # [^<]* -- NOT (.*?) -- so the pattern can never span a nested element.
    #
    # abapGit nests some tables under an element with the same name as its leaf field:
    #
    #     <ICFHANDLER_TABLE>
    #       <ICFHANDLER>                                       <- wrapper
    #         <ICF_NAME>EXTSYS</ICF_NAME>
    #         <ICFHANDLER>ZCL_EXT_REST_HANDLER</ICFHANDLER> <- leaf
    #       </ICFHANDLER>
    #
    # A non-greedy <ICFHANDLER>(.*?)</ICFHANDLER> matches from the wrapper's open tag
    # to the LEAF's close tag and captures an XML blob; findall does not backtrack into
    # a consumed match, so the leaf is then never seen at all. The blob is truthy, so
    # it got emitted as an edge target and as the OData-twin discriminator -- both
    # silently wrong. Excluding '<' from the capture makes the wrapper simply not
    # match, so the leaf does.
    return re.compile(rf"<{tag}>([^<]*)</{tag}>")


def find_all(text, tag):
    rx = _TAG_CACHE.get(tag)
    if rx is None:
        rx = _TAG_CACHE[tag] = _tag_re(tag)
    return [m.strip() for m in rx.findall(text) if m.strip()]


def find_one(text, tag):
    vals = find_all(text, tag)
    return vals[0] if vals else ""


_SPRAS_RX = re.compile(r"<TDSPRAS>([^<]*)</TDSPRAS>")
_TITLE_RX = re.compile(r"<TDTITLE>([^<]*)</TDTITLE>")


def pick_readable_text(xml, lang="E"):
    """The most useful of a form's translations of its own title.

    Prefer the requested language, found BY POSITION: the <TDSPRAS> and <TDTITLE>
    elements cannot be zipped, because the header block carries a <TDSPRAS> of its own
    and the lists come out different lengths -- zipping them returned the Danish title
    for language 'E'.

    Failing that, prefer plain ASCII. The localised copies arrive mojibaked (a GBK or
    Big5 title decoded as latin-1) and are unreadable to a rule and a reviewer alike,
    while any European copy is intact and says the same thing. Among ASCII candidates
    the SHORTEST wins: 'Certificate of Origin EU' over 'Opprinnelsessertifikat EF',
    because a keyword list is far likelier to hold the English words.
    """
    titles = [(m.start(), m.group(1).strip()) for m in _TITLE_RX.finditer(xml)]
    if not titles:
        return ""
    for m in _SPRAS_RX.finditer(xml):
        if m.group(1).strip().upper() != lang.upper():
            continue
        after = [t for pos, t in titles if pos > m.end()]
        if after and after[0]:
            return after[0]
    ascii_ok = [t for _p, t in titles
                if t and t.isascii() and sum(c.isalpha() for c in t) >= 3]
    if ascii_ok:
        return min(ascii_ok, key=len)
    return next((t for _p, t in titles if t), "")


def decode(path):
    """Bytes -> str, tolerating abapGit's BOM and any latin-1 residue.

    A plain open() uses the platform default (cp1252 on Windows) and raises on any
    file containing non-Latin text -- which in a localised estate is hundreds of files.
    """
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def strip_comments(code):
    """Remove ABAP full-line (*) and trailing (") comments.

    A grep-based extractor does neither, so commented-out code produces phantom
    edges -- often a hundred or more phantom STATIC_CALL edges from dead lines.
    """
    out = []
    for line in code.splitlines():
        if COMMENT_LINE.match(line):
            continue
        out.append(TRAILING_COMMENT.sub("", line))
    return "\n".join(out)


# --- code patterns --------------------------------------------------------------------
CALL_TCODE_RX = re.compile(
    r"\b(CALL|LEAVE\s+TO)\s+TRANSACTION\s+'([^']+)'", re.I)
SUBMIT_RX = re.compile(r"^\s*SUBMIT\s+([A-Za-z0-9_/]+)", re.I | re.M)
INCLUDE_RX = re.compile(r"^\s*INCLUDE\s+([A-Za-z0-9_/]+)", re.I | re.M)
PERFORM_EXT_RX = re.compile(
    r"\bPERFORM\s+[A-Za-z0-9_]+\s+IN\s+PROGRAM\s+([A-Za-z0-9_/]+)", re.I)
CALL_FM_RX = re.compile(r"\bCALL\s+FUNCTION\s+'([^']+)'", re.I)
STATIC_CALL_RX = re.compile(r"\b([A-Za-z_][A-Za-z0-9_/]*)\s*=>", re.I)
CREATE_OBJECT_RX = re.compile(
    r"\bCREATE\s+OBJECT\s+[\w<>-]+\s+TYPE\s+([A-Za-z0-9_/]+)", re.I)
# Only custom form names. A bare `FORM = '...'` also matches the ALV callback
# parameters (I_CALLBACK_PF_STATUS_SET etc.), which are subroutine names, not forms.
FORMNAME_RX = re.compile(
    r"\b(?:FORMNAME|TDFORM|FORM)\s*=\s*'([A-Za-z0-9_/]+)'", re.I)

# --- content evidence: what the code CHANGES, not just what it mentions --------------
# Measured against held-out truth (scripts/measure_signals.py reproduces it per estate):
#
#     writing a module's standard tables   most accurate, fires rarely
#     naming conventions                   close behind, fires widely
#     reading  a module's standard tables  clearly weaker
#     calling a module's change BAPIs      clearly weaker
#
# A direct write to a standard SAP table is the most accurate signal in the whole
# ladder: it is an invasive, unusual act, and it is almost always done by the team that
# owns the table. Reading is not -- every module reads every other module's data all
# day. Calling a change API is not either: a production confirmation posts goods
# movements and accounting documents, so the call means "I trigger that process", not
# "I belong to it".
#
# The write patterns match internal tables too (`INSERT lt_items`), which is why the
# result is intersected with the known standard-table set. That intersection IS the
# filter -- without it this rule would fire on every ABAP program ever written.
WRITE_RX = [
    re.compile(r"\b(?:INSERT|MODIFY)\s+(?:INTO\s+)?([A-Za-z0-9_/]+)", re.I),
    re.compile(r"\bUPDATE\s+([A-Za-z0-9_/]+)", re.I),
    re.compile(r"\bDELETE\s+(?:FROM\s+)?([A-Za-z0-9_/]+)", re.I),
]
# Custom tables the code uses, from a TABLES declaration or any DB statement. These
# matter twice over: they make the table reachable (instead of sitting in Unattached as
# unexplained DDIC), and the table's NAME carries the estate's naming convention, so a
# family rule can read it. Four programs titled "Asset Master Data" -- a copy-pasted
# title -- were attributed FI by the weakest rule in the ladder when the only table they
# touch is ZXX_WF_PR_CH1, the price-change workflow table. The custom table name was the
# real signal and nothing was looking at it.
CUSTOM_TABLE_RX = [
    re.compile(r"^\s*TABLES\s*:?\s*([A-Za-z0-9_,\s]+)", re.I | re.M),
    re.compile(r"\bFROM\s+([A-Za-z0-9_]+)", re.I),
    re.compile(r"\b(?:INSERT|MODIFY|UPDATE)\s+(?:INTO\s+)?([A-Za-z0-9_]+)", re.I),
    re.compile(r"\bDELETE\s+FROM\s+([A-Za-z0-9_]+)", re.I),
]

# Outbound RFC: CALL FUNCTION 'X' DESTINATION 'Y'. The DESTINATION addition is the
# only thing that distinguishes a local call from a remote one.
RFC_DEST_RX = re.compile(r"\bCALL\s+FUNCTION\s+'[^']+'\s+DESTINATION", re.I)
MSG_CLASS_RX = re.compile(
    r"\bMESSAGE\s+[eiswaxEISWAX]?\d{3}\s*\(\s*([A-Za-z0-9_/]+)\s*\)", re.I)
AUTH_OBJ_RX = re.compile(r"\bAUTHORITY-CHECK\s+OBJECT\s+'([^']+)'", re.I)
INCLUDE_NOISE = {"TYPE", "STRUCTURE", "BOUND"}
SUBMIT_NOISE = {"AND", "OR", "EXPORTING", "WITH", "VIA", "TO", "VARIANT", "ADDITIONS",
                "LINE", "USING"}

# Object-oriented references. A class used through a reference variable, a superclass,
# or an implemented interface is part of the using object's implementation -- but a
# `ZCL_FOO=>` regex alone never sees it -- a sizeable share of the objects otherwise
# reported "unreferenced" are reachable through exactly these patterns.
OO_PATTERNS = [
    ("INHERITS", r"\bINHERITING\s+FROM\s+({N})"),
    ("TYPE_REF_TO", r"\bTYPE\s+REF\s+TO\s+({N})"),
    ("CREATE_OBJ_TYPE", r"\bCREATE\s+OBJECT\s+[\w<>-]+\s+TYPE\s+({N})"),
    ("NEW_INSTANCE", r"\bNEW\s+({N})\s*\("),
    ("TYPE_OF", r"\bTYPE\s+(?:LINE\s+OF\s+|TABLE\s+OF\s+)?({N})"),
]
INTERFACES_RX = re.compile(r"\bINTERFACES\s*:?\s*([^.]*)", re.I)

# IDoc naming is the most discriminating content signal a retail or integration estate
# has, and the table rules are blind to it: a segment type is a DDIC structure, not a
# table, so `ls_seg TYPE e1kna1m` and `pi_mestyp = 'WBBDLD'` read as nothing at all.
# Both forms appear the same way in every estate -- as a type reference or as a literal
# -- so both are collected here and resolved by name in the ladder (R14).
IDOC_SEG_RX = re.compile(r"\b([ZY]?E[123][A-Z][A-Z0-9_]{2,})\b", re.I)
IDOC_MSG_RX = re.compile(r"(?:MESTYP|IDOCTP|MESSAGE_TYPE|MESTY)\w*\s*"
                         r"(?:=|EQ)\s*'([A-Z][A-Z0-9_]{2,})'", re.I)


class Obj:
    __slots__ = ("name", "otype", "tags", "texts", "tables", "tables_written",
                 "std_calls", "loc", "forms", "msg_classes", "auth_objs", "fm_calls",
                 "literals", "oo_refs", "ext_comm", "ztables", "files", "paths",
                 "idoc_refs", "data_elements", "field_names")

    def __init__(self, name, otype):
        self.name, self.otype = name, otype
        self.tags = {}
        self.texts = []
        self.tables = set()
        self.tables_written = set()
        self.std_calls = set()
        self.forms = set()
        self.msg_classes = set()
        self.auth_objs = set()
        self.fm_calls = set()
        self.literals = set()
        self.oo_refs = set()
        self.ext_comm = set()
        self.ztables = set()
        self.idoc_refs = set()
        self.data_elements = set()
        self.field_names = set()
        self.loc = 0
        self.files = 0
        self.paths = []


def _custom_name_class(prefixes):
    """Regex fragment matching a custom object name, e.g. '[ZY][A-Za-z0-9_]{3,}'."""
    cls = "".join(sorted({p.upper() for p in prefixes} | {p.lower() for p in prefixes}))
    return f"[{cls}][A-Za-z0-9_]{{3,}}"


def run(cfg, verbose=True):
    parse = N.make_parser(cfg.known_types)
    nameclass = _custom_name_class(cfg.custom_prefixes)
    z_literal_rx = re.compile(rf"'({nameclass})'")
    # `TYPE <something>` in ABAP. Captured whole and filtered afterwards rather
    # than built into the pattern, because the knowledge base holds data-element
    # PREFIXES (PAE_, 0FI_) and a prefix baked into an alternation with a trailing
    # word boundary stops being a prefix. Custom names are excluded here -- they go
    # through the estate's own naming rules instead, where they belong.
    de_prefixes = tuple(e for e, _m in cfg.std_data_elements)
    de_rx = re.compile(r"\bTYPE\s+(?:LINE\s+OF\s+|TABLE\s+OF\s+)?([A-Za-z][\w/]{2,})\b")
    z_name_rx = re.compile(rf"\b({nameclass})\b")
    oo_rx = [(kind, re.compile(pat.replace("{N}", nameclass), re.I))
             for kind, pat in OO_PATTERNS]
    table_rx = (re.compile(r"\b(" + "|".join(sorted(cfg.table_to_module, key=len,
                                                    reverse=True)) + r")\b", re.I)
                if cfg.table_to_module else None)

    objs = {}
    edges = []           # (src, src_type, edge_type, tgt, tgt_type, origin, evidence)
    fm_to_fugr = {}
    fugr_includes = {}
    unparsed = collections.Counter()
    seen_files = set()   # basename -> a mirrored sub-package folder must not double-count
    mirrored = 0

    paths = []
    for root in cfg.source_roots:
        if not root.exists():
            print(f"WARNING: source root {root} does not exist", file=sys.stderr)
            continue
        paths.extend(p for p in root.rglob("*") if p.is_file())
    if verbose:
        print(f"scanning {len(paths)} files under "
              f"{', '.join(cfg.rel(r) for r in cfg.source_roots)} ...")

    for path in paths:
        parsed = parse(path.name)
        if parsed is None:
            unparsed[path.suffix.lower()] += 1
            continue
        # package.devc.xml is the package itself, not an object in it. Parsed naively
        # it becomes an object called PACKAGE of type DEVC, once per folder.
        if path.name == "package.devc.xml":
            continue
        # Some estates extract a sub-package export INTO the parent's src/, leaving a
        # byte-identical mirror of files already present. Counting both doubles LOC and
        # file counts. The map is keyed by filename, so mirrors collapse -- but they are
        # counted and reported, because a silent duplicate is how double-counting starts.
        if path.name in seen_files:
            mirrored += 1
            continue
        seen_files.add(path.name)

        otype = parsed.object_type
        key = (parsed.object_name, otype.upper())
        obj = objs.get(key)
        if obj is None:
            obj = objs[key] = Obj(parsed.object_name, otype.upper())
        obj.files += 1
        if len(obj.paths) < 3:
            obj.paths.append(cfg.rel(path))

        # --- ABAP source ---------------------------------------------------------------
        if parsed.ext == "abap":
            code = decode(path)
            obj.loc += sum(1 for ln in code.splitlines() if ln.strip())
            clean = strip_comments(code)
            if table_rx:
                obj.tables.update(t.upper() for t in table_rx.findall(clean))
            for rx in WRITE_RX:
                for t in rx.findall(clean):
                    t = t.upper()
                    if t in cfg.all_std_tables:
                        obj.tables_written.add(t)
            for kw, tc in CALL_TCODE_RX.findall(clean):
                et = "LEAVE_TCODE" if kw.upper().startswith("LEAVE") else "CALL_TCODE"
                obj.std_calls.add(tc.upper())
                edges.append((obj.name, obj.otype, et, tc.upper(), "TRAN", "code",
                              path.name))
            for t in SUBMIT_RX.findall(clean):
                t = t.upper()
                if t in SUBMIT_NOISE:
                    continue
                obj.std_calls.add(t)
                edges.append((obj.name, obj.otype, "SUBMIT", t, "PROG", "code",
                              path.name))
            for t in INCLUDE_RX.findall(clean):
                t = t.upper()
                if t in INCLUDE_NOISE:
                    continue
                obj.std_calls.add(t)
                edges.append((obj.name, obj.otype, "INCLUDE", t, "PROG", "code",
                              path.name))
            for t in PERFORM_EXT_RX.findall(clean):
                edges.append((obj.name, obj.otype, "PERFORM_IN_PROG", t.upper(),
                              "PROG", "code", path.name))
            for fm in CALL_FM_RX.findall(clean):
                fm = fm.upper()
                obj.fm_calls.add(fm)
                obj.std_calls.add(fm)
                if N.is_custom(fm, cfg.custom_prefixes):
                    edges.append((obj.name, obj.otype, "CALL_FM", fm, "FUGR", "code",
                                  path.name))
            for t in STATIC_CALL_RX.findall(clean):
                if N.is_custom(t, cfg.custom_prefixes):
                    edges.append((obj.name, obj.otype, "STATIC_CALL", t.upper(), "",
                                  "code", path.name))
                else:
                    obj.std_calls.add(t.upper())
            for t in CREATE_OBJECT_RX.findall(clean):
                if N.is_custom(t, cfg.custom_prefixes):
                    edges.append((obj.name, obj.otype, "CREATE_OBJECT", t.upper(),
                                  "CLAS", "code", path.name))
            for f in FORMNAME_RX.findall(clean):
                if N.is_custom(f, cfg.custom_prefixes):
                    obj.forms.add(f.upper())
            obj.literals.update(m.upper() for m in z_literal_rx.findall(clean))
            # Data element references in ABAP. `INFNR TYPE INFNR` in a BW extractor
            # that never SELECTs anything is the only statement it makes about its
            # subject, and the DDIC path (R18 off <ROLLNAME>) cannot see it because the
            # object is a class, not a structure. Intersected with the known standard
            # set, exactly like the table patterns, so local type names cost nothing.
            if de_prefixes:
                for m in de_rx.findall(clean):
                    m = m.upper()
                    if m.startswith(de_prefixes) and not N.is_custom(
                            m, cfg.custom_prefixes):
                        obj.data_elements.add(m)
            obj.idoc_refs.update(m.upper() for m in IDOC_SEG_RX.findall(clean))
            obj.idoc_refs.update(m.upper() for m in IDOC_MSG_RX.findall(clean))
            for rx in CUSTOM_TABLE_RX:
                for hit in rx.findall(clean):
                    for tok in re.split(r"[,\s]+", hit):
                        tok = tok.strip().upper()
                        if tok and N.is_custom(tok, cfg.custom_prefixes)                                 and tok != obj.name:
                            obj.ztables.add(tok)
            for kind, rx in oo_rx:
                for m in rx.findall(clean):
                    obj.oo_refs.add((kind, m.upper()))
            for block in INTERFACES_RX.findall(clean):
                for m in z_name_rx.findall(block):
                    obj.oo_refs.add(("IMPLEMENTS", m.upper()))
            upper = clean.upper()
            for marker, label in cfg.external_comm:
                if marker == "CALL FUNCTION_DESTINATION":
                    if RFC_DEST_RX.search(clean):
                        obj.ext_comm.add(label)
                elif marker in upper:
                    obj.ext_comm.add(label)
            obj.msg_classes.update(m.upper() for m in MSG_CLASS_RX.findall(clean))
            obj.auth_objs.update(a.upper() for a in AUTH_OBJ_RX.findall(clean))
            continue

        # --- CDS dependency metadata ---------------------------------------------------
        if parsed.ext == "baseinfo":
            try:
                data = json.loads(decode(path)).get("BASEINFO", {})
            except (json.JSONDecodeError, AttributeError):
                data = {}
            for kind in ("FROM", "ASSOCIATED", "BASE"):
                for tgt in data.get(kind) or []:
                    edges.append((obj.name, "DDLS", f"CDS_{kind}", tgt.upper(), "",
                                  "metadata", path.name))
            continue

        if parsed.ext in ("asddls", "asddlxs"):
            srcx = decode(path)
            obj.loc += sum(1 for ln in srcx.splitlines() if ln.strip())
            if re.search(r"@OData\.publish\s*:\s*true", srcx, re.I):
                obj.tags["ODATA_PUBLISH"] = "X"
            continue

        if parsed.ext != "xml":
            continue

        # --- XML -----------------------------------------------------------------------
        text = decode(path)
        for tag in SINGLE_TAGS.get(otype, []):
            val = find_one(text, tag)
            if val and tag not in obj.tags:
                obj.tags[tag] = val
        for tag in MULTI_TAGS.get(otype, []):
            vals = find_all(text, tag)
            if vals:
                obj.tags.setdefault(tag + "_ALL", "|".join(sorted(set(vals))))
        for tag in TEXT_TAGS:
            obj.texts.extend(find_all(text, tag))
        if otype in ("form", "ssfo"):
            readable = pick_readable_text(text)
            if readable:
                obj.texts.insert(0, readable)

        # Opaque types carry a padded compound key or a hash on disk; the name a
        # consultant would recognise is in the payload.
        if otype in cfg.opaque_types:
            obj.tags.setdefault("REPAIRED_NAME", N.repair_name(parsed, obj.tags))

        if otype == "fugr" and parsed.subtype == "":
            area = (obj.tags.get("AREA") or obj.name).upper()
            # <REMOTE_CALL>R inside each <item> is the ONLY authoritative marker that a
            # function module is RFC-enabled. Grepping the FM body for the literal
            # "REMOTE-ENABLED" finds nothing -- that string is a comment abapGit does
            # not serialise -- so an estate's whole external RFC surface can be reported
            # as zero. A function group exposed over RFC is an external API surface and
            # a first-class governance fact, not a low-priority object family.
            rfc = [v for v in find_all(text, "REMOTE_CALL") if v.strip().upper() == "R"]
            if rfc:
                obj.tags["RFC_FMS"] = str(len(rfc))
            for fm in find_all(text, "FUNCNAME"):
                fm_to_fugr[fm.upper()] = area
            incs = [i.upper() for i in find_all(text, "SOBJ_NAME")]
            if incs:
                fugr_includes[area] = incs

        elif otype == "tran":
            tcode = obj.tags.get("TCODE", obj.name).upper()
            pgm = obj.tags.get("PGMNA", "").upper()
            if pgm:
                edges.append((tcode, "TRAN", "TCODE_PGM", pgm, "PROG", "metadata",
                              path.name))
            param = obj.tags.get("PARAM", "")
            for etype, tgt, ttype in decode_tstcp(param):
                edges.append((tcode, "TRAN", etype, tgt, ttype, "metadata",
                              f"PARAM={param}"))

        elif otype == "sxci":
            imp = (obj.tags.get("IMP_CLASS") or "").upper()
            if imp:
                edges.append((obj.name, "SXCI", "BADI_IMPL_CLASS", imp, "CLAS",
                              "metadata", path.name))
            for tag, et in (("EXIT_NAME", "ENHANCES_BADI"),
                            ("INTER_NAME", "ENHANCES_INTF")):
                v = (obj.tags.get(tag) or "").upper()
                if v:
                    edges.append((obj.name, "SXCI", et, v, "STD", "metadata",
                                  path.name))

        elif otype == "enho":
            for tag, et in (("SPOT_NAME_ALL", "ENHANCES_SPOT"),
                            ("BADI_NAME_ALL", "ENHANCES_BADI"),
                            ("IMPL_CLASS_ALL", "BADI_IMPL_CLASS"),
                            ("PROGRAMNAME_ALL", "ENHANCES_OBJECT"),
                            ("CLASS_NAME_ALL", "ENHANCES_CLASS")):
                # IMPL_CLASS / CLASS_NAME point at a custom class in this repo; the
                # others name standard SAP objects, which cannot be walked into.
                ttype = "CLAS" if et in ("BADI_IMPL_CLASS", "ENHANCES_CLASS") else "STD"
                for v in (obj.tags.get(tag) or "").split("|"):
                    if v:
                        edges.append((obj.name, "ENHO", et, v.upper(), ttype,
                                      "metadata", path.name))
            # Enhancement implementations carry inline ABAP inside the XML, which an
            # .abap-only sweep never reads.
            inline = "\n".join(find_all(text, "SOURCE") + find_all(text, "CODE"))
            if inline and table_rx:
                clean_inline = strip_comments(inline)
                obj.tables.update(t.upper() for t in table_rx.findall(clean_inline))
                for rx in WRITE_RX:
                    for t in rx.findall(clean_inline):
                        if t.upper() in cfg.all_std_tables:
                            obj.tables_written.add(t.upper())
                obj.tags["INLINE_ABAP"] = "X"

        elif otype == "cmod":
            for v in (obj.tags.get("MEMBER_ALL") or "").split("|"):
                if v:
                    edges.append((obj.name, "CMOD", "CMOD_MEMBER", v.upper(), "SMOD",
                                  "metadata", path.name))

        elif otype == "sicf":
            handler = (obj.tags.get("ICFHANDLER") or "").upper()
            obj.tags["REPAIRED_NAME"] = N.repair_name(parsed, obj.tags)
            if handler:
                obj.tags["IS_ODATA_TWIN"] = "X" if handler.startswith("/IWFND/") else ""
                edges.append((obj.name, "SICF", "ICF_HANDLER", handler, "CLAS",
                              "metadata", path.name))

        elif otype == "iwsg":
            model = (obj.tags.get("MODEL_IDENTIFIER") or "").upper()
            if model:
                edges.append((obj.name, "IWSG", "ODATA_MODEL", model, "IWOM",
                              "metadata", path.name))

        elif otype == "iwom":
            cls = (obj.tags.get("CLASS_NAME") or "").upper()
            if cls:
                edges.append((obj.name, "IWOM", "ODATA_CLASS", cls, "CLAS", "metadata",
                              path.name))

        elif otype in ("tabl", "dtel", "doma", "ttyp", "view", "shlp", "tobj",
                       "auth", "sush"):
            # A DDIC object holds no ABAP, so the only facts it can offer are the
            # objects it is composed OF and the standard tables it checks against.
            # Both matter:
            #
            #   composition   table -> data element -> domain, table type -> row type,
            #                 view -> base tables, maintenance object -> table. These
            #                 give the leaf DDIC objects an inbound edge, which is what
            #                 lets a domain inherit the module of the table that uses
            #                 it. Without them hundreds of objects can sit in
            #                 Unattached labelled "attributed via its consumer" while
            #                 having no recorded consumer at all.
            #   check tables  a foreign key onto LFB1 or a view over MARD is content
            #                 evidence about the DDIC object itself, of exactly the kind
            #                 R7/R10 already read from code. It is filtered through the
            #                 same non-discriminating list, so a MANDT/T000 key or a
            #                 MARA lookup contributes nothing.
            for tag, etype, ttype in (("FIELDNAME_ALL", "", ""),
                                      ("ROLLNAME_ALL", "DDIC_FIELD", "DTEL"),
                                      ("PRECFIELD_ALL", "DDIC_INCLUDE", "TABL"),
                                      ("DOMNAME_ALL", "DDIC_DOMAIN", "DOMA"),
                                      ("ROWTYPE_ALL", "DDIC_ROWTYPE", "TABL"),
                                      ("TABNAME_ALL", "DDIC_BASE", "TABL"),
                                      ("CHECKTABLE_ALL", "DDIC_CHECK", "TABL")):
                raw = obj.tags.get(tag) or ""
                if not raw and tag == "DOMNAME_ALL":
                    raw = obj.tags.get("DOMNAME") or ""
                for v in raw.split("|"):
                    v = v.strip().upper()
                    if not v or v == obj.name or v.startswith("."):
                        continue
                    if tag == "FIELDNAME_ALL":
                        # Field NAMES, as opposed to the data elements they are typed
                        # with. A retailer's 'ARTICLE' field typed with MATNR says what
                        # the table is for where MATNR -- which every module uses --
                        # cannot. Read through this estate's own naming rules, never as
                        # a module name in itself.
                        obj.field_names.add(v)
                        continue
                    if etype in ("DDIC_FIELD", "DDIC_ROWTYPE"):
                        # The data elements the fields are typed with -- standard AND
                        # custom. Standard ones name the business object (R18); custom
                        # ones carry this estate's naming convention, the same way
                        # custom table names already do.
                        obj.data_elements.add(v)
                    if N.is_custom(v, cfg.custom_prefixes):
                        edges.append((obj.name, otype.upper(), etype, v, ttype,
                                      "metadata", path.name))
                    elif v in cfg.table_to_module:
                        obj.tables.add(v)
            for tag, etype in (("ROOTTAB", "DDIC_BASE"), ("SELMETHOD", "DDIC_BASE")):
                v = (obj.tags.get(tag) or "").strip().upper()
                if not v or v == obj.name:
                    continue
                if N.is_custom(v, cfg.custom_prefixes):
                    edges.append((obj.name, otype.upper(), etype, v, "TABL",
                                  "metadata", path.name))
                elif v in cfg.table_to_module:
                    obj.tables.add(v)

        elif otype == "scvi":
            pgm = (obj.tags.get("PROGNAME") or "").upper()
            if pgm:
                edges.append((obj.name, "SCVI", "VARIANT_OF_PROG", pgm, "PROG",
                              "metadata", path.name))

        elif otype == "stvi":
            tc = (obj.tags.get("TCODE") or "").upper()
            if tc:
                edges.append((obj.name, "STVI", "VARIANT_OF_TCODE", tc, "TRAN",
                              "metadata", path.name))
            # <GUI_PROG> is the standard program the variant actually runs, and it is
            # the single most informative field in the whole object. A T-Code is a
            # four-character label chosen by whoever filed it in the menu; the program
            # name embeds the table it reports on. 'IH09' resolves only to "somewhere in
            # the Plant Maintenance menu"; its program 'RIMARA20' is a report over MARA,
            # which is what the transaction actually displays. Without this the variant
            # inherits the menu area instead of the data object.
            for pgm in (obj.tags.get("GUI_PROG_ALL") or "").split("|"):
                pgm = pgm.strip().upper()
                if pgm:
                    edges.append((obj.name, "STVI", "VARIANT_OF_PROG", pgm, "PROG",
                                  "metadata", path.name))

        elif otype == "aqqu":
            infoset = (obj.tags.get("CLAS") or "").upper()
            if infoset:
                edges.append((obj.name, "AQQU", "QUERY_INFOSET", infoset, "AQSG",
                              "metadata", path.name))
            group = (obj.tags.get("NUM") or "").upper()
            if group:
                edges.append((obj.name, "AQQU", "QUERY_USERGROUP", group, "AQBG",
                              "metadata", path.name))

        elif otype == "aqsg":
            # The InfoSet's <TAB> entries are standard tables. Feeding them into the
            # object's table set is what lets rule R7 attribute a query at all -- a
            # query has no ABAP source to fingerprint.
            for t in (obj.tags.get("TAB_ALL") or "").split("|"):
                if t:
                    obj.tables.add(t.upper())

        elif otype == "dial":
            pgm = (obj.tags.get("PROG") or "").upper()
            if pgm:
                edges.append((obj.name, "DIAL", "DIAL_PROG", pgm, "PROG", "metadata",
                              path.name))

        elif otype == "enhc":
            for v in (obj.tags.get("ENHNAME_ALL")
                      or obj.tags.get("ENHNAME") or "").split("|"):
                if v:
                    edges.append((obj.name, "ENHC", "ENHC_MEMBER", v.upper(), "ENHO",
                                  "metadata", path.name))

        elif otype == "webi":
            # A WEBI is a Web Service Definition -- a SOAP endpoint published over
            # function modules, NOT a Web Dynpro application and not an ITS service.
            # The published FMs are what the service DOES, so an edge to each one (and
            # via the FM->FUGR alias to its function group) is the only sound way to
            # attribute a web service; attributing it by its own name attributes the
            # wrapper. Mislabelling this family hides a live external API surface --
            # dozens of services, each publishing real function modules.
            for fm in sorted(set(find_all(text, "FUNCTION"))):
                fm = fm.upper()
                if fm and fm != obj.name:
                    edges.append((obj.name, "WEBI", "WS_PUBLISHES_FM", fm, "FUGR",
                                  "metadata", path.name))
                    obj.fm_calls.add(fm)
                    obj.std_calls.add(fm)

        elif otype in ("wdyn", "wdya"):
            for cmp_name in find_all(text, "COMPONENT_NAME"):
                if N.is_custom(cmp_name, cfg.custom_prefixes) \
                        and cmp_name.upper() != obj.name:
                    edges.append((obj.name, otype.upper(), "WDY_USES",
                                  cmp_name.upper(), "WDYN", "metadata", path.name))

    # --- resolve function-module calls to their owning function group -----------------
    # A CALL FUNCTION names an FM, but the OBJECT is the function group. Without this
    # alias every custom FM call is a dangling edge, which is why function groups look
    # unreferenced.
    fm_edges = 0
    for obj in objs.values():
        for fm in obj.fm_calls:
            fugr = fm_to_fugr.get(fm)
            if fugr:
                et = "WS_PUBLISHES_FUGR" if obj.otype == "WEBI" else "CALL_FM_FUGR"
                edges.append((obj.name, obj.otype, et, fugr, "FUGR",
                              "metadata", f"FM={fm}"))
                fm_edges += 1
    for area, incs in fugr_includes.items():
        for inc in incs:
            edges.append((area, "FUGR", "FUGR_INCLUDE", inc, "PROG", "metadata",
                          "fugr.xml <INCLUDES>"))

    # --- resolve names that exist as objects ------------------------------------------
    name_types = collections.defaultdict(set)
    for (name, otype) in objs:
        name_types[name].add(otype)

    def best_type(nm):
        ts = name_types[nm]
        for t in cfg.type_priority:
            if t in ts:
                return t
        return sorted(ts)[0]

    # Forms: printing is driven through standard function calls (WRITE_FORM,
    # SSF_FUNCTION_MODULE_NAME) that carry the form name as a literal parameter, not as
    # a call target -- so forms otherwise have zero inbound edges and vanish.
    form_objects = {name for (name, otype) in objs
                    if otype in ("SSFO", "FORM", "SSST", "SFPF")}
    form_edges = 0
    for (name, otype), obj in objs.items():
        for fname in obj.forms & form_objects:
            edges.append((name, otype, "USES_FORM", fname, best_type(fname),
                          "code", "FORMNAME= literal"))
            form_edges += 1

    # Literal cross-references: 'ZFOO' in code where ZFOO is a real object. This is the
    # highest-yield edge pattern in a typical estate and keyword-anchored regexes miss
    # it entirely, because ABAP routes names through a variable first:
    #     lv_formname = 'ZXX_WM_002_BINLAB'.   " then -> SSF_FUNCTION_MODULE_NAME
    #     CALL FUNCTION lv_fmname.             " assigned earlier as a literal
    # Resolving literals against the objects that actually exist means a literal naming
    # no real object costs nothing.
    lit_edges = 0
    for (name, otype), obj in objs.items():
        for lit in obj.literals:
            if lit == name or lit not in name_types:
                continue
            edges.append((name, otype, "LITERAL_REF", lit, best_type(lit), "code",
                          "custom-name literal in code"))
            lit_edges += 1

    # A screen variant is named '<transaction-variant>_<screen>' -- 'ZVAR12_0500'
    # inside 'ZVAR12'. Its own serialisation names only the framework program it runs
    # in (SAPLSVAR, SAPLSLVC_FULLSCREEN), which is shared by every module and therefore
    # says nothing; the transaction variant it belongs to says everything. Resolved
    # against the variants that actually exist, so a name that merely looks like one
    # costs nothing.
    tcvariants = {name for (name, otype) in objs if otype == "STVI"}
    scvi_edges = 0
    for (name, otype) in list(objs):
        if otype != "SCVI":
            continue
        for tv in tcvariants:
            if name.startswith(tv + "_") and name != tv:
                edges.append((name, "SCVI", "VARIANT_IN_TCVARIANT", tv, "STVI",
                              "metadata", "name prefix"))
                scvi_edges += 1
                break

    # A SAP Query is executed through a GENERATED report whose name packs the work
    # area, the user group and the query into fixed-width fields padded with '=':
    #
    #     AQ ZZ ZFOO_GROUP== ZFOO_QUERY====
    #     ^^ ^^ ^^^^^^^^^^^^ ^^^^^^^^^^^^^^
    #     |  |  user group   query name
    #     |  work area (ZZ = global/customer)
    #     literal
    #
    # A T-Code entering one of those looks like an unresolvable standard program, so
    # the query -- which IS in the repository, with its InfoSet and its tables -- never
    # gets connected to the transaction that runs it. Rewriting the edge to the query
    # object costs nothing when the name does not parse.
    # 'SAPLZIDOC' is the module pool of custom function group ZIDOC, and
    # 'SAPMZ_PRICECHANGE_STEP1_ZSPR' a custom module pool -- but both start with 'S',
    # so a custom-namespace test on the raw name says "standard SAP object" and they
    # end up on the research worklist as names nobody can look up. The wrapper prefix
    # is not part of the object.
    sapl_edges = 0
    for i, e in enumerate(edges):
        tgt = (e[3] or "").upper()
        for lead in ("SAPL", "SAPM", "SAPF"):
            if not tgt.startswith(lead) or len(tgt) <= len(lead):
                continue
            inner = tgt[len(lead):]
            if inner in name_types and N.is_custom(inner, cfg.custom_prefixes):
                edges[i] = (e[0], e[1], e[2], inner, best_type(inner), e[5],
                            f"{e[6]} (via {tgt})")
                sapl_edges += 1
            break

    aq_edges = 0
    for i, e in enumerate(edges):
        tgt = (e[3] or "").upper()
        if not tgt.startswith("AQ") or len(tgt) < 17 or "=" not in tgt[4:]:
            continue
        group = tgt[4:16].rstrip("=").strip()
        query = tgt[16:].rstrip("=").strip()
        if not group or not query:
            continue
        # The object name comes from the FILE name, where the two fields are padded to
        # fixed width -- so a 12-character user group leaves no gap and the collapsed
        # name has no space in it. Both forms have to be tried or every query owned by
        # a full-width group stays unresolved.
        real = next((c for c in (f"{group} {query}", f"{group}{query}")
                     if c in name_types), "")
        if real:
            edges[i] = (e[0], e[1], "RUNS_QUERY", real, "AQQU", "metadata",
                        f"generated query report {tgt}")
            aq_edges += 1
        elif group in name_types:
            # The query name in the generated program does not always round-trip to
            # the object name -- the two are padded differently and a query may carry
            # a namespace the report name drops. The USER GROUP always resolves, and a
            # group is a real object whose members are its queries, so inheriting from
            # it is sound where guessing the query would not be.
            edges[i] = (e[0], e[1], "QUERY_USERGROUP", group, "AQBG", "metadata",
                        f"user group of generated query report {tgt}")
            aq_edges += 1

    ztab_edges = 0
    for (name, otype), obj in objs.items():
        for tab in obj.ztables:
            if tab in name_types and (name_types[tab] & {"TABL", "VIEW", "TTYP"}):
                edges.append((name, otype, "USES_TABLE", tab, "TABL", "code",
                              "custom table"))
                ztab_edges += 1

    oo_edges = collections.Counter()
    for (name, otype), obj in objs.items():
        for kind, tgt in obj.oo_refs:
            if tgt == name or tgt not in name_types:
                continue
            edges.append((name, otype, kind, tgt, best_type(tgt), "code",
                          "OO reference"))
            oo_edges[kind] += 1

    # --- write -------------------------------------------------------------------------
    sec = cfg.secondary_script
    sig_path = cfg.work("object_signals.tsv")
    cols = ["object_name", "object_type", "files", "loc", "text_primary",
            "text_secondary", "subc", "appl", "pgmna", "param", "imp_class",
            "exit_name", "spot_name", "enho_tool", "icf_handler", "icf_url",
            "repaired_name", "odata_model", "odata_publish", "progname", "rfc_fms",
            "external_comm", "custom_tables", "idoc_refs", "data_elements",
            "field_names", "text_all",
            "std_tables",
            "std_tables_written", "std_calls", "forms", "msg_classes", "auth_objects"]
    with sig_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for (name, otype), o in sorted(objs.items()):
            if sec:
                primary = next((t for t in o.texts if not sec.search(t)), "")
                secondary = next((t for t in o.texts if sec.search(t)), "")
            else:
                primary = o.texts[0] if o.texts else ""
                secondary = ""
            w.writerow([
                name, otype, o.files, o.loc,
                primary.replace("\t", " ")[:200], secondary.replace("\t", " ")[:200],
                o.tags.get("SUBC", ""), o.tags.get("APPL", ""),
                o.tags.get("PGMNA", ""), o.tags.get("PARAM", ""),
                o.tags.get("IMP_CLASS", ""), o.tags.get("EXIT_NAME", ""),
                o.tags.get("SPOT_NAME_ALL", o.tags.get("SPOT_NAME", "")),
                o.tags.get("TOOL", ""), o.tags.get("ICFHANDLER", ""),
                o.tags.get("URL", ""), o.tags.get("REPAIRED_NAME", ""),
                o.tags.get("MODEL_IDENTIFIER", ""), o.tags.get("ODATA_PUBLISH", ""),
                o.tags.get("PROGNAME", ""), o.tags.get("RFC_FMS", ""),
                "; ".join(sorted(o.ext_comm)), "|".join(sorted(o.ztables)),
                "|".join(sorted(o.idoc_refs)),
                "|".join(sorted(o.data_elements)),
                "|".join(sorted(o.field_names)),
                # Every DISTINCT short text, not only the first. An object often
                # carries several and the first is the least useful: a SAP Query
                # InfoSet is named after itself and describes its data sources in the
                # field-group texts ("Conditions (Header)", "Change document header"),
                # which were extracted and then thrown away. Read only by R8, the
                # last-resort rule, so a long text cannot outweigh a real signal.
                " | ".join(dict.fromkeys(
                    t.replace("\t", " ").strip() for t in o.texts
                    if t.strip()))[:400],
                "|".join(sorted(o.tables)), "|".join(sorted(o.tables_written)),
                "|".join(sorted(o.std_calls)),
                "|".join(sorted(o.forms)), "|".join(sorted(o.msg_classes)),
                "|".join(sorted(o.auth_objs)),
            ])

    edge_path = cfg.work("edges_raw.csv")
    with edge_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["source_object", "source_type", "edge_type", "target_object",
                    "target_type", "origin", "evidence"])
        w.writerows(edges)

    files_path = cfg.work("object_files.tsv")
    with files_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["object_name", "object_type", "files", "example_paths"])
        for (name, otype), o in sorted(objs.items()):
            w.writerow([name, otype, o.files, " | ".join(o.paths)])

    stats = {
        "files_seen": len(paths),
        "files_mirrored": mirrored,
        "files_unparsed": sum(unparsed.values()),
        "unparsed_by_ext": dict(unparsed.most_common(10)),
        "objects": len(objs),
        "distinct_names": len(name_types),
        "edges_raw": len(edges),
        "fm_to_fugr_pairs": len(fm_to_fugr),
        "fm_edges": fm_edges,
        "form_edges": form_edges,
        "literal_edges": lit_edges,
        "objects_writing_std_tables": sum(1 for o in objs.values() if o.tables_written),
        "oo_edges": dict(oo_edges),
    }
    if verbose:
        print(f"\nobjects:        {len(objs)} ({len(name_types)} distinct names)")
        print(f"files parsed:   {len(paths) - stats['files_unparsed'] - mirrored}"
              f"  (unparsed {stats['files_unparsed']}, mirrored {mirrored})")
        print(f"raw edges:      {len(edges)}")
        print(f"  FM -> FUGR aliases:      {fm_edges} "
              f"(from {len(fm_to_fugr)} FUNCNAME pairs)")
        print(f"  form invocations:        {form_edges}")
        print(f"  literal cross-refs:      {lit_edges}")
        print(f"  custom-table references: {ztab_edges}")
        rfc = [o for o in objs.values() if o.tags.get("RFC_FMS")]
        if rfc:
            print(f"  RFC-enabled function groups:   {len(rfc)} "
                  f"({sum(int(o.tags['RFC_FMS']) for o in rfc)} remote-enabled FMs) "
                  "-- the estate's external API surface")
        ec = collections.Counter()
        for o in objs.values():
            for lab in o.ext_comm:
                ec[lab] += 1
        if ec:
            print("  outbound communication: "
                  + ", ".join(f"{lab} ({n})" for lab, n in ec.most_common()))
        wr = sum(1 for o in objs.values() if o.tables_written)
        print(f"  objects WRITING standard tables: {wr}  "
              "(the most accurate attribution signal there is -- and a governance "
              "finding in its own right)")
        print(f"  OO references:           {sum(oo_edges.values())}  -> "
              + ", ".join(f"{k}:{v}" for k, v in oo_edges.most_common()))
        by_type = collections.Counter(e[2] for e in edges)
        for et, n in by_type.most_common(16):
            print(f"  {et:<20} {n:>6}")
        print(f"\nwrote {cfg.rel(sig_path)}")
        print(f"wrote {cfg.rel(edge_path)}")
        print(f"wrote {cfg.rel(files_path)}")
    return stats


# --- T-Code parameter decoding --------------------------------------------------------
# `\s*` around the '=' is not cosmetic. SAP accepts whitespace in the parameter string
# and estates use it: '/*SM30 VIEWNAME= ZFOO_ADDR;UPDATE=X;' -- one space -- left the
# T-Code with no members at all, so the table it maintains was never linked and the row
# had no evidence of any kind. Its sibling, written without the space, resolved fine.
_SM30 = re.compile(r"VIEWNAME\s*=\s*([A-Za-z0-9_/]+)", re.I)
_VCL = re.compile(r"VCLDIR-VCLNAME\s*=\s*([A-Za-z0-9_/]+)", re.I)
_REPORT = re.compile(r"D_SREPOVARI-REPORT(?:TYPE)?\s*=\s*([A-Za-z0-9_/]+)", re.I)


def decode_tstcp(param):
    """<TSTCP><PARAM> -> [(edge_type, target, target_type)].

    A parameter transaction has no <PGMNA> at all -- its target is encoded in this
    string. Three forms cover the lot, and they resolve the many T-Codes that otherwise
    appear to have no entry point:

      /*SM30 VIEWNAME=X;      parameter transaction into table maintenance
      /NFBZ1 BKPF-BLART=CA;   skip-first-screen call of another T-Code
      @@FB50 ZFB50            variant transaction
    """
    if not param:
        return []
    p = param.strip()
    out = []
    if p.startswith("@@"):
        rest = p[2:].split()
        if rest:
            out.append(("PARAM_VARIANT_OF", rest[0].upper(), "TRAN"))
            if len(rest) > 1:
                out.append(("PARAM_VARIANT", rest[1].upper(), "STVI"))
        return out
    if p[:2] in ("/*", "/N", "/n") or p[:2].upper() == "/N":
        body = p[2:]
        tcode = re.split(r"[\s;]", body, maxsplit=1)[0].upper()
        if tcode:
            out.append(("PARAM_CALLS_TCODE", tcode, "TRAN"))
        for rx, et, tt in ((_SM30, "PARAM_MAINTAINS", "TABL"),
                           (_VCL, "PARAM_MAINTAINS", "VCLS"),
                           (_REPORT, "PARAM_REPORT", "PROG")):
            m = rx.search(body)
            if m:
                out.append((et, m.group(1).upper(), tt))
    return out
