"""python -m scripts.import_imdb [--refresh] [--max-movies 10000]"""
import argparse
from pathlib import Path
from app.config import Settings
from app.imdb_data import build_database, download_dataset


def main():
    parser = argparse.ArgumentParser(description="IMDb official non-commercial dataset import")
    parser.add_argument("--refresh", action="store_true", help="Download current datasets again")
    parser.add_argument("--max-movies", type=int, default=10000)
    parser.add_argument("--min-votes", type=int, default=1000)
    args = parser.parse_args()
    root = Path(Settings().data_dir)
    print("Source: https://datasets.imdbws.com/ ; personal/non-commercial use only", flush=True)
    paths = {}
    for name in ("title.ratings.tsv.gz", "title.basics.tsv.gz"):
        print(f"Downloading/reusing {name} ...", flush=True)
        paths[name] = download_dataset(name, root / "imdb-downloads", args.refresh)
    print("Cleaning and joining movie metadata + ratings ...", flush=True)
    metadata = build_database(paths["title.basics.tsv.gz"], paths["title.ratings.tsv.gz"], root / "imdb.sqlite3", args.min_votes, args.max_movies)
    print(f"Ready: {metadata['count']:,} movies. Restart the app after updating datasets.")


if __name__ == "__main__":
    main()
