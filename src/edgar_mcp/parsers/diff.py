from __future__ import annotations

from difflib import SequenceMatcher

from ..models import Modification, Paragraph


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _pair_similar(
    old: list[str], new: list[str], threshold: float = 0.4
) -> list[tuple[str | None, str | None, float]]:
    """Pair old/new paragraphs by similarity. Unpaired items get None partner."""
    result: list[tuple[str | None, str | None, float]] = []
    used_new: set[int] = set()

    for o in old:
        best_sim = 0.0
        best_j = -1
        for j, n in enumerate(new):
            if j in used_new:
                continue
            sim = SequenceMatcher(None, o, n).ratio()
            if sim > best_sim:
                best_sim = sim
                best_j = j

        if best_sim >= threshold and best_j >= 0:
            used_new.add(best_j)
            result.append((o, new[best_j], best_sim))
        else:
            result.append((o, None, 0.0))

    for j, n in enumerate(new):
        if j not in used_new:
            result.append((None, n, 0.0))

    return result


def diff_sections(
    text_current: str, text_previous: str
) -> tuple[list[Paragraph], list[Paragraph], list[Modification]]:
    """Diff two section texts at the paragraph level.

    Args:
        text_current: The newer section text.
        text_previous: The older section text.

    Returns:
        (added, removed, modified) paragraphs.
    """
    paras_cur = _split_paragraphs(text_current)
    paras_prev = _split_paragraphs(text_previous)

    matcher = SequenceMatcher(None, paras_prev, paras_cur)

    added: list[Paragraph] = []
    removed: list[Paragraph] = []
    modified: list[Modification] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        elif tag == "delete":
            removed.extend(Paragraph(text=p) for p in paras_prev[i1:i2])
        elif tag == "insert":
            added.extend(Paragraph(text=p) for p in paras_cur[j1:j2])
        elif tag == "replace":
            for old_p, new_p, sim in _pair_similar(
                paras_prev[i1:i2], paras_cur[j1:j2]
            ):
                if old_p is None and new_p is not None:
                    added.append(Paragraph(text=new_p))
                elif new_p is None and old_p is not None:
                    removed.append(Paragraph(text=old_p))
                elif old_p is not None and new_p is not None:
                    modified.append(
                        Modification(
                            before=old_p, after=new_p, similarity=sim
                        )
                    )

    return added, removed, modified
