import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import * as pdfjs from "pdfjs-dist";
import { EventBus, FindState, PDFFindController, PDFLinkService, PDFViewer } from "pdfjs-dist/web/pdf_viewer.mjs";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import { authHeaders, encId } from "../lib/api";
import { useNote } from "../lib/queries";
import { Button, Empty, Spinner } from "../components/ui";
import { Markdown } from "../components/Markdown";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const parts = (id: string) => id.replace(/\.md$/, "").split("/");

export default function Reader() {
  const noteId = useParams()["*"] || "";
  const [sp] = useSearchParams();
  const page = Number(sp.get("page") || "1");
  const q = (sp.get("q") || "").trim();
  const nav = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "pdf" | "text" | "error">("loading");
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    let viewer: PDFViewer | null = null;
    let linkService: PDFLinkService | null = null;
    let findController: PDFFindController | null = null;
    setState("loading");
    // highlight each significant word (array query = OR), not the phrase
    const terms = q.split(/\s+/).filter((w) => w.length > 2);
    const url = "/api/pdf/" + encId(noteId);
    const task = pdfjs.getDocument({ url, httpHeaders: authHeaders() });
    task.promise.then((pdf) => {
      if (cancelled || !containerRef.current || !viewerRef.current) return;
      const target = Math.min(Math.max(page, 1), pdf.numPages);
      const eventBus = new EventBus();
      linkService = new PDFLinkService({ eventBus });
      findController = new PDFFindController({ eventBus, linkService });
      viewer = new PDFViewer({
        container: containerRef.current,
        viewer: viewerRef.current,
        eventBus,
        linkService,
        findController,
      });
      linkService.setViewer(viewer);
      eventBus.on("pagesinit", () => {
        viewer!.currentScaleValue = "page-width";
        viewer!.currentPageNumber = target;
        if (terms.length) {
          eventBus.dispatch("find", {
            source: null, type: "", query: terms,
            caseSensitive: false, entireWord: false,
            highlightAll: true, findPrevious: false, matchDiacritics: false,
          });
        }
      });
      // find scrolls to its first match; once it settles (non-PENDING), put the reader
      // back on the page the search hit so a match elsewhere can't pull it away
      let jumped = false;
      eventBus.on("updatefindcontrolstate", (evt: { state: number }) => {
        if (jumped || evt.state === FindState.PENDING) return;
        jumped = true;
        requestAnimationFrame(() => { if (viewer) viewer.currentPageNumber = target; });
      });
      viewer.setDocument(pdf);
      linkService.setDocument(pdf, null);
      setState("pdf");
    }).catch((e: unknown) => {
      if (cancelled) return;
      const msg = String((e as { message?: string })?.message || e);
      // missing PDF -> fall back to transcribed text; anything else is an error
      if (/404|Missing PDF|Unexpected server response \(404\)/i.test(msg)) setState("text");
      else { setErr(msg); setState("error"); }
    });
    return () => {
      cancelled = true;
      task.destroy();
      // tear down so navigating between notes doesn't stack zombie viewers on the div
      // (setDocument(null) is the documented reset; the .d.ts just types it too strictly)
      const none = null as unknown as pdfjs.PDFDocumentProxy;
      viewer?.setDocument(none);
      linkService?.setDocument(none);
    };
  }, [noteId, page, q]);

  const note = useNote(state === "text" ? noteId : null);
  const title = parts(noteId).slice(-1)[0];
  const crumb = parts(noteId).slice(0, -1).join(" / ");

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-none items-center gap-3 border-b border-line px-5 py-2.5">
        <Button variant="ghost" onClick={() => nav(-1)}>&larr; Back</Button>
        <div className="min-w-0">
          <div className="truncate font-semibold">{title}</div>
          <div className="truncate text-xs text-muted">{crumb}</div>
        </div>
      </div>

      {/* PDF.js viewer: container must be absolutely positioned; kept mounted so refs exist */}
      <div className="relative min-h-0 flex-1" hidden={state !== "pdf" && state !== "loading"}>
        <div ref={containerRef} className="pdfContainer absolute inset-0 overflow-auto bg-[#525659]">
          <div ref={viewerRef} className="pdfViewer" />
        </div>
        {state === "loading" && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-white/80">
            <Spinner /> <span className="ml-2">Loading PDF...</span>
          </div>
        )}
      </div>

      {state === "error" && (
        <div className="min-h-0 flex-1 overflow-auto p-5">
          <Empty>Could not load PDF: {err}</Empty>
        </div>
      )}

      {state === "text" && (
        <div className="min-h-0 flex-1 overflow-auto">
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
        </div>
      )}
    </div>
  );
}
