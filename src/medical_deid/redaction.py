"""Exact, code-applied replacements for OCR text."""

from dataclasses import dataclass


class RedactionError(ValueError):
    """Raised when a model proposal cannot be proven safe against OCR text."""


@dataclass(frozen=True)
class EntityMatch:
    """One local-model or regex proposal for an exact OCR substring."""

    text: str
    kind: str
    replacement: str | None = None


@dataclass(frozen=True)
class RedactionChange:
    """A verified text replacement used in a reconstructed document."""

    source: str
    replacement: str
    kind: str


_PLACEHOLDER_TYPES = {
    "address": "АДРЕС",
    "birth_date": "ВОЗРАСТ",
    "email": "EMAIL",
    "government_id": "ДОКУМЕНТ",
    "insurance_id": "ПОЛИС",
    "medical_record_id": "НОМЕР_КАРТЫ",
    "other": "ДАННЫЕ",
    "patient_name": "ПАЦИЕНТ",
    "phone": "ТЕЛЕФОН",
    "relative_name": "РОДСТВЕННИК",
    "workplace": "РАБОТОДАТЕЛЬ",
}


def apply_replacements(
    text: str,
    entities: list[EntityMatch],
    *,
    placeholder_counts: dict[str, int] | None = None,
) -> tuple[str, list[RedactionChange]]:
    """Replace only fully verified non-overlapping OCR substrings."""
    spans: list[tuple[int, int, EntityMatch]] = []
    seen = set[tuple[str, str, str | None]]()
    for entity in entities:
        normalized = entity.text.strip()
        key = (normalized, entity.kind, entity.replacement)
        if not normalized or key in seen:
            continue
        seen.add(key)
        if entity.kind not in _PLACEHOLDER_TYPES:
            raise RedactionError(f"Unsupported identifier type: {entity.kind}.")
        occurrences = _find_exact_occurrences(text, normalized)
        if not occurrences:
            raise RedactionError(f"A proposed identifier is not exact OCR text: {normalized!r}.")
        for start in occurrences:
            spans.append((start, start + len(normalized), entity))

    spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))
    _reject_overlaps(spans)

    counts = placeholder_counts if placeholder_counts is not None else {}
    changes: list[RedactionChange] = []
    pieces: list[str] = []
    cursor = 0
    for start, end, entity in spans:
        pieces.append(text[cursor:start])
        if entity.replacement is None:
            counts[entity.kind] = counts.get(entity.kind, 0) + 1
            replacement = f"[{_PLACEHOLDER_TYPES[entity.kind]}_{counts[entity.kind]}]"
        else:
            replacement = entity.replacement
        pieces.append(replacement)
        changes.append(
            RedactionChange(source=text[start:end], replacement=replacement, kind=entity.kind)
        )
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), changes


def _reject_overlaps(spans: list[tuple[int, int, EntityMatch]]) -> None:
    for previous, current in zip(spans, spans[1:], strict=False):
        if current[0] < previous[1]:
            raise RedactionError("Proposed identifier spans are overlapping.")


def _find_exact_occurrences(text: str, candidate: str) -> list[int]:
    """Find candidate occurrences that do not cut through an OCR word or number."""
    occurrences: list[int] = []
    start = text.find(candidate)
    while start >= 0:
        end = start + len(candidate)
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        if not _continues_token(before, candidate[0]) and not _continues_token(
            after, candidate[-1]
        ):
            occurrences.append(start)
        start = text.find(candidate, start + len(candidate))
    return occurrences


def _continues_token(neighbor: str, candidate_edge: str) -> bool:
    return (neighbor.isalpha() and candidate_edge.isalpha()) or (
        neighbor.isdigit() and candidate_edge.isdigit()
    )
