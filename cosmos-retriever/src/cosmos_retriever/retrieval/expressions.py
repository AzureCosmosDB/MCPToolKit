from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# English-only stopword list. Full-text queries are assumed to be English; this
# list only removes English function words so they don't dominate FullTextScore.
# Non-English queries still work — `_TOKEN_RE` is Unicode-aware, so their tokens
# are tokenized/lower-cased/de-duplicated normally; their function words simply
# aren't stripped (mildly noisier, but RRF/FullTextScore tolerate it). The only
# degenerate case is an all-English-stopword query, which can reduce to zero
# terms. Add per-language lists here if broader language support is needed.
_STOPWORDS = frozenset(
    ["a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "did", "do", "does", "doing", "don", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "like", "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "please", "same", "she", "should", "so", "some", "such", "tell", "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "yourself", "yourselves"]
)

_FTS_MAX_TERMS = 30


def tokenize_for_fts(query: str) -> list[str]:

    out: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(query):
        t = raw.lower()
        if t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= _FTS_MAX_TERMS:
            break
    return out


def fts_literal_args(terms: list[str]) -> str:
    

    def esc(t: str) -> str:
        return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'

    return ", ".join(esc(t) for t in terms)
