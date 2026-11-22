from pathlib import Path
import re
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .database import replace_chunks, get_chunks

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "data" / "knowledge"


def read_document(path: Path):
    if path.suffix.lower() == '.pdf':
        try:
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    if path.suffix.lower() in {'.txt', '.md'}:
        return path.read_text(encoding='utf-8', errors='ignore')
    return ""


def chunk_text(text, size=900, overlap=140):
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end == len(text): break
        start = max(start + 1, end - overlap)
    return chunks


def ingest_knowledge():
    KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    records = []
    for path in KNOWLEDGE.rglob('*'):
        if path.is_file() and path.suffix.lower() in {'.pdf', '.txt', '.md'}:
            text = read_document(path)
            for idx, chunk in enumerate(chunk_text(text)):
                records.append((path.name, str(path.relative_to(ROOT)), chunk, idx, 'local-ingest'))
    replace_chunks(records)
    return {"documents": len({r[0] for r in records}), "chunks": len(records)}


def retrieve(query, limit=5):
    chunks = get_chunks()
    if not chunks:
        return []
    docs = [x['chunk_text'] for x in chunks]
    tokens = [re.findall(r"[a-z0-9]+", d.lower()) for d in docs]
    qtokens = re.findall(r"[a-z0-9]+", query.lower())
    # Lightweight BM25 scoring, implemented locally to keep the starter dependency footprint small.
    import math
    n_docs = len(tokens)
    avg_len = sum(len(t) for t in tokens) / max(n_docs, 1)
    doc_freq = {}
    for term in set(qtokens):
        doc_freq[term] = sum(1 for doc in tokens if term in set(doc))
    b_scores = []
    k1, b = 1.5, 0.75
    for doc in tokens:
        score = 0.0
        freq = {}
        for term in doc: freq[term] = freq.get(term, 0) + 1
        for term in qtokens:
            tf = freq.get(term, 0)
            if not tf: continue
            idf = math.log(1 + (n_docs - doc_freq.get(term, 0) + 0.5) / (doc_freq.get(term, 0) + 0.5))
            denom = tf + k1 * (1 - b + b * len(doc) / max(avg_len, 1))
            score += idf * tf * (k1 + 1) / denom
        b_scores.append(score)
    try:
        vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1,2))
        matrix = vectorizer.fit_transform(docs + [query])
        v_scores = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    except Exception:
        v_scores = [0.0] * len(chunks)
    # Normalize each retrieval score before a simple reciprocal-rank-style blend.
    def ranks(scores):
        order = sorted(range(len(scores)), key=lambda i: float(scores[i]), reverse=True)
        out = [0] * len(scores)
        for rank, i in enumerate(order, 1): out[i] = 1.0 / (60 + rank)
        return out
    br, vr = ranks(b_scores), ranks(v_scores)
    blended = [br[i] + vr[i] for i in range(len(chunks))]
    order = sorted(range(len(chunks)), key=lambda i: blended[i], reverse=True)[:limit]
    return [{"source": chunks[i]['source_name'], "path": chunks[i]['source_path'], "chunk_id": chunks[i]['id'], "text": docs[i], "score": round(float(blended[i]), 5)} for i in order]
