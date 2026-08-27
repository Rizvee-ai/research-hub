"""
Splitting text into passages.

A passage never spans two pages. That keeps page attribution
unambiguous — a chunk drawn from pages 8 and 9 cannot honestly
be cited as either.

Passages overlap slightly so a sentence sitting on a boundary is
not lost from both sides.
"""

from config import CHUNK_WORDS, CHUNK_OVERLAP, MIN_WORDS_PER_PAGE


def split_page(text, size=CHUNK_WORDS, overlap=CHUNK_OVERLAP):
    words = text.split()
    if len(words) < MIN_WORDS_PER_PAGE:
        return []                       # near-empty page, nothing worth keeping

    if len(words) <= size:
        return [" ".join(words)]

    step = size - overlap
    out = []
    for i in range(0, len(words), step):
        piece = words[i:i + size]
        if len(piece) < MIN_WORDS_PER_PAGE and out:
            break                       # trailing scrap, already covered
        out.append(" ".join(piece))
    return out


def split_document(pages):
    """
    pages is [(page_number, text), ...]
    Returns [{page, seq, text}, ...] in document order.
    """
    chunks = []
    seq = 0
    for page_no, text in pages:
        for piece in split_page(text):
            chunks.append({"page": page_no, "seq": seq, "text": piece})
            seq += 1
    return chunks
