import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

from mdnotes.embed import EMBED_DIM, EMBED_MODEL, embed_documents
from mdnotes.notefmt import HANDWRITTEN

DEFAULT_INDEX = Path.home() / ".cache" / "mdnotes" / "index.db"

_WORD = re.compile(r"\w+")


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode()).hexdigest()


def _embed_text(page: dict) -> str:
    """Text used for embedding and FTS: the markdown plus the hidden search context."""
    ctx = page.get("search_context") or ""
    return f"{page['markdown']}\n\n{ctx}".strip() if ctx else page["markdown"]


def _fts_query(text: str) -> str:
    """Turn free text into a lenient FTS5 MATCH expression (any term, quoted)."""
    words = _WORD.findall(text)
    return " OR ".join(f'"{w}"' for w in words)


class NoteIndex:
    """SQLite index over note/textbook pages: FTS5 (BM25) + sqlite-vec (KNN)."""

    def __init__(self, path: Path = DEFAULT_INDEX, embed_client=None):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._embed_client = embed_client
        self.db = sqlite3.connect(str(self._path))
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self._migrate()

    def _migrate(self) -> None:
        self.db.executescript(f"""
        create table if not exists notes(
            note_id text primary key,
            title text not null,
            path text,
            source_type text not null default '{HANDWRITTEN}',
            drive_mtime text,
            synced_at text
        );
        create table if not exists pages(
            page_id integer primary key autoincrement,
            note_id text not null,
            page_num integer not null,
            total integer,
            content_hash text not null,
            markdown text not null
        );
        create index if not exists pages_note on pages(note_id);
        create virtual table if not exists pages_fts using fts5(markdown, title);
        create table if not exists embeddings(
            content_hash text primary key,
            model text not null,
            dim integer not null,
            vector blob not null
        );
        create virtual table if not exists vec_pages using vec0(
            page_id integer primary key,
            embedding float[{EMBED_DIM}]
        );
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def upsert_note(
        self,
        note_id: str,
        title: str,
        pages: list[dict],
        path: str | None = None,
        source_type: str = HANDWRITTEN,
        drive_mtime: str | None = None,
    ) -> None:
        """Replace all pages for a note. pages: [{page_num, total, markdown}, ...]."""
        db = self.db
        now = datetime.now(timezone.utc).isoformat()

        # Embed any missing pages BEFORE touching the DB, so a Voyage failure can't
        # leave a half-deleted note behind. Cache lookup is keyed by (hash, model, dim)
        # so a model/dim change re-embeds instead of reusing an incompatible vector.
        blobs: dict[str, bytes] = {}
        missing_text: list[str] = []
        missing_hash: list[str] = []
        for p in pages:
            embed_text = _embed_text(p)
            ch = content_hash(embed_text)
            if ch in blobs:
                continue
            row = db.execute(
                "select vector from embeddings where content_hash=? and model=? and dim=?",
                (ch, EMBED_MODEL, EMBED_DIM),
            ).fetchone()
            if row is not None:
                blobs[ch] = row[0]
            else:
                missing_text.append(embed_text)
                missing_hash.append(ch)
        if missing_text:
            vectors = embed_documents(missing_text, client=self._embed_client)
            if len(vectors) != len(missing_text):
                raise RuntimeError("embedding count mismatch from Voyage")
            for ch, vec in zip(missing_hash, vectors):
                blobs[ch] = sqlite_vec.serialize_float32(vec)

        # All embeddings ready: now do the replacement as one atomic transaction.
        try:
            self._delete_pages(note_id)
            db.execute(
                "insert into notes(note_id,title,path,source_type,drive_mtime,synced_at) "
                "values(?,?,?,?,?,?) on conflict(note_id) do update set "
                "title=excluded.title, path=excluded.path, source_type=excluded.source_type, "
                "drive_mtime=excluded.drive_mtime, synced_at=excluded.synced_at",
                (note_id, title, path, source_type, drive_mtime, now),
            )
            for p in pages:
                embed_text = _embed_text(p)
                ch = content_hash(embed_text)
                cur = db.execute(
                    "insert into pages(note_id,page_num,total,content_hash,markdown) values(?,?,?,?,?)",
                    (note_id, p["page_num"], p.get("total"), ch, p["markdown"]),
                )
                pid = cur.lastrowid
                # index the hidden search context alongside the markdown so its
                # plain-language terms are searchable (FTS) and embedded (vec)
                db.execute(
                    "insert into pages_fts(rowid, markdown, title) values(?,?,?)",
                    (pid, embed_text, title),
                )
                db.execute(
                    "insert or replace into embeddings(content_hash,model,dim,vector) values(?,?,?,?)",
                    (ch, EMBED_MODEL, EMBED_DIM, blobs[ch]),
                )
                db.execute("insert into vec_pages(page_id, embedding) values(?,?)", (pid, blobs[ch]))
            db.commit()
        except BaseException:
            db.rollback()
            raise

    def _delete_pages(self, note_id: str) -> None:
        db = self.db
        for (pid,) in db.execute("select page_id from pages where note_id=?", (note_id,)).fetchall():
            db.execute("delete from pages_fts where rowid=?", (pid,))
            db.execute("delete from vec_pages where page_id=?", (pid,))
        db.execute("delete from pages where note_id=?", (note_id,))

    def remove_note(self, note_id: str) -> None:
        """Delete a note and its pages from the index (embeddings cache is left intact)."""
        self._delete_pages(note_id)
        self.db.execute("delete from notes where note_id=?", (note_id,))
        self.db.commit()

    def fts_candidates(self, query: str, limit: int = 40) -> list[int]:
        """Return page_ids ranked by BM25 for the query (best first)."""
        match = _fts_query(query)
        if not match:
            return []
        rows = self.db.execute(
            "select rowid from pages_fts where pages_fts match ? order by bm25(pages_fts) limit ?",
            (match, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def vec_candidates(self, query_vec: list[float], limit: int = 40) -> list[int]:
        """Return page_ids ranked by vector distance (nearest first)."""
        blob = sqlite_vec.serialize_float32(query_vec)
        rows = self.db.execute(
            "select page_id from vec_pages where embedding match ? and k = ? order by distance",
            (blob, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def get_page(self, page_id: int) -> dict | None:
        row = self.db.execute(
            "select p.page_id, p.note_id, p.page_num, p.total, p.markdown, "
            "n.title, n.path, n.source_type "
            "from pages p join notes n on n.note_id = p.note_id where p.page_id = ?",
            (page_id,),
        ).fetchone()
        if row is None:
            return None
        keys = ["page_id", "note_id", "page_num", "total", "markdown", "title", "path", "source_type"]
        return dict(zip(keys, row))

    def list_notes(self) -> list[dict]:
        rows = self.db.execute(
            "select note_id, title, source_type, path, "
            "(select count(*) from pages where pages.note_id = notes.note_id) as page_count "
            "from notes order by title"
        ).fetchall()
        keys = ["note_id", "title", "source_type", "path", "page_count"]
        return [dict(zip(keys, r)) for r in rows]

    def page_ids_under(self, course: str) -> set[int]:
        """page_ids whose note_id is inside the given top-level course folder."""
        # escape LIKE metacharacters so a course named 'CS_1' or 'A%B' matches literally
        esc = course.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.db.execute(
            "select page_id from pages where note_id like ? escape '\\'", (esc + "/%",)
        ).fetchall()
        return {r[0] for r in rows}

    def note_path(self, note_id: str) -> str | None:
        row = self.db.execute("select path from notes where note_id=?", (note_id,)).fetchone()
        return row[0] if row else None

    def courses(self) -> list[str]:
        """Distinct top-level folder names across all notes."""
        seen = set()
        for (nid,) in self.db.execute("select note_id from notes").fetchall():
            if "/" in nid:
                seen.add(nid.split("/", 1)[0])
        return sorted(seen)

    def note_markdown(self, note_id: str) -> list[dict]:
        rows = self.db.execute(
            "select page_num, total, markdown from pages where note_id=? order by page_num",
            (note_id,),
        ).fetchall()
        return [dict(zip(["page_num", "total", "markdown"], r)) for r in rows]
