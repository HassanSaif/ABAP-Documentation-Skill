"""
names.py -- abapGit filename parsing, and name repair for the opaque object types.

The naive parser (`ls | awk '{print $NF}'`, or splitting on whitespace in any form)
silently corrupts every filename containing a space, and abapGit emits plenty of them
because it pads compound keys to a fixed width:

    'extsys         a1b2c3d4e5f60718293a4b5c6.sicf.xml'
    'zc_mm_foo_cds       0001.iwsv.xml'
    '991000ZXX_WM_FOO                    .iatu.xml'

A large estate typically has a couple of hundred of these. Parsed by whitespace they
become object names like 'a1b2c3d4e5f60718293a4b5c6' and '0001', which
is how SICF nodes and OData services end up in an inventory under hash names.

The correct rule is simple: ABAP object names cannot contain a dot, and abapGit always
emits '<name>.<type>[.<subtype>].<ext>'. So the type is the SECOND dot-token,
unconditionally, and the name is the first -- spaces included.
"""

import re

_WS = re.compile(r"\s+")

# Types whose on-disk name is a padded compound key or a generated hash. Their
# human-readable name has to be recovered from the XML payload.
REPAIR_TAGS = {
    "sicf": ["ICF_NAME", "ORIG_NAME", "URL"],
    "iwsv": ["SERVICE_NAME", "TECHNICAL_NAME"],
    "iwmo": ["MODEL_NAME", "TECHNICAL_NAME"],
    "iwvb": ["VOCABULARY_NAME", "TECHNICAL_NAME"],
    "iatu": ["TEMPLATE_NAME", "PROGRAM"],
    "tobj": ["OBJECT"],
    "sush": ["NAME"],
    # 'zmm         zmmbarcode.aqqu.xml' -> ZMMBARCODE (the query), not 'ZMM ZMMBARCODE'
    "aqqu": ["QNUM"],
}


class ParsedName:
    __slots__ = ("filename", "raw_name", "object_type", "subtype", "ext")

    def __init__(self, filename, raw_name, object_type, subtype, ext):
        self.filename = filename
        self.raw_name = raw_name
        self.object_type = object_type
        self.subtype = subtype
        self.ext = ext

    @property
    def object_name(self):
        """Uppercased name with padding runs collapsed.

        The padding is positional, not semantic, so 'extsys         a1b2c3d4...'
        collapses to 'EXTSYS A1B2C3D4...' -- stable and non-lossy. For the opaque
        types the name a consultant would recognise comes from repair_name().
        """
        return _WS.sub(" ", self.raw_name).strip().upper()

    def __repr__(self):
        return f"ParsedName({self.object_name!r}, {self.object_type!r})"


def make_parser(known_types):
    """Return parse(filename) -> ParsedName|None for one set of known object types."""
    known = {t.lower() for t in known_types}

    def parse(filename):
        parts = filename.split(".")
        if len(parts) < 3:
            return None
        raw_name, otype = parts[0], parts[1].lower()
        if not raw_name or otype not in known:
            return None
        subtype = ".".join(parts[2:-1]) if len(parts) > 3 else ""
        return ParsedName(filename, raw_name, otype, subtype, parts[-1].lower())

    return parse


def is_main_file(parsed):
    """True for the object's own definition file, not a sub-part.

    Counts objects without double-counting: a function group is one object across its
    ~7 include files, a class one object across locals/testclasses.
    """
    return parsed.subtype == ""


def repair_name(parsed, tag_values):
    """Best human-readable name for an opaque object, given its extracted XML tags."""
    for tag in REPAIR_TAGS.get(parsed.object_type, ()):
        val = (tag_values.get(tag) or "").strip()
        if val:
            return val.upper() if not val.startswith("/") else val
    return parsed.object_name


def is_custom(name, prefixes=("Z", "Y")):
    """Custom-namespace test. '/NS/ZFOO' counts; a bare '/IWFND/...' does not."""
    if not name:
        return False
    n = name.upper()
    if n.startswith("/"):
        end = n.find("/", 1)
        if end < 0:
            return False
        n = n[end + 1:]
    return bool(n) and n[0] in tuple(p.upper() for p in prefixes)


def strip_namespace(name):
    """'/NS/ZFOO' -> 'ZFOO'; 'ZFOO' -> 'ZFOO'."""
    n = (name or "").upper()
    if n.startswith("/"):
        end = n.find("/", 1)
        if end > 0:
            return n[end + 1:]
    return n
