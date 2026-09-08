import { useState } from "react";
import { useDriveChildren } from "../lib/queries";
import type { DriveFolder } from "../lib/api";
import { Button, Spinner } from "./ui";

// browse My Drive folders (any depth) and pick one as the notes folder
export function FolderBrowser({ onSelect }: { onSelect: (f: DriveFolder) => void }) {
  const [stack, setStack] = useState<DriveFolder[]>([{ id: "root", name: "My Drive" }]);
  const current = stack[stack.length - 1];
  const children = useDriveChildren(current.id);

  return (
    <div className="mt-3 rounded-lg border border-line">
      <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-2 text-sm">
        {stack.map((f, i) => (
          <span key={f.id} className="flex items-center gap-1">
            {i > 0 && <span className="text-muted">/</span>}
            <button
              className={i === stack.length - 1 ? "font-semibold" : "text-accent"}
              onClick={() => setStack(stack.slice(0, i + 1))}
            >
              {f.name}
            </button>
          </span>
        ))}
        {current.id !== "root" && (
          <Button variant="ghost" className="ml-auto px-2.5 py-1 text-xs" onClick={() => onSelect(current)}>
            Use this folder
          </Button>
        )}
      </div>
      <div className="max-h-72 overflow-auto p-1">
        {children.isLoading && <div className="p-3 text-sm text-muted"><Spinner /> Loading...</div>}
        {children.error && <div className="p-3 text-sm text-danger">{String(children.error)}</div>}
        {children.data && children.data.folders.length === 0 && (
          <div className="p-3 text-sm text-muted">No subfolders here.</div>
        )}
        {children.data?.folders.map((f) => (
          <div key={f.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-accentSoft">
            <button className="flex-1 text-left" onClick={() => setStack([...stack, f])}>
              📁 {f.name}
            </button>
            <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={() => onSelect(f)}>
              Use this
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
