"""What customer PII looks like, and what only looks like it.

Every pattern runs on a copy of the text with full-width characters turned
half-width, and with a non-breaking space or a typographic hyphen turned into
the plain one. The mapping is one character to one character, so match offsets
are also offsets into the original text.

The shapes of PII are code: a phone, an email, a national ID and a card number
look the same in every company. Every value a company might change is settings
(settings.json): its own order and product number formats, the card prefixes
that carry no check digit, the words that mark a number as an amount, a
business id or a contact number, and how far around a number to look for them.
"""

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple


class EntityKind(StrEnum):
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    NATIONAL_ID = "NATIONAL_ID"
    CREDIT_CARD = "CREDIT_CARD"


class Finding(NamedTuple):
    kind: EntityKind
    start: int
    end: int


@dataclass(frozen=True)
class Detector:
    kind: EntityKind
    pattern: re.Pattern[str]
    is_valid: Callable[[str], bool]
    vetoes: tuple[Callable[[str, int, int], bool], ...] = ()


def _any_of(words: Iterable[str]) -> str:
    return "(?:" + "|".join(re.escape(word) for word in words) + ")"


_SETTINGS = json.loads((Path(__file__).parent / "settings.json").read_text(encoding="utf-8"))

_HALFWIDTH = {code_point: code_point - 0xFEE0 for code_point in range(0xFF01, 0xFF5F)} | {
    0x3000: 0x20,  # ideographic space
    0x00A0: 0x20,  # non-breaking space
    0x2010: 0x2D,  # hyphen
    0x2011: 0x2D,  # non-breaking hyphen
    0x2013: 0x2D,  # en dash
}

# A match may not touch an ASCII letter or digit on either side, so a card or an
# ID never comes out of the middle of an order number or a tracking code. A
# phone is the exception on its right side only: people write it straight
# before a word, so only another digit there stops it.
_START = r"(?<![0-9A-Za-z])"
_END = r"(?![0-9A-Za-z])"

_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", re.ASCII)
_NATIONAL_ID = re.compile(_START + r"[A-Za-z][1289]\d{8}" + _END, re.ASCII)
# A 19-digit card in groups is its own pattern, tried first. As an optional tail of the 16-digit form it would also
# swallow three digits that only follow a card, such as its security code, and the 19 digits would then fail the check.
_CREDIT_CARD_19_GROUPED = re.compile(
    _START + r"\d{4}(?P<separator>[ -])\d{4}(?P=separator)\d{4}(?P=separator)\d{4}(?P=separator)\d{3}" + _END, re.ASCII
)
_CREDIT_CARD = re.compile(
    _START
    + r"(?:\d{13,19}"
    + r"|\d{4}(?P<separator>[ -])\d{4}(?P=separator)\d{4}(?P=separator)\d{2,4}"
    + r"|\d{4}(?P<separator_4_6>[ -])\d{6}(?P=separator_4_6)\d{4,5})"
    + _END,
    re.ASCII,
)
_PHONE = re.compile(_START + r"(?:\+?886[ -]?|0)9\d{2}[ -]?\d{3}[ -]?\d{3}(?!\d)", re.ASCII)

# The company's own number formats, from settings.json. They are never PII.
DEFAULT_PROTECTED: tuple[re.Pattern[str], ...] = tuple(re.compile(pattern, re.ASCII) for pattern in _SETTINGS["protected_patterns"])


def _luhn_ok(value: str) -> bool:
    total = 0
    digits_from_the_right = (int(character) for character in reversed(value) if character.isdigit())
    for position, digit in enumerate(digits_from_the_right):
        if position % 2:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0


def _card_ok(value: str) -> bool:
    # Some card ranges, such as UnionPay's, carry no Luhn check digit. The settings list their prefixes.
    return value.startswith(tuple(_SETTINGS["card_prefixes_without_check_digit"])) or _luhn_ok(value)


# Letter codes run 10 to 35 in this order. I and O were added last.
_ID_LETTERS = "ABCDEFGHJKLMNPQRSTUVXYWZIO"
_ID_WEIGHTS = (1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1)


def _national_id_ok(value: str) -> bool:
    code = _ID_LETTERS.index(value[0].upper()) + 10
    digits = (code // 10, code % 10, *map(int, value[1:]))
    return sum(digit * weight for digit, weight in zip(digits, _ID_WEIGHTS, strict=False)) % 10 == 0


_AMOUNT_BEFORE = re.compile(_any_of(_SETTINGS["amount_markers_before"]) + r"[ :]*$")
# The marker must end there. A currency unit right after the number marks an amount; the same character starting a
# longer word, such as a bank's name or a holiday, does not.
_AMOUNT_AFTER = re.compile(r" *" + _any_of(_SETTINGS["amount_markers_after"]) + r"(?!\w)")


def _beside_amount(text: str, start: int, end: int) -> bool:
    return bool(
        _AMOUNT_BEFORE.search(text, max(0, start - _SETTINGS["amount_marker_window"]), start) or _AMOUNT_AFTER.match(text, end)
    )


# A label ends at a digit, a line break or one of the punctuation marks the settings list.
_LABEL_BREAK = re.compile(r"[0-9\n" + re.escape(_SETTINGS["label_breaks"]) + "]")
_BUSINESS_ID_LABEL = re.compile(_any_of(_SETTINGS["business_id_labels"]) + r"[ :#]*$")
_CONTACT_LABEL = re.compile(_any_of(_SETTINGS["contact_labels"]), re.IGNORECASE)


def _labeled_as_business_id(text: str, start: int, end: int) -> bool:
    if not re.fullmatch(r"09\d{8}", text[start:end]):
        return False
    label = _LABEL_BREAK.split(text[max(0, start - _SETTINGS["label_window"]) : start])[-1]
    return bool(_BUSINESS_ID_LABEL.search(label)) and not _CONTACT_LABEL.search(label)


# Order is priority. An email can hold a phone-shaped local part, so it claims
# its span first.
DETECTORS: tuple[Detector, ...] = (
    Detector(EntityKind.EMAIL, _EMAIL, lambda value: True),
    Detector(EntityKind.NATIONAL_ID, _NATIONAL_ID, _national_id_ok),
    Detector(EntityKind.CREDIT_CARD, _CREDIT_CARD_19_GROUPED, _card_ok, (_beside_amount,)),
    Detector(EntityKind.CREDIT_CARD, _CREDIT_CARD, _card_ok, (_beside_amount,)),
    Detector(EntityKind.PHONE, _PHONE, lambda value: True, (_labeled_as_business_id,)),
)


def find_pii(text: str, protected: Sequence[re.Pattern[str]] = DEFAULT_PROTECTED) -> list[Finding]:
    text = text.translate(_HALFWIDTH)
    # One flag per character keeps the overlap checks linear when a pasted
    # customer list holds thousands of matches.
    protected_flags = bytearray(len(text))
    for pattern in protected:
        for match in pattern.finditer(text):
            protected_flags[match.start() : match.end()] = b"\x01" * (match.end() - match.start())
    taken = bytearray(len(text))
    findings = []
    for detector in DETECTORS:
        for match in detector.pattern.finditer(text):
            start, end = match.span()
            # A business number hides what lies wholly inside it. What only overlaps it, such as an email whose
            # local part looks like an order number, is still PII.
            if 1 in taken[start:end] or 0 not in protected_flags[start:end]:
                continue
            if not detector.is_valid(match.group()) or any(veto(text, start, end) for veto in detector.vetoes):
                continue
            taken[start:end] = b"\x01" * (end - start)
            findings.append(Finding(detector.kind, start, end))
    return sorted(findings, key=lambda finding: finding.start)
