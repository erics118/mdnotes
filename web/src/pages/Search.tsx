import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCourses, useNotes, useSearch } from "../lib/queries";
import type { NoteMeta } from "../lib/api";
import { Badge, Card, Empty, Spinner } from "../components/ui";
import { useDebounced } from "../lib/useDebounced";

const parts = (id: string) => id.replace(/\.md$/, "").split("/");
const crumb = (id: string) => parts(id).slice(0, -1).join(" / ");

export default function Search() {
  const [query, setQuery] = useState("");
  const [course, setCourse] = useState<string | null>(null);
  const debounced = useDebounced(query, 220);
  const nav = useNavigate();

  const courses = useCourses();
  const notes = useNotes();
  const search = useSearch(debounced, course);

  const open = (noteId: string, page: number) => {
    const id = encodeURIComponent(noteId).replace(/%2F/g, "/");
    const qp = debounced.trim() ? `&q=${encodeURIComponent(debounced.trim())}` : "";
    nav(`/note/${id}?page=${page}${qp}`);
  };

  return (
    <div className="mx-auto max-w-3xl px-5 py-4">
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search your notes..."
        autoFocus
        className="w-full rounded-lg border border-line bg-panel px-3.5 py-2.5 text-base outline-none focus:border-accent"
      />
      <div className="mt-2.5 flex gap-2 overflow-x-auto pb-0.5">
        <Chip label="All courses" active={course === null} onClick={() => setCourse(null)} />
        {(courses.data?.courses ?? []).map((c) => (
          <Chip key={c} label={c} active={course === c} onClick={() => setCourse(c)} />
        ))}
      </div>

      <div className="mt-4">
        {query.trim() ? (
          search.isFetching ? (
            <div className="py-2 text-sm text-muted"><Spinner /> Searching...</div>
          ) : !search.data?.results.length ? (
            <Empty>No matches.</Empty>
          ) : (
            <>
              <div className="py-1.5 text-[13px] text-muted">{search.data.results.length} results</div>
              {search.data.results.map((h, i) => (
                <Card key={i} onClick={() => open(h.note_id, h.page_num)} className="mb-2.5 cursor-pointer hover:border-accent">
                  <div className="mb-1 text-xs text-muted">{crumb(h.note_id)}</div>
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{h.title}</span>
                    <Badge>{h.source_type}</Badge>
                    <Badge tone="muted">page {h.page_num}</Badge>
                  </div>
                  <div className="text-sm text-muted break-words">{h.snippet}</div>
                </Card>
              ))}
            </>
          )
        ) : (
          <BrowseTree notes={notes.data?.notes ?? []} course={course} onOpen={open} loading={notes.isLoading} />
        )}
      </div>
    </div>
  );
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`flex-none whitespace-nowrap rounded-full border px-3 py-1 text-[13px] ${
        active ? "border-accent bg-accent text-white" : "border-line bg-panel text-ink"
      }`}
    >
      {label}
    </button>
  );
}

interface TreeNode { dirs: Record<string, TreeNode>; files: (NoteMeta & { name: string })[]; }

function BrowseTree({ notes, course, onOpen, loading }: {
  notes: NoteMeta[]; course: string | null; onOpen: (id: string, page: number) => void; loading: boolean;
}) {
  const root = useMemo(() => {
    const filtered = course ? notes.filter((n) => parts(n.note_id)[0] === course) : notes;
    const r: TreeNode = { dirs: {}, files: [] };
    for (const n of filtered) {
      const p = parts(n.note_id);
      let node = r;
      for (let i = 0; i < p.length - 1; i++) { node.dirs[p[i]] ??= { dirs: {}, files: [] }; node = node.dirs[p[i]]; }
      node.files.push({ ...n, name: p[p.length - 1] });
    }
    return course && r.dirs[course] ? r.dirs[course] : r;
  }, [notes, course]);

  if (loading) return <div className="py-2 text-sm text-muted"><Spinner /> Loading...</div>;
  if (!notes.length) return <Empty>No notes yet. Go to Setup to connect Drive and sync.</Empty>;
  return <Nodes node={root} onOpen={onOpen} depth={0} />;
}

function count(n: TreeNode): number {
  let c = n.files.length;
  for (const k in n.dirs) c += count(n.dirs[k]);
  return c;
}

function Nodes({ node, onOpen, depth }: { node: TreeNode; onOpen: (id: string, page: number) => void; depth: number }) {
  return (
    <>
      {Object.keys(node.dirs).sort().map((name) => (
        <details key={name} open={depth === 0} className="mb-0.5">
          <summary className="flex cursor-pointer items-center gap-2 rounded-lg px-1.5 py-1.5 font-semibold hover:bg-accentSoft [&::-webkit-details-marker]:hidden">
            <span className="text-muted">{name}</span>
            <span className="text-xs font-normal text-muted">{count(node.dirs[name])}</span>
          </summary>
          <div className="ml-2.5 border-l border-line pl-4">
            <Nodes node={node.dirs[name]} onOpen={onOpen} depth={depth + 1} />
          </div>
        </details>
      ))}
      {node.files.sort((a, b) => a.name.localeCompare(b.name)).map((f) => (
        <div
          key={f.note_id}
          onClick={() => onOpen(f.note_id, 1)}
          className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-accentSoft"
        >
          <span className="flex-1">{f.name}</span>
          <Badge>{f.source_type}</Badge>
          <span className="text-xs text-muted">{f.page_count}p</span>
        </div>
      ))}
    </>
  );
}
