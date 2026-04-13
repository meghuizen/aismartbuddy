---
summary: lxml 6.0.4 for building and parsing small well-formed XML documents (cache files, config)
read_when: Implementing XML read/write with lxml, before calling etree.Element or etree.parse
---

# lxml.etree -- Build, Serialize, Parse XML

lxml is a Pythonic binding for libxml2/libxslt. This doc covers only the
build-serialize-parse pattern for small, well-formed XML documents (cache files,
config, metadata stores). XSLT, HTML parsing, schema validation, and advanced
XPath are out of scope.

**Version researched**: 6.0.4 (released 2026-04-12, built on libxml2 2.11.9)
**Python compatibility**: 3.9+
**Official docs**: https://lxml.de/
**Install**: `pip install lxml` (binary wheels available for all major platforms)

---

## 1. Building XML

### Element (root)

```python
from lxml import etree

root = etree.Element("video", id="abc123", langcode="en",
                     fetched_at="2026-04-12T10:00:00Z")
```

`Element(tag, attrib=None, nsmap=None, **extra)` creates an element.
Keyword arguments become attributes. All attribute values must be strings.

### SubElement (children)

```python
title = etree.SubElement(root, "title")
title.text = "My Video Title"
```

`SubElement(parent, tag, attrib=None, nsmap=None, **extra)` creates a child
element and appends it to `parent` in one call. This is the idiomatic way to
build trees -- do not create elements separately and then append unless you
need to move them between trees.

### Attributes

```python
# Set during creation
etree.SubElement(langs, "lang", code="en", name="English", generated="true")

# Set after creation
el.set("key", "value")

# Read
val = el.get("key")            # returns str or None
val = el.get("key", "default") # returns str or "default"

# Dict-like access
el.attrib["key"] = "value"
all_attrs = dict(el.attrib)
```

All attribute values are strings. There is no automatic type conversion. Store
booleans as `"true"/"false"`, numbers as their string representation.

### Text content

```python
seg.text = "Hello world"
```

Assign a string to `.text`. Special characters (`<`, `>`, `&`) are
automatically escaped to entities (`&lt;`, `&gt;`, `&amp;`) during
serialization. You never need to pre-escape text -- lxml handles it.

When parsed back, `.text` returns the original unescaped string. The escaping
is transparent and round-trips correctly.

### CDATA sections

```python
desc = etree.SubElement(root, "description")
desc.text = etree.CDATA("This has <b>HTML</b> & chars: https://example.com/?foo=bar&baz=1")
```

`etree.CDATA(text)` wraps text so it serializes as `<![CDATA[...]]>` instead
of entity-escaped text. Use CDATA when:

- The text contains heavy HTML/XML markup that would become unreadable with escaping
- You want the on-disk XML to remain human-readable for debugging
- You are storing URLs with `&` parameters, code snippets, etc.

CDATA is purely a serialization choice. Both CDATA and entity-escaped text parse
back to the same `.text` string value.

**CDATA round-trip behavior (important):**

The default parser strips CDATA markers. After `parse()`, the text is stored as
a plain string. Re-serializing produces entity-escaped output, not CDATA:

```python
# Write file with CDATA
desc.text = etree.CDATA("<b>HTML</b> & stuff")
tree.write("file.xml", ...)

# Parse back with default parser
parsed = etree.parse("file.xml")
desc = parsed.getroot().find("description")
desc.text  # => '<b>HTML</b> & stuff'  (plain string, CDATA stripped)
etree.tostring(desc, encoding='unicode')
# => '<description>&lt;b&gt;HTML&lt;/b&gt; &amp; stuff</description>'
```

To preserve CDATA on round-trip, use `strip_cdata=False`:

```python
parser = etree.XMLParser(strip_cdata=False)
parsed = etree.parse("file.xml", parser)
# Now re-serializing produces <![CDATA[...]]> again
```

If your cache is write-once-read-once (write XML, later parse to get data), the
default parser is fine -- the `.text` value is identical either way.

If you need to read-modify-write the XML and preserve CDATA sections, always
parse with `XMLParser(strip_cdata=False)`.

### Self-closing elements (empty elements)

```python
etree.SubElement(langs, "lang", code="en", name="English", generated="true")
# Serializes as: <lang code="en" name="English" generated="true"/>
```

Elements with no text and no children serialize as self-closing tags
automatically.

---

## 2. Serializing

### tostring() -- to bytes or str

```python
# Bytes output (for writing to files, network)
xml_bytes = etree.tostring(
    root,
    pretty_print=True,       # indent with 2 spaces
    xml_declaration=True,     # add <?xml ...?> header
    encoding='utf-8'          # encode as UTF-8 bytes
)
# type: bytes
# b"<?xml version='1.0' encoding='utf-8'?>\n<video ...>\n  <title>..."
```

```python
# String output (for logging, debugging)
xml_str = etree.tostring(root, pretty_print=True, encoding='unicode')
# type: str
# No xml_declaration allowed with encoding='unicode'
```

**Key parameters:**

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `pretty_print` | bool | `False` | Adds indentation and newlines |
| `xml_declaration` | bool | `False` | Adds `<?xml version='1.0' ...?>` |
| `encoding` | str | (ASCII bytes) | `'utf-8'` for bytes, `'unicode'` for str |
| `method` | str | `'xml'` | Also `'html'`, `'text'`, `'c14n'` |
| `with_tail` | bool | `True` | Include tail text after element |

**Encoding behavior:**

- `encoding='utf-8'` -- returns `bytes`, declaration says `encoding='utf-8'`
- `encoding='UTF-8'` -- returns `bytes`, declaration says `encoding='UTF-8'`
- `encoding='unicode'` -- returns `str`, **cannot** combine with `xml_declaration=True` (raises ValueError)
- No encoding specified -- returns `bytes` with ASCII encoding

**xml_declaration behavior:**

- `xml_declaration=True` requires an encoding other than `'unicode'`
- Without explicit `xml_declaration=True`, no declaration is emitted even with `encoding='utf-8'`
- Without explicit encoding, declaration defaults to `encoding='ASCII'`

### Recommended serialization for a cache file

```python
xml_bytes = etree.tostring(
    root,
    pretty_print=True,
    xml_declaration=True,
    encoding='utf-8'
)
```

This produces clean, readable, valid XML with a proper declaration.

---

## 3. Writing to file

### ElementTree.write() -- direct file output

```python
tree = etree.ElementTree(root)
tree.write(
    "cache/video_abc123.xml",
    pretty_print=True,
    xml_declaration=True,
    encoding='utf-8'
)
```

Same parameters as `tostring()`. Accepts a file path (string) or a file-like
object opened in binary mode.

**Encoding casing note**: `write()` uppercases the encoding in the XML
declaration regardless of what you pass. `encoding='utf-8'` produces
`encoding='UTF-8'` in the file. `tostring()` preserves casing as given.
This is cosmetic and has no functional impact.

**File path vs file object:**

```python
# Path string (preferred -- simpler, slightly more efficient)
tree.write("path/to/file.xml", pretty_print=True, xml_declaration=True, encoding='utf-8')

# File object (must be binary mode)
with open("path/to/file.xml", "wb") as f:
    tree.write(f, pretty_print=True, xml_declaration=True, encoding='utf-8')
```

### Alternative: tostring() + file write

```python
xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='utf-8')
Path("cache/video.xml").write_bytes(xml_bytes)
```

Both approaches produce identical output. Use `tree.write()` for simplicity;
use `tostring()` when you also need the bytes in memory (e.g., for hashing).

---

## 4. Parsing (reading XML files)

### etree.parse() -- from file path (preferred for files)

```python
tree = etree.parse("cache/video_abc123.xml")
root = tree.getroot()
```

Returns an `ElementTree`. Call `.getroot()` to get the root `Element`.

Passing a file path string is more efficient than passing a file object because
lxml can use optimized C-level I/O.

`parse()` also accepts file-like objects, `BytesIO`, and HTTP/FTP URLs.

### etree.fromstring() -- from bytes in memory

```python
xml_bytes = Path("cache/video.xml").read_bytes()
root = etree.fromstring(xml_bytes)
```

Returns an `Element` directly (not an `ElementTree`).

Use `fromstring()` when you already have the XML as bytes in memory. For reading
a file, prefer `parse()` -- it avoids loading the entire file into a Python
bytes object first.

### Which to use

| Situation | Function | Returns |
|-----------|----------|---------|
| Reading a file on disk | `etree.parse(path)` | `ElementTree` (call `.getroot()`) |
| XML bytes already in memory | `etree.fromstring(data)` | `Element` directly |
| XML string in memory | `etree.fromstring(s.encode('utf-8'))` | `Element` directly |

`fromstring()` accepts both `bytes` and `str`, but passing bytes is preferred.
The lxml FAQ states: "You should generally avoid converting XML/HTML data to
unicode before passing it into the parsers. It is both slower and error prone."

### Parser options (rarely needed for well-formed cache files)

```python
parser = etree.XMLParser(
    strip_cdata=False,        # preserve CDATA sections (default True = strip)
    remove_blank_text=True,   # remove whitespace-only text nodes (for re-formatting)
)
tree = etree.parse("file.xml", parser)
```

For a simple cache file you wrote yourself, the default parser is fine. Only
customize if you need `strip_cdata=False` for CDATA preservation.

---

## 5. Accessing parsed data

### Attributes

```python
root.get("id")            # "abc123" or None
root.get("missing", "")   # "" (default)
root.attrib               # dict-like: {"id": "abc123", "langcode": "en", ...}
```

### Text content

```python
root.find("title").text           # "My Video Title"
root.find("description").text     # raw string, CDATA stripped by default
```

### findtext() -- text with default

```python
root.findtext("title")                  # "My Video Title"
root.findtext("nonexistent", default="N/A")  # "N/A"
```

Combines `find()` + `.text` in one call with a default for missing elements.

### find() -- first match

```python
root.find("title")                # first direct child named "title"
root.find("transcript/seg")       # first <seg> inside <transcript>
root.find(".//seg")               # first <seg> anywhere in tree
```

Returns `Element` or `None`. **Warning**: testing `if element:` is unreliable
because an element with no children is falsy. Always use `if element is not None:`.

### findall() -- all matches

```python
segs = root.findall(".//seg")     # list of all <seg> elements
langs = root.findall("available_languages/lang")  # all <lang> children
```

Returns a `list` (possibly empty, never `None`).

### iter() -- depth-first traversal

```python
for seg in root.iter("seg"):
    start = seg.get("start")
    dur = seg.get("duration")
    text = seg.text
```

Iterates all matching elements in document order (depth-first). More memory
efficient than `findall()` for large documents, but for a small cache file
either is fine.

### Path expressions (ElementPath subset)

lxml's `find()`/`findall()` support a subset of XPath called ElementPath:

```
"tag"              -- direct child by tag name
"parent/child"     -- path through children
".//tag"           -- any descendant
"*/tag"            -- grandchildren named tag
"tag[@attr]"       -- child with attribute present
"tag[@attr='val']" -- child with attribute value
```

This is sufficient for the cache structure described. Full XPath is available
via `root.xpath()` but unnecessary here.

---

## 6. Escaping and special characters

### Automatic escaping (you almost never need CDATA)

lxml automatically escapes special XML characters in text content:

```python
seg.text = "This has <angle brackets> & ampersands"
etree.tostring(seg, encoding='unicode')
# '<seg ...>This has &lt;angle brackets&gt; &amp; ampersands</seg>'
```

On parse-back, `.text` returns the original unescaped string:

```python
seg.text  # "This has <angle brackets> & ampersands"
```

The escaping is transparent. You assign raw strings, you get raw strings back.
The XML file contains entities, but you never see them in your Python code.

### When to use CDATA vs plain text

**Use plain text** (the default) for:
- Simple strings, titles, names
- Transcript text with occasional special chars
- Anything you will only read programmatically

**Use CDATA** for:
- Content with heavy HTML/XML markup (descriptions with `<b>`, `<a href>`, etc.)
- Content you want human-readable when viewing the raw XML file
- URLs with `&` query parameters where entity escaping hurts readability

Both are semantically identical after parsing. The choice is purely about
on-disk readability.

### Attribute values

Attribute values are also automatically escaped:

```python
el.set("url", "https://example.com/?a=1&b=2")
# Serializes as: url="https://example.com/?a=1&amp;b=2"
# el.get("url") returns: "https://example.com/?a=1&b=2"
```

No manual escaping needed. CDATA is not available for attributes (XML spec
limitation, not lxml-specific).

---

## 7. Complete example: your YouTube cache

### Writing

```python
from lxml import etree

def build_video_xml(video_id: str, langcode: str, title: str,
                    description: str, languages: list[dict],
                    segments: list[dict], fetched_at: str) -> etree._Element:
    root = etree.Element("video", id=video_id, langcode=langcode,
                         fetched_at=fetched_at)

    title_el = etree.SubElement(root, "title")
    title_el.text = title

    desc_el = etree.SubElement(root, "description")
    desc_el.text = etree.CDATA(description)  # may contain HTML/URLs

    langs_el = etree.SubElement(root, "available_languages")
    for lang in languages:
        etree.SubElement(langs_el, "lang",
                         code=lang["code"],
                         name=lang["name"],
                         generated=str(lang["generated"]).lower())

    transcript_el = etree.SubElement(root, "transcript")
    for seg in segments:
        seg_el = etree.SubElement(transcript_el, "seg",
                                  start=str(seg["start"]),
                                  duration=str(seg["duration"]))
        seg_el.text = seg["text"]

    return root


def write_video_cache(root: etree._Element, path: str) -> None:
    tree = etree.ElementTree(root)
    tree.write(path, pretty_print=True, xml_declaration=True, encoding='utf-8')
```

### Reading

```python
from lxml import etree

def read_video_cache(path: str) -> dict:
    tree = etree.parse(path)
    root = tree.getroot()

    languages = []
    for lang in root.findall("available_languages/lang"):
        languages.append({
            "code": lang.get("code"),
            "name": lang.get("name"),
            "generated": lang.get("generated") == "true",
        })

    segments = []
    for seg in root.iter("seg"):
        segments.append({
            "start": float(seg.get("start")),
            "duration": float(seg.get("duration")),
            "text": seg.text or "",
        })

    return {
        "video_id": root.get("id"),
        "langcode": root.get("langcode"),
        "fetched_at": root.get("fetched_at"),
        "title": root.findtext("title", default=""),
        "description": root.findtext("description", default=""),
        "languages": languages,
        "segments": segments,
    }
```

---

## 8. Common mistakes

### Falsy element check

```python
# WRONG -- element with no children evaluates as False
el = root.find("transcript")
if el:           # False if <transcript> has no children!
    process(el)

# CORRECT
if el is not None:
    process(el)
```

This is the single most common lxml bug. An empty element (no children) is
falsy. Always compare explicitly with `is not None`.

### Forgetting encoding='utf-8' in tostring

```python
# Returns ASCII bytes, no declaration
etree.tostring(root, xml_declaration=True)
# b"<?xml version='1.0' encoding='ASCII'?>..."

# What you want
etree.tostring(root, xml_declaration=True, encoding='utf-8')
```

### Combining encoding='unicode' with xml_declaration

```python
# RAISES ValueError
etree.tostring(root, encoding='unicode', xml_declaration=True)
```

The XML spec requires the declaration to specify a byte encoding. A Python
`str` has no byte encoding, so lxml refuses this combination.

### Pretty-print not working on re-serialization

If you parse a file and re-serialize with `pretty_print=True`, existing
whitespace text nodes can interfere. Use `remove_blank_text=True` when
parsing to allow lxml to reformat:

```python
parser = etree.XMLParser(remove_blank_text=True)
tree = etree.parse("file.xml", parser)
# Now tree.write(..., pretty_print=True) will format cleanly
```

For cache files you wrote yourself with `pretty_print=True`, this is already
fine. This matters when parsing XML from external sources.

### Modifying tree during iteration

```python
# DANGEROUS -- may skip elements or crash
for seg in root.iter("seg"):
    if some_condition(seg):
        seg.getparent().remove(seg)

# SAFE -- collect first, then modify
for seg in root.findall(".//seg"):  # list, not iterator
    if some_condition(seg):
        seg.getparent().remove(seg)
```

### Opening XML files in text mode

```python
# WRONG -- can cause encoding mismatches
with open("file.xml", "r") as f:
    tree = etree.parse(f)

# CORRECT -- binary mode or just pass the path
tree = etree.parse("file.xml")
```

XML is defined as a byte stream. The parser reads the encoding from the XML
declaration. Pre-decoding as text can conflict with the declared encoding.

---

## 9. Gotchas

### write() uppercases encoding in declaration

`tree.write(..., encoding='utf-8')` produces `encoding='UTF-8'` in the file.
`tostring(..., encoding='utf-8')` produces `encoding='utf-8'`. Both are valid
XML. This is cosmetic only.

### CDATA is stripped by default on parse

The default `XMLParser` has `strip_cdata=True`. After parsing, CDATA content
becomes plain text. Re-serializing produces entity-escaped output, not CDATA.
If you need CDATA preserved for round-trip editing, parse with
`XMLParser(strip_cdata=False)`.

For a cache that is written once and read once, this does not matter -- the
`.text` value is identical regardless.

### Attribute ordering

lxml may not preserve the order of attributes you specified. The XML spec
says attribute order is not significant. If you need a specific order for
readability, note that lxml generally preserves insertion order in practice
(Python dict ordering), but this is not guaranteed by the spec.

### seg.text can be None

An empty element has `.text` of `None`, not `""`:

```python
seg = etree.SubElement(transcript, "seg", start="0.0", duration="1.0")
# seg.text is None, not ""
seg.text  # None
```

Always handle this: `seg.text or ""`.

### Namespace prefixes in find()

If your XML has no namespaces (like the cache structure above), this is not
an issue. But if you ever add namespaces, `find("tag")` will not match
`{http://ns}tag`. You must use `find("{http://ns}tag")` or pass a
`namespaces` dict. For cache files under your control, avoid namespaces.

---

## Links

- [Official tutorial](https://lxml.de/tutorial.html)
- [Parsing docs](https://lxml.de/parsing.html)
- [API reference: lxml.etree](https://lxml.de/apidoc/lxml.etree.html)
- [Element class API](https://lxml.de/api/lxml.etree._Element-class.html)
- [CDATA class](https://lxml.de/api/lxml.etree.CDATA-class.html)
- [FAQ (common pitfalls)](https://lxml.de/FAQ.html)
- [lxml.etree-specific APIs](https://lxml.de/api.html)
- [Changelog](https://github.com/lxml/lxml/blob/master/CHANGES.txt)
- [PyPI](https://pypi.org/project/lxml/)
