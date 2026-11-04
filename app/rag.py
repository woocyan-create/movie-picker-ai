"""Source-labelled chunks + persistent Chroma retrieval; embeddings are explicit."""
import hashlib
import math
import re


def chunk_document(movie, chunk_size=420, overlap=60):
    # Only trusted metadata and explicitly labelled editorial notes are indexed.
    fields = [f"Title: {movie['title']}. Original title: {movie.get('original', movie['title'])}.",
              f"Year: {movie.get('year')}. Runtime: {movie.get('runtime')} minutes. Genres: {', '.join(movie['genres'])}.",
              f"IMDb rating: {movie.get('rating')}. Votes: {movie.get('votes')}." if movie.get('source_url') else "Sample editorial catalog.",
              movie["note"], f"Source: {movie['source']}. URL: {movie.get('source_url') or 'local catalog'}."]
    text = re.sub(r"\s+", " ", " ".join(fields)).strip()
    if chunk_size <= overlap or overlap < 0:
        raise ValueError("Invalid chunk settings")
    chunks = []
    for position in range(0, len(text), chunk_size - overlap):
        part = text[position:position + chunk_size]
        digest = hashlib.sha256(part.encode()).hexdigest()[:16]
        chunks.append({"id": f"{movie['id']}:{position}:{digest}", "movie_id": movie["id"], "text": part, "source": movie["source"], "source_url": movie.get("source_url") or ""})
        if position + chunk_size >= len(text):
            break
    return chunks


def demo_embedding(text, dimensions=256):
    """Deterministic lexical hash, NOT a learned semantic embedding."""
    vector = [0.] * dimensions
    tokens = re.findall(r"[\w가-힣]+", text.casefold())
    for token in tokens:
        for fragment in [token, *[token[i:i+2] for i in range(len(token)-1)]]:
            digest = hashlib.sha256(fragment.encode()).digest()
            vector[int.from_bytes(digest[:4], 'little') % dimensions] += 1 if digest[4] % 2 else -1
    norm = math.sqrt(sum(v*v for v in vector)) or 1
    return [v/norm for v in vector]


class MovieRAG:
    def __init__(self, root, client=None, model="text-embedding-3-small", provider="openai"):
        import chromadb
        self.client = client
        self.model = model
        signature = hashlib.sha256((provider + ":" + model if client else "demo-lexical-v1").encode()).hexdigest()[:12]
        store = chromadb.PersistentClient(path=str(root / "chroma"))
        self.collection = store.get_or_create_collection("imdb-chunks-" + signature, embedding_function=None, metadata={"hnsw:space": "cosine"})

    def embed(self, texts):
        if self.client:
            response = self.client.embeddings.create(model=self.model, input=texts)
            return [row.embedding for row in sorted(response.data, key=lambda r: r.index)]
        return [demo_embedding(text) for text in texts]

    def retrieve(self, movies, query, limit=12):
        if not movies:
            return []
        chunks = [chunk for movie in movies for chunk in chunk_document(movie)]
        ids = [chunk["id"] for chunk in chunks]
        existing = set(self.collection.get(ids=ids, include=[])["ids"])
        missing = [chunk for chunk in chunks if chunk["id"] not in existing]
        for start in range(0, len(missing), 64):
            batch = missing[start:start+64]
            self.collection.upsert(ids=[c["id"] for c in batch], documents=[c["text"] for c in batch], embeddings=self.embed([c["text"] for c in batch]), metadatas=[{**{k: c[k] for k in ("movie_id", "source", "source_url")}, "chunk_id": c["id"]} for c in batch])
        # Isolate each query's exact chunks: an old movie version or another request's
        # documents must never leak into the current filtered candidate pool.
        result = self.collection.query(query_embeddings=self.embed([query]), n_results=min(limit, len(chunks)), where={"chunk_id": {"$in": ids}}, include=["documents", "metadatas", "distances"])
        allowed = set(ids)
        return [{"id": cid, "movie_id": meta["movie_id"], "text": text, "source": meta["source"], "source_url": meta["source_url"]} for cid, text, meta in zip(result["ids"][0], result["documents"][0], result["metadatas"][0]) if cid in allowed]
