"""Official IMDb non-commercial TSV import; never scrapes imdb.com pages."""
import csv
from contextlib import closing
from datetime import datetime, timezone
import gzip
import heapq
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from uuid import uuid4

import httpx

DATASET_URL = "https://datasets.imdbws.com/"
LICENSE_URL = "https://developer.imdb.com/non-commercial-datasets/"
GENRES = {"Action": "액션", "Adventure": "모험", "Animation": "애니메이션", "Biography": "전기", "Comedy": "코미디", "Crime": "범죄", "Documentary": "다큐멘터리", "Drama": "드라마", "Family": "가족", "Fantasy": "판타지", "Film-Noir": "느와르", "History": "역사", "Horror": "공포", "Music": "음악", "Musical": "뮤지컬", "Mystery": "미스터리", "Romance": "로맨스", "Sci-Fi": "SF", "Sport": "스포츠", "Thriller": "스릴러", "War": "전쟁", "Western": "서부"}


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def optional_int(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def download_dataset(name, directory, refresh=False):
    if name not in {"title.basics.tsv.gz", "title.ratings.tsv.gz"}:
        raise ValueError("Unsupported dataset")
    target = Path(directory) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not refresh:
        return target
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with httpx.stream("GET", DATASET_URL + name, timeout=120, follow_redirects=True) as response:
            response.raise_for_status()
            with partial.open("wb") as output:
                for block in response.iter_bytes(1024 * 1024):
                    output.write(block)
        with gzip.open(partial, "rt", encoding="utf-8") as check:
            if "tconst" not in check.readline():
                raise ValueError("Unexpected IMDb dataset header")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def build_database(basics, ratings, destination, min_votes=1000, max_movies=10000):
    """Bounded-memory streaming import. Publish DB atomically after validation."""
    if min_votes < 0 or max_movies < 1:
        raise ValueError("Invalid import limits")
    scores = {}
    with gzip.open(ratings, "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            votes = optional_int(row.get("numVotes"))
            if votes is not None and votes >= min_votes:
                try:
                    score = float(row["averageRating"])
                except (ValueError, KeyError):
                    continue
                if 0 <= score <= 10:
                    scores[row["tconst"]] = (score, votes)
    selected = []
    with gzip.open(basics, "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            imdb_id = row.get("tconst", "")
            if row.get("titleType") != "movie" or row.get("isAdult") != "0" or imdb_id not in scores or not re.fullmatch(r"tt\d+", imdb_id):
                continue
            score, votes = scores[imdb_id]
            record = dict(id=imdb_id, title=row["primaryTitle"], original=row["originalTitle"], year=optional_int(row["startYear"]), runtime=optional_int(row["runtimeMinutes"]), genres=[] if row["genres"] == "\\N" else row["genres"].split(","), rating=score, votes=votes)
            entry = (votes, imdb_id, record)
            if len(selected) < max_movies:
                heapq.heappush(selected, entry)
            elif entry[:2] > selected[0][:2]:
                heapq.heapreplace(selected, entry)
    if not selected:
        raise ValueError("No eligible IMDb movies; previous database was preserved")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
    try:
        with closing(sqlite3.connect(staging)) as conn:
            conn.execute("CREATE TABLE movies (id TEXT PRIMARY KEY, title TEXT, original TEXT, year INTEGER, runtime INTEGER, genres TEXT, rating REAL, votes INTEGER, search_text TEXT)")
            conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            conn.executemany("INSERT INTO movies VALUES(?,?,?,?,?,?,?,?,?)", [(m["id"], m["title"], m["original"], m["year"], m["runtime"], json.dumps(m["genres"]), m["rating"], m["votes"], normalize(m["title"] + " " + m["original"])) for _, _, m in selected])
            conn.execute("CREATE INDEX by_votes ON movies(votes DESC)")
            metadata = {"imported_at": datetime.now(timezone.utc).isoformat(), "count": len(selected), "min_votes": min_votes, "max_movies": max_movies, "source": DATASET_URL, "license": LICENSE_URL}
            conn.executemany("INSERT INTO metadata VALUES(?,?)", [(k, str(v)) for k, v in metadata.items()])
            conn.commit()
        staging.replace(destination)
    finally:
        staging.unlink(missing_ok=True)
    return metadata


class IMDbStore:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "imdb.sqlite3"

    def connect(self):
        if not self.path.exists():
            raise FileNotFoundError("IMDb 데이터가 없습니다. python -m scripts.import_imdb 를 먼저 실행하세요.")
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def status(self):
        if not self.path.exists():
            return {"ready": False, "count": 0}
        with closing(self.connect()) as conn:
            metadata = dict(conn.execute("SELECT key,value FROM metadata").fetchall())
        return {"ready": True, **metadata, "count": int(metadata["count"])}

    @staticmethod
    def movie(row):
        item = dict(row)
        item.pop("search_text", None)
        original_genres = json.loads(item["genres"])
        item["genres"] = [GENRES.get(g, g) for g in original_genres]
        item["source"] = "IMDb non-commercial datasets"
        item["source_url"] = f"https://www.imdb.com/title/{item['id']}/"
        item["synopsis"] = "IMDb 무료 데이터셋에는 줄거리가 포함되어 있지 않습니다."
        item["note"] = f"IMDb 메타데이터: {item['title']} ({item['year'] or '연도 미상'}), 장르 {', '.join(item['genres'])}, 상영 시간 {item['runtime'] or '미상'}분, 평점 {item['rating']}/10, 투표 {item['votes']:,}개."
        return item

    def search(self, query, preferences, limit=60):
        conditions, args = [], []
        if query.strip():
            # Literal substring search; '%' and '_' are never treated as user wildcards.
            escaped = normalize(query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("search_text LIKE ? ESCAPE '\\'")
            args.append("%" + escaped + "%")
        if preferences.max_minutes:
            conditions.append("runtime IS NOT NULL AND runtime <= ?")
            args.append(preferences.max_minutes)
        reverse = {v: k for k, v in GENRES.items()}
        if preferences.genres:
            conditions.append("(" + " OR ".join("genres LIKE ?" for _ in preferences.genres) + ")")
            args.extend('%"' + reverse.get(g, g) + '"%' for g in preferences.genres)
        for genre in preferences.avoid:
            conditions.append("genres NOT LIKE ?")
            args.append('%"' + reverse.get(genre, genre) + '"%')
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with closing(self.connect()) as conn:
            rows = conn.execute("SELECT * FROM movies" + where + " ORDER BY votes DESC LIMIT ?", [*args, max(1, min(limit, 200))]).fetchall()
        return [self.movie(row) for row in rows]

    def get(self, movie_id):
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
        return self.movie(row) if row else None
