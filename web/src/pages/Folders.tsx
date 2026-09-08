import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useFolders, useSetFolderPref, useStatus } from "../lib/queries";
import type { SyncFolder } from "../lib/api";
import { Button, Card, Empty, Spinner } from "../components/ui";

interface FNode { name: string; id: string | null; path: string | null; choice: string; children: Record<string, FNode>; }

export default function Folders() {
  const status = useStatus();
  const authed = !!status.data?.authed;
  const configured = !!status.data?.folder_configured;
  const folders = useFolders(authed && configured);
  const setPref = useSetFolderPref();

  const tree = useMemo(() => {
    const root: FNode = { name: "", id: null, path: null, choice: "default", children: {} };
    for (const f of folders.data?.folders ?? []) {
      const segs = f.path.split("/");
      let node = root;
      segs.forEach((seg, i) => {
        node.children[seg] ??= { name: seg, id: null, path: null, choice: "default", children: {} };
        node = node.children[seg];
        if (i === segs.length - 1) { node.id = f.id; node.path = f.path; node.choice = f.choice; }
      });
    }
    return root;
  }, [folders.data]);

  if (!authed) return <Info>Connect Google Drive in <Link className="text-accent" to="/setup">Setup</Link> first.</Info>;
  if (!configured) return <Info>Choose your notes folder in <Link className="text-accent" to="/setup">Setup</Link> first.</Info>;
  if (folders.isLoading) return <Info><Spinner /> Loading folders...</Info>;
  if (folders.error) return <Info>{String(folders.error)}</Info>;

  const set = (f: FNode, choice: string) =>
    f.id && setPref.mutate({ folder_id: f.id, name: f.path || f.name, choice });

  return (
    <div className="mx-auto max-w-3xl px-5 py-4">
      <div className="py-1.5 text-[13px] text-muted">
        Choose what to sync. Ignored folders (and their contents) are skipped. Default follows the parent (ignored at the top).
      </div>
      <Card><FolderNodes node={tree} depth={0} onSet={set} /></Card>
    </div>
  );
}

function Info({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-3xl px-5 py-4"><Empty>{children}</Empty></div>;
}

function FolderNodes({ node, depth, onSet }: { node: FNode; depth: number; onSet: (f: FNode, c: string) => void }) {
  const names = Object.keys(node.children).sort();
  return (
    <>
      {names.map((name) => {
        const c = node.children[name];
        const hasKids = Object.keys(c.children).length > 0;
        return (
          <details key={name} open={depth < 1} className="mb-0.5">
            <summary className="flex cursor-pointer items-center gap-2 rounded-lg px-1.5 py-1.5 hover:bg-accentSoft [&::-webkit-details-marker]:hidden">
              <span className="flex-1 font-medium">{name}</span>
              {c.id && <Seg choice={c.choice} onSet={(v) => onSet(c, v)} />}
            </summary>
            {hasKids && (
              <div className="ml-2.5 border-l border-line pl-4">
                <FolderNodes node={c} depth={depth + 1} onSet={onSet} />
              </div>
            )}
          </details>
        );
      })}
    </>
  );
}

function Seg({ choice, onSet }: { choice: string; onSet: (c: string) => void }) {
  const opts: [string, string][] = [["sync", "Sync"], ["ignore", "Ignore"], ["default", "Default"]];
  return (
    <span className="inline-flex overflow-hidden rounded-lg border border-line" onClick={(e) => e.preventDefault()}>
      {opts.map(([val, label]) => {
        const on = choice === val;
        const cls = on
          ? val === "sync" ? "bg-accent text-white" : val === "ignore" ? "bg-danger text-white" : "bg-accentSoft text-accent"
          : "bg-panel text-muted";
        return (
          <button key={val} onClick={() => onSet(val)} className={`px-2.5 py-1 text-xs ${cls}`}>{label}</button>
        );
      })}
    </span>
  );
}
