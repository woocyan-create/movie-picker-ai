import gzip
from pathlib import Path
import pytest
from app.imdb_data import build_database


@pytest.fixture
def imdb_directory(tmp_path):
    basics = tmp_path / "basics.gz"
    ratings = tmp_path / "ratings.gz"
    # Synthetic metadata to test the pipeline without network or licensed downloads.
    rows = [
        ("tt0000001", "Quiet Fields", "2018", "90", "Drama,Family", "0", "movie"),
        ("tt0000002", "Comedy Road", "2014", "100", "Comedy,Drama", "0", "movie"),
        ("tt0000003", "Space Puzzle", "2010", "148", "Action,Sci-Fi,Thriller", "0", "movie"),
        ("tt0000004", "Unknown Runtime", "2020", "\\N", "Comedy", "0", "movie"),
        ("tt0000005", "Adult Excluded", "2020", "80", "Drama", "1", "movie"),
        ("tt0000006", "Series Excluded", "2020", "30", "Comedy", "0", "tvSeries"),
        ("tt0000007", "Horror House", "2019", "95", "Horror,Thriller", "0", "movie"),
    ]
    with gzip.open(basics, "wt", encoding="utf-8") as out:
        out.write("tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear\truntimeMinutes\tgenres\n")
        for mid, title, year, runtime, genres, adult, kind in rows:
            out.write(f"{mid}\t{kind}\t{title}\t{title}\t{adult}\t{year}\t\\N\t{runtime}\t{genres}\n")
    with gzip.open(ratings, "wt", encoding="utf-8") as out:
        out.write("tconst\taverageRating\tnumVotes\n")
        for index, (mid, *_) in enumerate(rows):
            out.write(f"{mid}\t7.5\t{10000-index*100}\n")
    build_database(basics, ratings, tmp_path / "imdb.sqlite3", min_votes=100, max_movies=100)
    return tmp_path
