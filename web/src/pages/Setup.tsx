import { useState } from "react";
import { Link } from "react-router-dom";
import { useLogin, useSaveSettings, useStartSync, useStatus, useStopSync } from "../lib/queries";
import type { DriveFolder } from "../lib/api";
import { Button, Card, Spinner } from "../components/ui";
import { FolderBrowser } from "../components/FolderBrowser";

export default function Setup() {
  const status = useStatus();
  const login = useLogin();
  const saveSettings = useSaveSettings();
  const startSync = useStartSync();
  const stopSync = useStopSync();
  const [browsing, setBrowsing] = useState(false);
  const [outDir, setOutDir] = useState<string | null>(null);

  const s = status.data;
  if (!s) return <Wrap><Spinner /> Loading...</Wrap>;

  const chooseFolder = (f: DriveFolder) => {
    saveSettings.mutate({ folder_id: f.id, folder_name: f.name });
    setBrowsing(false);
  };

  return (
    <Wrap>
      {/* Google */}
      <Card className="mb-4">
        <div className="mb-1 flex items-center gap-2">
          <b>Google Drive</b>
          {s.authed ? <span className="text-accent">connected</span> : <span className="text-danger">not connected</span>}
        </div>
        {!s.authed && (
          <div className="mt-2">
            <Button onClick={() => login.mutate()} disabled={s.auth_running}>
              {s.auth_running ? <><Spinner /> Waiting for sign-in...</> : "Connect Google Drive"}
            </Button>
            {s.auth_error && <div className="mt-2 text-sm text-danger">{s.auth_error}</div>}
            <div className="mt-2 text-[13px] text-muted">Opens a Google sign-in in your browser.</div>
          </div>
        )}
      </Card>

      {/* Keys */}
      <Card className="mb-4">
        <b>API keys</b>
        <div className="mt-1 text-[13px] text-muted">
          Anthropic: {s.has_anthropic_key ? <span className="text-accent">set</span> : <span className="text-danger">missing (MDNOTES_ANTHROPIC_API_KEY)</span>}
          {"  |  "}
          Voyage: {s.has_voyage_key ? <span className="text-accent">set</span> : <span className="text-danger">missing (MDNOTES_VOYAGE_API_KEY)</span>}
        </div>
      </Card>

      {/* Notes folder */}
      <Card className="mb-4">
        <div className="mb-1 flex items-center gap-2">
          <b>Notes folder</b>
          {s.folder_configured ? <span className="text-accent">{s.folder_name}</span> : <span className="text-danger">not chosen</span>}
        </div>
        <div className="text-[13px] text-muted">Browse to the Drive folder your GoodNotes notebooks are in (it can be nested).</div>
        <div className="mt-2">
          <Button variant="ghost" disabled={!s.authed} onClick={() => setBrowsing((b) => !b)}>
            {browsing ? "Close" : s.folder_configured ? "Change folder" : "Choose folder"}
          </Button>
        </div>
        {browsing && s.authed && <FolderBrowser onSelect={chooseFolder} />}
      </Card>

      {/* Output dir */}
      <Card className="mb-4">
        <b>Output directory</b>
        <div className="mb-1 mt-2 text-[13px] text-muted">Where transcribed notes and PDFs are stored</div>
        <input
          value={outDir ?? s.output_dir}
          onChange={(e) => setOutDir(e.target.value)}
          className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <div className="mt-2">
          <Button variant="ghost" onClick={() => outDir && saveSettings.mutate({ output_dir: outDir })}>Save</Button>
        </div>
        {saveSettings.isError && <div className="mt-2 text-[13px] text-danger">Could not save: {String(saveSettings.error)}</div>}
      </Card>

      {/* Sync */}
      <Card>
        <div className="mb-1 flex items-center gap-2">
          <b>Sync</b>
          {s.sync.running && <span className="text-[13px] text-muted"><Spinner /> running</span>}
        </div>
        <div className="text-[13px] text-muted">
          Pulls the folders marked Sync in <Link className="text-accent" to="/folders">Folders</Link>, transcribes, keeps PDFs, and indexes.
        </div>
        <div className="mt-3 flex gap-2">
          <Button onClick={() => startSync.mutate()} disabled={!s.authed || !s.folder_configured || s.sync.running}>
            Sync now
          </Button>
          {s.sync.running && (
            <Button variant="danger" onClick={() => stopSync.mutate()} disabled={s.sync.stopping}>
              {s.sync.stopping ? "Stopping..." : "Stop"}
            </Button>
          )}
          <Link to="/folders"><Button variant="ghost">Configure folders</Button></Link>
        </div>
        <SyncStatus />
        {startSync.isError && <div className="mt-2 text-[13px] text-danger">Could not start sync: {String(startSync.error)}</div>}
        {stopSync.isError && <div className="mt-2 text-[13px] text-danger">Could not stop sync: {String(stopSync.error)}</div>}
        {!s.folder_configured && <div className="mt-2 text-[13px] text-danger">Choose a notes folder first.</div>}
      </Card>
    </Wrap>
  );
}

function SyncStatus() {
  const { data: s } = useStatus();
  if (!s) return null;
  const { sync } = s;
  if (sync.running) {
    const p = sync.progress;
    const file = p?.file ?? "scanning...";
    const pages = p?.pages ? ` - page ${p.page}/${p.pages}` : "";
    return (
      <div className="mt-2 text-[13px] text-muted">
        {sync.stopping ? "stopping after current page - " : ""}{p?.done ?? 0} done - {file}{pages}
      </div>
    );
  }
  if (sync.error) return <div className="mt-2 text-[13px] text-danger">{sync.error}</div>;
  if (sync.result)
    return (
      <div className="mt-2 text-[13px] text-muted">
        {sync.result.stopped ? "Stopped. " : "Done. "}
        {sync.result.processed.length} synced, {sync.result.skipped.length} skipped, {sync.result.errors.length} errors.
      </div>
    );
  return null;
}

function Wrap({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-3xl px-5 py-4">{children}</div>;
}
