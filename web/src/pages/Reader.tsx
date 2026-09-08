import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { encId, headOk, pwParam } from "../lib/api";
import { useNote } from "../lib/queries";
import { Button, Empty, Spinner } from "../components/ui";
import { Markdown } from "../components/Markdown";

const parts = (id: string) => id.replace(/\.md$/, "").split("/");

export default function Reader() {
  const params = useParams();
  const noteId = params["*"] || "";
  const [sp] = useSearchParams();
  const page = Number(sp.get("page") || "1");
  const nav = useNavigate();
  const [pdf, setPdf] = useState<"loading" | "yes" | "no">("loading");

  useEffect(() => {
    let alive = true;
    setPdf("loading");
    headOk("/api/pdf/" + encId(noteId) + "?_=1" + pwParam()).then((ok) => {
      if (alive) setPdf(ok ? "yes" : "no");
    });
    return () => { alive = false; };
  }, [noteId]);

  const note = useNote(pdf === "no" ? noteId : null);
  const title = parts(noteId).slice(-1)[0];
  const crumb = parts(noteId).slice(0, -1).join(" / ");

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-none items-center gap-3 border-b border-line px-5 py-2.5">
        <Button variant="ghost" onClick={() => nav(-1)}>&larr; Back</Button>
        <div>
          <div className="font-semibold">{title}</div>
          <div className="text-xs text-muted">{crumb}</div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {pdf === "loading" && <div className="p-5 text-sm text-muted"><Spinner /> Loading...</div>}
        {pdf === "yes" && (
          <iframe
            title="pdf"
            className="h-full w-full border-0"
            src={"/api/pdf/" + encId(noteId) + "?_=1" + pwParam() + "#page=" + page}
          />
        )}
        {pdf === "no" && (
          <div className="mx-auto max-w-3xl px-5 py-4">
            <div className="mb-4 rounded-lg bg-accentSoft px-3 py-2.5 text-[13px] text-accent">
              PDF not on disk yet - showing transcribed text. Sync to view the original page.
            </div>
            {note.isLoading && <div className="text-sm text-muted"><Spinner /> Loading...</div>}
            {note.error && <Empty>{String(note.error)}</Empty>}
            {note.data?.pages.map((pg) => (
              <div key={pg.page_num} className="mt-5 border-t border-line pt-2 first:mt-0 first:border-0">
                <div className="mb-1 text-xs text-muted">page {pg.page_num}/{pg.total || "?"}</div>
                <Markdown text={pg.markdown} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
