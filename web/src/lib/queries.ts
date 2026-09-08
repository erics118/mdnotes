import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import type { DriveFolder, Hit, NoteMeta, NotePage, Status, SyncFolder } from "./api";

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => api.get<Status>("/api/status"),
    refetchInterval: (q) => {
      const s = q.state.data;
      return s && (s.auth_running || s.sync.running) ? 1500 : false;
    },
  });
}

export function useCourses() {
  return useQuery({ queryKey: ["courses"], queryFn: () => api.get<{ courses: string[] }>("/api/courses") });
}

export function useNotes() {
  return useQuery({ queryKey: ["notes"], queryFn: () => api.get<{ notes: NoteMeta[] }>("/api/notes") });
}

export function useSearch(q: string, course: string | null) {
  return useQuery({
    queryKey: ["search", course, q],
    enabled: q.trim().length > 0,
    queryFn: () =>
      api.get<{ results: Hit[] }>(
        "/api/search?q=" + encodeURIComponent(q.trim()) + (course ? "&course=" + encodeURIComponent(course) : ""),
      ),
    staleTime: 5 * 60 * 1000,
  });
}

export function useNote(noteId: string | null) {
  return useQuery({
    queryKey: ["note", noteId],
    enabled: !!noteId,
    queryFn: () => api.get<{ pages: NotePage[] }>("/api/note/" + api.encId(noteId!)),
  });
}

export function useDriveChildren(parent: string) {
  return useQuery({
    queryKey: ["children", parent],
    queryFn: () => api.get<{ folders: DriveFolder[] }>("/api/drive/children?parent=" + encodeURIComponent(parent)),
  });
}

export function useFolders(enabled: boolean) {
  return useQuery({
    queryKey: ["folders"],
    enabled,
    queryFn: () => api.get<{ root: string; folders: SyncFolder[] }>("/api/folders"),
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/api/auth/login"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, string>) => api.post("/api/settings", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["folders"] });
    },
  });
}

export function useSetFolderPref() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { folder_id: string; name: string; choice: string }) => api.post("/api/folders", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["folders"] }),
  });
}

export function useStartSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/api/sync"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });
}

export function useStopSync() {
  return useMutation({ mutationFn: () => api.post("/api/sync/stop") });
}
