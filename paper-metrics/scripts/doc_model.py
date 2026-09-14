#!/usr/bin/env python3
"""Typed document model of the metrics base artifact (design L1/L2).

The base artifact is a MinerU content_list.json: a list of typed blocks whose text
lives in DIFFERENT fields depending on the block type (text / table_body /
list_items / ...), and whose captions live in one of four *_caption keys.  Parsing
it in exactly one place means every consumer works with typed records instead of
raw dicts, and the census cannot silently miss a field again - counting lists as
"0 characters" is precisely the bug this module exists to prevent.

Streams are the unit of scope: a metric declares which stream it reads, and the
census states the size of every stream the metrics do NOT read.

Python 3.10: StrEnum / Never / assert_never are 3.11+, so the shims below stay
local and explicit instead of pulling in typing_extensions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, NoReturn

# ---------------------------------------------------------------------------
# JSON boundary types (no bare Any: the boundary produces these, nothing else)
# ---------------------------------------------------------------------------

JsonScalar = str | int | float | bool | None
#: Covariant containers on purpose: a nested literal like {"figures": [1]} must be
#: assignable where JsonValue is expected, and list/dict are invariant in their
#: parameter while Sequence/Mapping are not.
JsonValue = JsonScalar | Sequence["JsonValue"] | Mapping[str, "JsonValue"]


class DocumentParseError(Exception):
    """The base artifact could not be parsed into a document model."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path: Path = path
        self.reason: str = reason


def assert_never(value: NoReturn) -> NoReturn:
    """Exhaustiveness guard (3.10 shim for typing.assert_never)."""
    raise AssertionError(f"unhandled variant: {value!r}")


class Stream(str, Enum):
    """Where a block belongs.  The metrics read PROSE and nothing else - yet."""

    PROSE = "prose"
    TABLES = "tables"
    EQUATIONS = "equations"
    FIGURES = "figures"
    LISTS = "lists"
    FOOTNOTES = "footnotes"
    RUNNING_HEADS = "running_heads"
    PAGE_NUMBERS = "page_numbers"
    ASIDES = "asides"
    CODE = "code"
    OTHER = "other"


#: MinerU block type -> stream.  An unknown type lands in OTHER and is reported,
#: never dropped silently.
_STREAM_OF_TYPE: Final[dict[str, Stream]] = {
    "text": Stream.PROSE,
    "table": Stream.TABLES,
    "equation": Stream.EQUATIONS,
    "image": Stream.FIGURES,
    "chart": Stream.FIGURES,
    "list": Stream.LISTS,
    "page_footnote": Stream.FOOTNOTES,
    "header": Stream.RUNNING_HEADS,
    "footer": Stream.RUNNING_HEADS,
    "page_number": Stream.PAGE_NUMBERS,
    "aside_text": Stream.ASIDES,
    "code": Stream.CODE,
}

#: The only stream the frozen metrics read.  Everything else is censused and
#: declared as unread, so "we never looked at the tables" is a stated fact.
_METRIC_STREAMS: Final[frozenset[Stream]] = frozenset({Stream.PROSE})

_HTML_COMMENT_RE: Final = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG_RE: Final = re.compile(r"<[^>]+>")
_HTML_BREAK_RE: Final = re.compile(r"</(?:td|th|tr)>|<br\s*/?>", re.IGNORECASE)
_HTML_ENTITY_RE: Final = re.compile(r"&(#x?[0-9a-fA-F]+|[a-zA-Z]+);")
_LATEX_CMD_RE: Final = re.compile(r"\\[A-Za-z]+")
_LATEX_NOISE_RE: Final = re.compile(r"[\u0024{}\\]")
_DIGIT_RE: Final = re.compile("\u005b0-9\uFF10-\uFF19\u005d")
_WHITESPACE_RE: Final = re.compile(r"\s+")
_ENTITY_MAP: Final[dict[str, str]] = {"amp": "&", "lt": "<", "gt": ">",
                                      "quot": '"', "apos": "'", "nbsp": " "}


def stream_of_type(block_type: str) -> Stream:
    """Stream of a MinerU block type; unknown types go to Stream.OTHER."""
    return _STREAM_OF_TYPE.get(block_type, Stream.OTHER)


def count_digits(text: str) -> int:
    """Count ASCII and full-width digits (CNKI encodes digits full-width)."""
    return len(_DIGIT_RE.findall(text))


def _decode_entity(match: re.Match[str]) -> str:
    body = match.group(1)
    try:
        if body[:2].lower() == "#x":
            # base 16 with the prefix stripped: passing base 0 with "#" rewritten to
            # "0x" works too, but the decimal branch cannot use base 0 at all
            # ("01234" is invalid there), so both branches stay explicit.
            return chr(int(body[2:], 16))  # noqa: FURB166
        if body[0] == "#":
            return chr(int(body[1:]))
    except (ValueError, IndexError):
        return match.group(0)
    return _ENTITY_MAP.get(body.lower(), match.group(0))


def html_to_text(raw: str) -> str:
    """Cell text of a table_body with the markup taken out.

    Required before any table metric: on the real corpus the raw HTML is 51.8%
    markup by character count, and its attributes carry thousands of digits that
    are not content at all (colspan, widths, style numbers).
    """
    text = _HTML_COMMENT_RE.sub(" ", raw)
    text = _HTML_BREAK_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _HTML_ENTITY_RE.sub(_decode_entity, text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def latex_to_text(raw: str) -> str:
    """LaTeX with its scaffolding removed; variables and digits survive."""
    text = _LATEX_NOISE_RE.sub(" ", _LATEX_CMD_RE.sub(" ", raw))
    return _WHITESPACE_RE.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class Block:
    """One canonical block, normalised to a single stream.

    index is the position in the source content_list: evidence samples point at it
    so a reader (or the baseline evidence verifier) can re-open the exact block.
    caption_field names the *_caption key the caption came from, for the same
    reason - "which field was read" must be answerable, not guessed.
    """

    index: int
    kind: Stream
    text_plain: str
    raw_chars: int
    digits: int
    caption: str
    caption_digits: int
    level: int | None
    caption_field: str | None


@dataclass(frozen=True, slots=True)
class StreamCensus:
    """Size of one stream, and whether the metrics read it."""

    blocks: int
    chars: int
    digits: int
    raw_chars: int
    caption_chars: int
    caption_digits: int
    dropped_by_metrics: bool


@dataclass(frozen=True, slots=True)
class DocumentModel:
    """Parsed base artifact: ordered blocks plus per-stream aggregation."""

    blocks: tuple[Block, ...]
    source: Path

    def text(self, stream: Stream) -> str:
        """Normalised text of one stream, in document order."""
        return "\n".join(b.text_plain for b in self.blocks if b.kind is stream
                         and b.text_plain)

    def census(self) -> dict[Stream, StreamCensus]:
        """Per-stream size, sorted by stream name for a deterministic product."""
        buckets: dict[Stream, dict[str, int]] = {}
        for block in self.blocks:
            acc = buckets.setdefault(block.kind, {
                "blocks": 0, "chars": 0, "digits": 0, "raw_chars": 0,
                "caption_chars": 0, "caption_digits": 0})
            acc["blocks"] += 1
            acc["chars"] += len(block.text_plain)
            acc["digits"] += block.digits
            acc["raw_chars"] += block.raw_chars
            acc["caption_chars"] += len(block.caption)
            acc["caption_digits"] += block.caption_digits
        return {
            stream: StreamCensus(
                dropped_by_metrics=stream not in _METRIC_STREAMS, **buckets[stream])
            for stream in sorted(buckets, key=lambda s: s.value)
        }


def _field_str(block: dict[str, JsonValue], key: str) -> str:
    value = block.get(key)
    return value if isinstance(value, str) else ""


def _items_str(block: dict[str, JsonValue], key: str) -> str:
    value = block.get(key)
    if not isinstance(value, list):
        return ""
    return " ".join(item for item in value if isinstance(item, str))


def _captions(block: dict[str, JsonValue]) -> tuple[str, str | None]:
    """(joined caption text, first key that carried one).

    Every *_caption key counts: the real corpus uses four different ones
    (image_/table_/chart_/code_caption), so a fixed pair of names would silently
    drop most captions.  The key is kept because evidence has to be able to say
    which field it read.
    """
    parts: list[str] = []
    source: str | None = None
    for key, value in block.items():
        if not key.endswith("_caption"):
            continue
        if isinstance(value, list):
            items = [item for item in value if isinstance(item, str)]
        elif isinstance(value, str):
            items = [value]
        else:
            items = []
        if items and source is None:
            source = key
        parts.extend(items)
    return " ".join(parts), source


def _plain_text(kind: Stream, block: dict[str, JsonValue]) -> tuple[str, str]:
    """(raw, normalised) text of one block, per stream."""
    match kind:
        case Stream.TABLES:
            raw = _field_str(block, "table_body")
            return raw, html_to_text(raw)
        case Stream.EQUATIONS:
            raw = _field_str(block, "text")
            return raw, latex_to_text(raw)
        case Stream.LISTS:
            raw = _items_str(block, "list_items")
            return raw, raw
        case (Stream.PROSE | Stream.FIGURES | Stream.FOOTNOTES
              | Stream.RUNNING_HEADS | Stream.PAGE_NUMBERS | Stream.ASIDES
              | Stream.CODE | Stream.OTHER):
            raw = _field_str(block, "text")
            return raw, raw
        case unreachable:
            assert_never(unreachable)


def _to_block(index: int, raw_block: dict[str, JsonValue]) -> Block:
    kind = stream_of_type(_field_str(raw_block, "type"))
    raw, plain = _plain_text(kind, raw_block)
    caption, caption_field = _captions(raw_block)
    level = raw_block.get("text_level")
    return Block(index=index, kind=kind, text_plain=plain, raw_chars=len(raw),
                 digits=count_digits(plain), caption=caption,
                 caption_digits=count_digits(caption),
                 level=level if isinstance(level, int) else None,
                 caption_field=caption_field)


def _load_blocks(path: Path) -> list[dict[str, JsonValue]]:
    """Read and parse the artifact at the boundary; typed errors only."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DocumentParseError(path, f"unreadable: {exc}") from exc
    # Annotated at the boundary: json.loads returns Any, and every consumer past
    # this line must see JsonValue instead (parse, don't validate).
    parsed: JsonValue
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise DocumentParseError(path, f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise DocumentParseError(path, "expected a JSON list of blocks")
    blocks: list[dict[str, JsonValue]] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise DocumentParseError(path, f"block {index} is not an object")
        blocks.append(item)
    return blocks


def parse_document(path: Path) -> DocumentModel:
    """Parse a content_list.json into a typed document model."""
    blocks = _load_blocks(path)
    return DocumentModel(blocks=tuple(_to_block(index, block)
                                      for index, block in enumerate(blocks)),
                         source=path)
