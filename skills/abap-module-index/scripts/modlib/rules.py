"""
rules.py -- the attribution rule ladder, and the accumulator that keeps it honest.

A tick means "this module HAS A STAKE in this unit", NOT "this module owns it". Rules
are additive: a class that splits a billing document is legitimately both SD and FI,
and both teams need to see it.

The ladder, strongest first:

  R1  home package            AUTHORITATIVE  a decision a human made in SAP
  R2  resolved entry program  AUTHORITATIVE  the program behind the T-Code, never the
                                             T-Code name (module tokens live in the
                                             program name far more often)
  R3  enhancement anchor      AUTHORITATIVE  the STANDARD object being enhanced
  R4  classic exit include    AUTHORITATIVE  ZX<fgrp>U01 self-classifies
  R10 content: table writes   AUTHORITATIVE  what the code CHANGES. Measured most
                                             accurate of all; fires rarely
  R5  name tokens             STRONG         this estate's naming convention
  R6  special families        STRONG         site-specific families (RF handhelds,
                                             eInvoicing, CDS, ...)
  R9  standard-name wrapper   AUTH/STRONG    a custom name wrapping a standard
                                             transaction; AUTHORITATIVE when the
                                             standard name came from a resolved entry
  R7  closure fingerprint     INFERRED       discriminating standard tables READ, and
                                             standard calls (clearly weaker -- reading
                                             or calling another module is normal)
  R8  tie-breakers            WEAK           TRDIR application area, description
                                             keywords -- only when nothing else fired

Confidence is the authority of the best signal that fired, per unit.

OPEN VOCABULARY: any rule may name a module that has no tick column in this config.
That hit is not discarded -- it lands in the proposal register with its evidence, and
the discovery report asks a human to adopt or rule it out. Silence is never the
default answer to "we found something you did not tell us about".
"""

import re


AUTHORITATIVE, STRONG, INFERRED, WEAK = "AUTHORITATIVE", "STRONG", "INFERRED", "WEAK"
_RANK = {AUTHORITATIVE: 3, STRONG: 2, INFERRED: 1, WEAK: 0}
CONFIDENCE = {AUTHORITATIVE: "HIGH", STRONG: "MEDIUM", INFERRED: "LOW", WEAK: "LOW"}


# --- R5: name tokens ------------------------------------------------------------------
def name_tokens(cfg, object_name, object_type=""):
    """Module hits from an object name, honouring this estate's segment rules.

    The convention is read off the CONFIGURED segment positions, because estates
    differ:

      ZXX_GRP_SD_006_RVADOR01  ->  segment 3 is the module (GRP is a shared layer)
      ZXX_WM_034_PH_INV       ->  segment 2 is the module
      ZMM_PRICE_UPDATE        ->  the bare-prefix form: the module is glued to the Z
      ZXX_NG_EXEMPTVAT        ->  NG is a legal entity, blacklisted -> no hit

    The blacklist is what makes this rule safe. Two-letter tokens that look like
    modules are very often entity codes, plant codes or architectural layers, and an
    unfiltered token match smears those across the whole estate.
    """
    import re as _re
    from . import names as N
    clean = N.strip_namespace(object_name)
    # Split on whitespace as well as underscore: abapGit pads compound keys, so a SAP
    # Query arrives as 'ZMM         ZMMBARCODE' and an ICF node as 'EXTSYS  <hash>'.
    # Splitting on '_' alone makes the whole padded string one segment and the rule
    # silently never fires for those object types.
    segs = [s for s in _re.split(r"[_\s]+", clean) if s]
    if not segs or not segs[0].startswith(tuple(p.upper()
                                                for p in cfg.custom_prefixes)):
        return []
    blacklist = cfg.segment_blacklist | cfg.type_segment_blacklist.get(
        (object_type or "").upper(), set())

    def bare_prefix():
        head = segs[0]
        if len(head) > 1 and head[1:] in cfg.token_map:
            return [(cfg.token_map[head[1:]], f"name:{head}_*")]
        return []

    hits = []
    for idx in cfg.module_segments:
        if idx >= len(segs):
            break
        seg = segs[idx]
        if seg in blacklist:
            continue
        if idx == cfg.module_segments[0]:
            bp = bare_prefix()
            if bp:
                return bp
        if seg in cfg.token_map:
            hits.append((cfg.token_map[seg],
                         f"name:{'_'.join(segs[:idx + 1])}_*"))
            break
    return hits or bare_prefix()


# --- R6: special families -------------------------------------------------------------
def family_hits(cfg, object_name):
    out = []
    for rx, mods, label in cfg.families:
        if rx.search(object_name or ""):
            out.extend((m, f"family:{label}") for m in mods)
    return out


# --- R9: standard-object name wrapper -------------------------------------------------
def wrapper_hits(cfg, name):
    """Module from a custom name that WRAPS a standard SAP transaction/program name.

    ZVA01_ZXX    -> VA01   -> SD     (screen variant of the sales order)
    ZME21N_ZXX_01-> ME21N  -> MM     (purchase order variant per site)
    ZF_07XX      -> F-07   -> FI     (parameterised posting transaction)
    YXX_F110CHECK -> F110  -> FI     (payment-run form)

    This is the rule that attributes transaction/screen variants and parameterised
    T-Codes. Without it they are the single largest unclassifiable population in an
    estate that customises standard transactions rather than writing new ones -- most
    variants, and a large share of parameterised T-Codes, have no other signal at all.

    The custom prefix is stripped first and the patterns are anchored, because an
    unanchored 'ME' or 'CO' would match half of any estate.
    """
    import re as _re
    from . import names as N
    n = N.strip_namespace(name)
    for pfx in sorted(cfg.custom_prefixes, key=len, reverse=True):
        if n.startswith(pfx.upper()):
            n = n[len(pfx):]
            break
    n = n.lstrip("_ ")
    if not n:
        return []
    # The standard code sits at the start of the stripped name (ZVA01_ZXX), or in a
    # later segment when a team prefix comes first (YXX_F110CHECK -> F110CHECK).
    # Patterns stay anchored per candidate, and every one of them requires a digit or a
    # distinctive letter run, so a segment like COST or MERCH cannot match.
    # Generic framework programs carry no module: SM30 maintains a table and the
    # module belongs to the TABLE, SAPLSVAR is the variant dialog, SAPLSLVC_FULLSCREEN
    # the ALV grid. Checked before the patterns, so a later family pattern cannot claim
    # one of them by accident.
    full = N.strip_namespace(name).upper()
    if full.startswith(cfg.std_name_ignore) or n.startswith(cfg.std_name_ignore):
        return []
    candidates = [n] + [s for s in _re.split(r"[_\s-]+", n)[1:] if s]
    for cand in candidates:
        for rx, mods in cfg.std_name_wrappers:
            if rx.search(cand):
                return [(m, f"std-wrapper:{name}->{cand}") for m in mods]
    return []


# --- R3: enhancement anchors ----------------------------------------------------------
def std_anchor_hits(cfg, anchor):
    """Module of the STANDARD object a custom enhancement hangs off.

    R3 resolves an anchor against the BAdI-spot table, which covers the spots worth
    naming and nothing else. A HOOK_IMPL on a standard program is just as
    authoritative and is not a spot at all: 'ZPOPULATE_ERRO_STATUS' enhances SAPLWPUE,
    the POS interface function group, and that is the only thing about it that carries
    any meaning -- its own name and short text say 'populate error'.

    The SAPL/SAPM prefixes are stripped because they are the module-pool wrapper, not
    the function group: SAPLWPUE is function group WPUE.
    """
    a = (anchor or "").upper()
    for lead in ("SAPL", "SAPM", "SAPF", "RM", "RV", "RI"):
        if a.startswith(lead) and len(a) > len(lead) + 1:
            a = a[len(lead):]
            break
    if not a:
        return []
    mod, ev = std_object_module(cfg, a)
    if not mod:
        mod = std_call_module(cfg, a)
        ev = f"std-object:{a}"
    if mod:
        return [(mod, f"enhances:{anchor} ({ev})")]
    return []


def badi_hits(cfg, anchor):
    """Module hits from a BAdI spot / classic exit / enhanced-object name."""
    if not anchor:
        return []
    a = anchor.upper()
    for key, mods in cfg.badi_spots.items():
        if a.startswith(key) or key in a:
            return [(m, f"spot:{anchor}") for m in mods]
    return []


# --- R4: classic SMOD exit includes ---------------------------------------------------
def exit_include_hits(cfg, name):
    n = (name or "").upper()
    for pfx, mods in cfg.exit_include_prefixes:
        if n.startswith(pfx):
            return [(m, f"exit-include:{name}") for m in mods]
    return []


# --- R10: content evidence -- what the code CHANGES -----------------------------------
def write_hits(cfg, tables_written):
    """Modules whose standard tables this object WRITES.

    The most accurate signal in the ladder, measured against held-out truth: ahead of
    naming conventions, and well ahead of table reads and calls to a module's change
    BAPIs. scripts/measure_signals.py measures all four on your own estate.

    The asymmetry is the point. Every module reads every other module's data, and a
    process that posts through another module's API (a production confirmation posting
    a goods movement) is a consumer of it. But writing straight into a standard SAP
    table is invasive and rare, and it is almost always done by the team that owns the
    table. Where it fires it is close to definitive; it simply does not fire often --
    typically well under one percent of an estate's objects.

    Two consequences, and the second is worth as much as the first:
      * it can attribute a unit no naming rule reaches, at HIGH confidence
      * it is a governance finding on its own -- code bypassing SAP's own APIs
    """
    hits = []
    seen = set()
    for t in sorted(tables_written):
        mod = cfg.table_to_module.get(t)
        if mod and mod not in seen:
            seen.add(mod)
            hits.append((mod, f"writes:{t}"))
    return hits


# --- R7: standard-object fingerprint --------------------------------------------------
def std_call_module(cfg, name):
    n = (name or "").upper()
    if not n or n.startswith(cfg.std_call_ignore):
        return None
    for pfx, mod in cfg.std_call_prefixes:
        if n.startswith(pfx):
            return mod
    return None


# --- R12: SAP's own infotype naming ---------------------------------------------------
def infotype_hits(cfg, name, text=""):
    """HR infotype tables/structures, which SAP names for you.

    An infotype numbered 9xxx is a customer infotype, and SAP generates a fixed family
    of DDIC objects for it: P9000 (the record), PA9000 (the transparent table), PS9000
    (the field structure), P9000_AF (query fields), plus a screen structure. None of
    those names contains a module token, none of them is referenced from custom code
    (the HR framework dispatches them from T777D), and so a whole custom infotype -- ten
    or more objects -- lands unattributed while being unambiguously HR.

    The number is what makes this safe: only the HR framework uses a four-digit suffix
    this way, and only 9000-9999 is the customer range.
    """
    it = cfg.infotype_naming
    if not it:
        return []
    n = (name or "").upper()
    # A module pool is named MP<infotype><screen> and nothing else in ABAP is. The
    # customer-range guard below exists to stop 'P1234' matching an arbitrary name; it
    # does not apply here, because MP200000 is infotype 2000 (Absences) and is just as
    # certainly HR as MP900010 is.
    for pfx in it.get("module_pool_prefixes", []):
        if n.startswith(pfx) and re.fullmatch(r"\d{6}", n[len(pfx):] or ""):
            return [(it["module"], f"infotype-pool:{n[len(pfx):][:4]}")]
    for pfx in it.get("prefixes", []):
        rest = n[len(pfx):] if n.startswith(pfx) else None
        if rest is None:
            continue
        # 'P9000', 'PA9000', 'PS9000_AF' -- and 'MP900010', where the module
        # pool name is infotype 9000 plus screen 10.
        m = re.match(r"^(\d{4})(?:\d{2}|_[A-Z0-9]+)?$", rest)
        if m and it.get("customer_range", [9000, 9999])[0] <= int(m.group(1))                 <= it.get("customer_range", [9000, 9999])[1]:
            return [(it["module"], f"infotype:{m.group(1)}")]
    if "INFOTYPE" in (text or "").upper() or "INFO TYPE" in (text or "").upper():
        return [(it["module"], "text:Infotype")]
    return []


# --- R13: append / extension of a standard object -------------------------------------
_APPEND_NAME = (
    re.compile(r"^CI_([A-Z0-9]{2,})$"),        # SAP's own customer-include convention
    re.compile(r"^ZZ([A-Z0-9]{3,})$"),         # ZZ<base> append structure
    re.compile(r"^[ZY]([A-Z0-9]{3,})_APPEND$"),
    re.compile(r"^[ZY][A-Z]{2,4}_([A-Z0-9]{4,})_APPEND$"),
    # 'ZT023', 'ZMARD' -- a Z in front of a standard table name. Safe only because the
    # captured base must resolve to a known standard object before anything fires, so
    # 'ZINV' and 'ZGOODS' capture a base and then match nothing.
    re.compile(r"^[ZY]([A-Z][A-Z0-9]{2,})$"),
)


def append_base(cfg, name, text=""):
    """The standard object a custom structure appends to, from its name or short text.

    An append structure carries no business words of its own -- 'ZZMC11VA1ITM',
    'CI_BSIS', 'ZBW_CE3XXXX' -- but it always states its base somewhere, and the base
    IS the module. Appends to LIS communication structures are the classic case: no
    other rule in the ladder can attribute them.

    The short text is used as well as the name, because SAP's own generated text says
    it outright: 'Append for MC11VA1ITM', 'Fields from BSEG', 'Append from CE3XXXX'.
    """
    n = (name or "").upper()
    for rx in _APPEND_NAME:
        m = rx.match(n)
        if m:
            return m.group(1)
    for rx in cfg.append_text_patterns:
        m = rx.search(text or "")
        if m:
            return m.group(1).upper()
    return ""


def std_object_module(cfg, base):
    """Module of a standard DDIC object, by table map then by known prefix family."""
    b = (base or "").upper()
    if not b:
        return None, ""
    if b in cfg.table_to_module:
        return cfg.table_to_module[b], f"std-table:{b}"
    for pfx, mod in cfg.std_object_prefixes:
        if b.startswith(pfx):
            return mod, f"std-object:{pfx}*"
    return None, ""


def append_hits(cfg, name, text=""):
    base = append_base(cfg, name, text)
    if not base:
        return []
    mod, ev = std_object_module(cfg, base)
    if mod:
        return [(mod, f"appends {base} ({ev})")]
    return []


# --- R18: the standard data elements a DDIC object is built from ----------------------
def data_element_hits(cfg, elements):
    """Module hits from the SAP data elements a structure's fields are typed with.

    The strongest signal a DDIC object has, and the last one left when everything else
    is silent. A custom table's short text is often just its own name repeated, its
    check tables are frequently all non-discriminating (MARA, T001W), and nothing in
    the estate references it -- but the data elements its fields are typed with came out
    of SAP's dictionary, and they name the business object:

        ZZXX_PAYROLL_FIELDS    PERNR_D, LGART           -> payroll           -> HR
        ZXX_OFFSET_DESC            GKONT_LTXT               -> offsetting G/L    -> FI
        ZXX_TM_SCHEDULE            TPLST, LZONE, ROUTE      -> transportation    -> SD

    Only the leading module is returned. A structure typed from three modules' fields
    is a join, not a three-way owner, and ticking all three is exactly the smearing the
    breadth cap exists to prevent.
    """
    counts, examples = {}, {}
    for el in sorted(set(e.upper() for e in elements or ())):
        if el in cfg.non_discriminating_data_elements:
            continue
        for pfx, mod in cfg.std_data_elements:
            if el.startswith(pfx):
                counts[mod] = counts.get(mod, 0) + 1
                examples.setdefault(mod, el)
                break
    if not counts:
        return []
    top = max(sorted(counts.items()), key=lambda kv: kv[1])
    return [(top[0], f"field-types:{examples[top[0]]}"
                     + (f" +{top[1] - 1}" if top[1] > 1 else ""))]


# --- R14: IDoc segment / extension ----------------------------------------------------
def _segment_base(cfg, seg):
    """'ZE1KNA1M' -> 'KNA1M'; '' if the name is not an IDoc segment."""
    n = (seg or "").upper()
    for pfx in cfg.idoc_naming.get("segment_prefixes", []):
        for lead in ("Z", "Y", ""):
            head = lead + pfx
            if n.startswith(head) and len(n) > len(head):
                return n[len(head):]
    return ""


def _resolve_segment(cfg, base):
    """Module of whatever an IDoc segment extends.

    Tried longest-first, because segment names carry a trailing qualifier that is not
    part of the table name: E1KNA1M is KNA1 + M, E1WBB01 is WBB + 01. Resolution goes
    through the UNFILTERED table map -- see Config.table_to_module_all: the demotion of
    LFA1 is a statement about reads, and a structure named after the vendor master is
    not an incidental lookup.
    """
    b = (base or "").upper()
    for cand in (b, b[:-1], b[:-2], b[:4], b[:3]):
        if not cand:
            continue
        if cand in cfg.table_to_module_all:
            return cfg.table_to_module_all[cand], f"segment-of:{cand}"
        for pfx, mod in cfg.std_object_prefixes:
            if cand.startswith(pfx):
                return mod, f"segment-of:{pfx}*"
    return None, ""


def idoc_hits(cfg, name, otype, text="", refs=(), text_refs=()):
    """IDoc evidence: the object IS a segment, or its code NAMES segments and messages.

    Three distinct facts, all of them invisible to every other rule:

      the object's own name    'ZE1KNA1M' is an extension to the DEBMAS customer-master
                               segment -- an interface object AND a customer-master
                               object. Reporting only the first loses the business
                               owner; only the second loses that it is an interface.
      segments in its code     an inbound exit declaring `TYPE e1kna1m` is processing
                               customer master, however little else it says. A segment
                               type is a DDIC structure, so no table rule sees it.
      message types in its code  the strongest of the three. `pi_mestyp = 'WBBDLD'`
                               names the business process outright, and SAP's message
                               type list is fixed and public.

    Message types are read from CODE ONLY, never from a short text, and the reason is
    ORDERS. It is a genuine SAP message type and also an ordinary English word, so
    scanning descriptions for message types attributed thirty-three programs about
    production orders, payment orders and sales orders to purchasing -- each with the
    evidence line 'idoc-message:ORDERS', each of them wrong, and R14 was the only rule
    supporting the tick. A literal next to MESTYP is an assignment; a word in a
    sentence is a word in a sentence.

    Segment names taken from a short text stay allowed: 'E1KNA1M' cannot be anything
    else, and the shape is what makes it safe.
    """
    if not cfg.idoc_naming:
        return []
    hits, seen = [], set()

    def push(mod, ev):
        if mod and (mod, ev) not in seen:
            seen.add((mod, ev))
            hits.append((mod, ev))

    bucket = cfg.resolve_special(cfg.idoc_naming.get("bucket", "@INTEGRATION"))
    own = _segment_base(cfg, name)
    is_idoc_obj = bool(own) or (otype or "").upper() in cfg.idoc_naming.get("types", [])
    if is_idoc_obj:
        push(bucket, f"idoc-object:{name}")
        mod, ev = _resolve_segment(cfg, own)
        push(mod, f"idoc-extends:{own} ({ev})" if mod else "")

    for ref in sorted(set(r.upper() for r in text_refs or ())):
        base = _segment_base(cfg, ref)
        if base:
            push(bucket, f"idoc-segment-in-text:{ref}")
            mod, ev = _resolve_segment(cfg, base)
            push(mod, f"idoc-segment-in-text:{ref} ({ev})")

    for ref in sorted(set(r.upper() for r in refs or ())):
        mods = cfg.idoc_message_types.get(ref)
        if mods:
            push(bucket, f"idoc-message:{ref}")
            for m in mods:
                push(m, f"idoc-message:{ref}")
            continue
        base = _segment_base(cfg, ref)
        if base:
            push(bucket, f"idoc-segment-ref:{ref}")
            mod, ev = _resolve_segment(cfg, base)
            push(mod, f"idoc-segment-ref:{ref} ({ev})")
    return [(m, e) for m, e in hits if m and e]


# --- R15: an include named after the function group it belongs to ---------------------
def fugr_include_hits(cfg, name):
    """'ZLKED2TOP' -> the TOP include of a clone of SAP's KED2 (CO-PA planning) -> CO.

    A function group's includes are L<AREA>TOP / L<AREA>UXX / L<AREA>F01, and a copy of
    a standard group keeps that shape with a Z in front. Such an include declares only
    a FUNCTION-POOL and some data, so it has nothing a table or call rule can read, and
    nothing references it -- but its own name states the standard function group it
    came from, which is the one fact that settles it.
    """
    n = (name or "").upper()
    for lead in ("Z", "Y"):
        if not n.startswith(lead + "L"):
            continue
        body = n[len(lead) + 1:]
        for suffix in cfg.fugr_include_suffixes:
            if body.endswith(suffix) and len(body) > len(suffix) + 1:
                area = body[:-len(suffix)]
                mod, ev = std_object_module(cfg, area)
                if not mod:
                    mod = std_call_module(cfg, area)
                    ev = f"std-fugr:{area}"
                if mod:
                    return [(mod, f"fugr-include:{name} -> {area} ({ev})")]
    return []


_WORD_RX = re.compile(r"[A-Z][A-Z0-9_]{2,}")


def text_words(text):
    """Upper-case tokens in a short text -- the only place a DDIC object can speak.

    'Extension to Vendor Master (CREMAS) - user access' names the IDoc message type
    outright, and a structure has no code for anything else to read.
    """
    return _WORD_RX.findall((text or "").upper())


# --- R8: description keywords ---------------------------------------------------------
def text_hits(cfg, text):
    """Module hits from description keywords, anchored at a word START.

    A plain substring test is what makes this rule embarrassing: the German title
    'PM/SM-Formular f. alle Papiere' matched the keyword 'API' inside "Papiere" and
    filed an SAP quality-management sample form under external interfaces.

    Anchored at the start of a word only, NOT at the end, and that asymmetry is
    deliberate: many keyword lists are word STEMS so they match inflected forms -- a
    Greek or German list will hold 'ΠΑΡΑΓΓΕΛ' to catch 'ΠΑΡΑΓΓΕΛΙΑ' and 'ΠΑΡΑΓΓΕΛΙΩΝ'.
    Requiring a trailing boundary would break every one of them; requiring a leading one
    costs nothing and kills the false positives.
    """
    if not text:
        return []
    t = text.upper()
    out = []
    for mod, kws in cfg.text_keywords.items():
        for kw in kws:
            k = kw.upper()
            if not k:
                continue
            if re.search(r"(?<![^\W_])" + re.escape(k), t):
                out.append((mod, f"text:{kw.title()}"))
                break
    return out


# --- R8s: a description that NAMES a standard object -----------------------------
def text_names_standard(cfg, text):
    """Standard object names appearing in a short text.

    SAP's own generated titles frequently name the program that prints the form:
    'RFDUZI00 Interest Calculation' on a SAPscript form is the interest-on-arrears
    report, which settles the module where the form's own name (`YXX_F_DUZI_01`) says
    nothing at all. Only tokens the wrapper table already recognises are used, so an
    ordinary English word in a description cannot fire this.
    """
    hits, seen = [], set()
    for tok in text_words(text):
        for mod, ev in wrapper_hits(cfg, tok):
            if mod not in seen:
                seen.add(mod)
                hits.append((mod, f"text-names:{tok}"))
    return hits


# --- accumulator ----------------------------------------------------------------------
class Attribution:
    """Accumulates (module -> best authority) plus ordered evidence clauses.

    Hits naming a module outside the tick vocabulary are kept separately in
    `proposed`, never dropped. `suppressed` records hits for modules a human has
    explicitly ruled out, so even a deliberate silence is counted.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.best = {}          # module -> authority
        self.support = {}       # module -> {rule ids that named it}
        self.rules = []         # rule ids in fire order
        self.evidence = []      # evidence clauses in fire order
        self.proposed = {}      # out-of-vocabulary module -> [authority, evidence]
        self.suppressed = set()
        self.notes = []

    def add(self, module, authority, rule_id, evidence):
        module = (module or "").upper()
        if not module:
            return
        if not self.cfg.in_vocab(module):
            if self.cfg.is_ruled_out(module):
                self.suppressed.add(module)
                return
            if not self.cfg.open_vocabulary:
                return
            cur = self.proposed.get(module)
            if cur is None or _RANK[authority] > _RANK[cur[0]]:
                self.proposed[module] = [authority, evidence or "", rule_id]
            return
        cur = self.best.get(module)
        if cur is None or _RANK[authority] > _RANK[cur]:
            self.best[module] = authority
        self.support.setdefault(module, set()).add(rule_id)
        if rule_id not in self.rules:
            self.rules.append(rule_id)
        if evidence and evidence not in self.evidence:
            self.evidence.append(evidence)

    def add_many(self, hits, authority, rule_id):
        for mod, ev in hits:
            self.add(mod, authority, rule_id, ev)

    @property
    def modules(self):
        return [m for m in self.cfg.all_modules if m in self.best]

    @property
    def core_modules(self):
        return [m for m in self.cfg.core if m in self.best]

    def trim_core_breadth(self):
        """Enforce the breadth cap by DROPPING ticks, not just flagging the row.

        The design has always said "mark it cross-module rather than ticking half the
        estate", and the CROSS column existed -- but nothing ever dropped a tick, so a
        unit could carry the flag AND all six core ticks at once. The validator forbids
        five, so the two disagreed, and whichever fired last decided what shipped.

        A five-module tick is not wrong so much as useless: an MIS income report really
        does read FI, MM, SD, CO and PP tables, and telling five teams they all own it
        tells none of them anything. The flag is the useful answer; the ticks above the
        cap are noise.

        Kept: highest authority first, then the most distinct rules naming it, then
        alphabetical -- deterministic, and independent of config list order. Buckets are
        never trimmed; they are concerns, and an object legitimately has several.
        Returns the modules dropped, for the row's notes.
        """
        cap = self.cfg.tuning["breadth_cap"]
        core = self.core_modules
        if len(core) <= cap:
            return []
        ranked = sorted(core, key=lambda m: (-_RANK[self.best[m]],
                                             -len(self.support.get(m, ())), m))
        dropped = ranked[cap:]
        for m in dropped:
            self.best.pop(m, None)
            self.support.pop(m, None)
        return dropped

    @property
    def confidence(self):
        if not self.best:
            return "NONE"
        return CONFIDENCE[max(self.best.values(), key=lambda a: _RANK[a])]

    @property
    def primary_module(self):
        """Highest-authority single module, for pivot tables.

        The tie-break used to end at `-all_modules.index(m)`, which means the FIRST
        entry in modules.core won every tie -- so whichever module a consultant happened
        to type first in the config became the owner of every genuinely two-sided unit,
        and its share of the estate was inflated by an artefact of list order -- the
        leading module's primary share ended up within a point of its tick share, which
        is not a thing that can be true of real code.

        Now ties go to the module the most DISTINCT RULES named. Two independent
        signals agreeing is real evidence of ownership where one is not, and it is
        order-independent. Core-vs-bucket still ranks above that, because a bucket is a
        concern rather than an owner, and the last resort is alphabetical -- arbitrary,
        but at least not a property of how the config was typed.
        """
        if not self.best:
            return ""
        return max(self.modules,
                   key=lambda m: (_RANK[self.best[m]], m in self.cfg.core,
                                  len(self.support.get(m, ())), m))[:]
