/**
 * Dashboard — the app's home. With a project open it shows statistics;
 * without one it offers New/Open project (and recent projects), so the app
 * always starts here. Picking a folder in the Open browse flow opens the
 * project immediately — no second click.
 */
import { useEffect, useState, type FormEvent } from "react";
import { BookOpen, FolderOpen, FolderTree, Hash, Layers, PlusCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

/** True inside the Tauri shell (native dialogs available); false in plain-browser dev. */
const isTauriShell =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Pick a directory via the native dialog. Returns null if cancelled/unavailable. */
async function pickDirectory(): Promise<string | null> {
  if (!isTauriShell) return null;
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const picked = await open({ directory: true, multiple: false });
    return typeof picked === "string" ? picked : null;
  } catch {
    return null;
  }
}

/** Join a picked directory with a filename using the platform separator. */
function joinPath(dir: string, name: string): string {
  return dir.endsWith("\\") || dir.endsWith("/") ? `${dir}${name}` : `${dir}\\${name}`;
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center gap-2 text-text-secondary">
        {icon}
        <span className="text-xs font-medium">{label}</span>
      </div>
      <div className="mt-1 text-2xl font-bold text-text-primary">{value}</div>
    </div>
  );
}

function ProjectFormDialog({
  mode,
  onClose,
}: {
  mode: "create" | "open";
  onClose: () => void;
}) {
  const { t } = useI18n();
  const busy = useProjectStore((s) => s.busy);
  const createProject = useProjectStore((s) => s.createProject);
  const openProject = useProjectStore((s) => s.openProject);
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!path.trim() || busy) return;
    setError(null);
    const ok =
      mode === "create"
        ? await createProject(path.trim())
        : await openProject(path.trim());
    if (ok) onClose();
  }

  // Picking a folder for OPEN is the action itself — no second click.
  async function browse() {
    const dir = await pickDirectory();
    if (!dir) return;
    if (mode === "create") {
      setPath(joinPath(dir, "NewProject.qda"));
    } else {
      setPath(dir);
      const ok = await openProject(dir);
      if (ok) onClose();
    }
  }

  const inputId = mode === "create" ? "create-path" : "open-path";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/70"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={mode === "create" ? t("welcome.newProject") : t("welcome.openProject")}
    >
      <form onSubmit={(e) => void submit(e)} className="w-96 max-w-[92vw] rounded-lg border border-border bg-surface shadow-xl">
        <div className="border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold text-text-primary">
            {mode === "create" ? t("welcome.newProject") : t("welcome.openProject")}
          </h2>
        </div>
        <div className="space-y-3 p-4">
          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">
              {mode === "create" ? t("welcome.createLabel") : t("welcome.openLabel")}
            </span>
            <div className="flex gap-2">
              <input
                id={inputId}
                type="text"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder={t("welcome.pathPlaceholder")}
                className="w-full min-w-0 flex-1 rounded-sm border border-border bg-bg px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
              />
              {isTauriShell && (
                <button
                  type="button"
                  onClick={() => void browse()}
                  className="shrink-0 rounded-sm border border-border bg-bg px-3 py-1.5 text-sm hover:bg-surface-higher"
                >
                  {t("welcome.browse")}
                </button>
              )}
            </div>
          </label>
          {error && (
            <p className="text-xs text-danger" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-sm border border-border bg-bg px-2.5 py-1 text-xs hover:bg-surface-higher disabled:opacity-40"
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={busy || !path.trim()}
              className="rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
            >
              {busy
                ? mode === "create"
                  ? t("welcome.creating")
                  : t("welcome.opening")
                : mode === "create"
                  ? t("welcome.createButton")
                  : t("welcome.openButton")}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function EmptyState() {
  const { t } = useI18n();
  const [recent, setRecent] = useState<string[]>([]);
  const [dialog, setDialog] = useState<"create" | "open" | null>(null);
  const busy = useProjectStore((s) => s.busy);
  const error = useProjectStore((s) => s.error);
  const openProject = useProjectStore((s) => s.openProject);

  useEffect(() => {
    api
      .recentProjects()
      .then((r) => setRecent(r.recent))
      .catch(() => setRecent([]));
  }, []);

  // In the Tauri shell, Open is ONE step: the native folder picker IS the
  // action. The typed-path dialog remains for plain-browser dev.
  async function handleOpenClick() {
    if (isTauriShell) {
      const dir = await pickDirectory();
      if (dir) await openProject(dir);
    } else {
      setDialog("open");
    }
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      <div className="border-b border-border px-6 py-3">
        <span className="text-sm font-medium text-text-primary">{t("app.name")}</span>
        <span className="ml-2 text-xs text-text-secondary">{t("app.version")}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {error && (
          <div
            role="alert"
            className="mb-4 max-w-xl rounded-sm border border-danger/50 bg-danger/10 px-3 py-2 text-sm text-danger"
          >
            {error}
          </div>
        )}

        <div className="flex max-w-xl items-center gap-2">
          <button
            type="button"
            onClick={() => setDialog("create")}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-sm bg-accent px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
          >
            <PlusCircle size={15} aria-hidden />
            {t("welcome.newProject")}
          </button>
          <button
            type="button"
            onClick={() => void handleOpenClick()}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-sm border border-border bg-surface px-3 py-1.5 text-sm hover:bg-surface-higher disabled:opacity-50"
          >
            <FolderOpen size={15} aria-hidden />
            {t("welcome.openProject")}
          </button>
        </div>

        {recent.length > 0 ? (
          <div className="mt-6">
            <h2 className="font-heading text-text-secondary">{t("welcome.recentProjects")}</h2>
            <ul className="mt-2 space-y-1">
              {recent.map((path) => (
                <li key={path}>
                  <button
                    type="button"
                    onClick={() => openProject(path)}
                    disabled={busy}
                    className="flex w-full max-w-xl items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-surface-higher disabled:opacity-50"
                  >
                    <FolderOpen size={14} className="shrink-0 text-text-secondary" aria-hidden />
                    <span className="truncate">{path}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="mt-6 max-w-2xl">
            <p className="text-xs text-text-secondary">{t("shell.emptyBlocks")}</p>
            <div className="mt-3 grid grid-cols-3 gap-4">
              {["Files", "Codes", "Cases"].map((label) => (
                <div
                  key={label}
                  className="rounded-lg border border-dashed border-border bg-bg p-4"
                  aria-hidden
                >
                  <div className="text-xs font-medium text-text-secondary">{label}</div>
                  <div className="mt-1 text-2xl font-bold text-text-secondary/40">—</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {dialog && <ProjectFormDialog mode={dialog} onClose={() => setDialog(null)} />}
      </div>
    </div>
  );
}

export function DashboardView() {
  const { t } = useI18n();
  const projectOpen = useProjectStore((s) => s.projectOpen);
  const autoOpening = useProjectStore((s) => s.autoOpening);
  const autoOpenStage = useProjectStore((s) => s.autoOpenStage);
  const summary = useProjectStore((s) => s.summary);
  const projectName = useProjectStore((s) => s.projectName);
  const openProject = useProjectStore((s) => s.openProject);
  const busy = useProjectStore((s) => s.busy);
  const [openers, setOpeners] = useState<string[]>([]);
  const [recent, setRecent] = useState<string[]>([]);
  const [dialog, setDialog] = useState<"create" | "open" | null>(null);

  // In the Tauri shell, Open is ONE step: the native folder picker IS the
  // action (the backend swaps projects without closing the current one).
  async function handleOpenClick() {
    if (isTauriShell) {
      const dir = await pickDirectory();
      if (dir) await openProject(dir);
    } else {
      setDialog("open");
    }
  }

  useEffect(() => {
    if (!projectOpen) {
      setOpeners([]);
      setRecent([]);
      return;
    }
    let cancelled = false;
    api
      .projectOpeners()
      .then((r) => {
        if (!cancelled) setOpeners([...new Set(r.openers.map((o) => o.user))]);
      })
      .catch(() => {
        if (!cancelled) setOpeners([]);
      });
    api
      .recentProjects()
      .then((r) => {
        if (!cancelled) setRecent(r.recent);
      })
      .catch(() => {
        if (!cancelled) setRecent([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectOpen]);

  if (!projectOpen) {
    // The app starts on the dashboard immediately; while the recent
    // project auto-opens (packaged app) show its progress right here.
    if (autoOpening) {
      return (
        <div className="flex h-full items-center justify-center bg-bg">
          <div className="flex w-72 flex-col items-center gap-4">
            <span className="text-sm font-medium text-text-primary">{t("app.name")}</span>
            <div
              className="h-1 w-full overflow-hidden rounded-full bg-border"
              role="progressbar"
              aria-label={t("shell.openingRecent")}
            >
              <div className="h-full w-1/3 animate-pulse rounded-full bg-accent" />
            </div>
            <span className="text-xs text-text-secondary">
              {autoOpenStage === "backend"
                ? t("shell.startingBackend")
                : t("shell.openingRecent")}
            </span>
          </div>
        </div>
      );
    }
    return <EmptyState />;
  }

  if (!summary) {
    return (
      <div className="flex h-full items-center justify-center bg-bg text-text-secondary">
        Loading project…
      </div>
    );
  }

  return (
    <div className="overflow-y-auto bg-bg p-6">
      <h1 className="text-[28px] font-bold text-text-primary">{projectName}</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Database version {summary.databaseversion} · created {summary.project_date}
      </p>
      {openers.length > 0 && (
        <p className="mt-1 text-xs text-warning">
          {t("dashboard.openers", { users: openers.join(", ") })}
        </p>
      )}

      <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-3">
        <Stat icon={<BookOpen size={16} aria-hidden />} label="Files" value={summary.files_count} />
        <Stat icon={<FolderTree size={16} aria-hidden />} label="Codes" value={summary.codes_count} />
        <Stat icon={<Layers size={16} aria-hidden />} label="Code categories" value={summary.code_categories_count} />
        <Stat icon={<Hash size={16} aria-hidden />} label="Cases" value={summary.cases_count} />
        <Stat icon={<BookOpen size={16} aria-hidden />} label="Attribute types" value={summary.attributes_count} />
        <Stat icon={<BookOpen size={16} aria-hidden />} label="Journal entries" value={summary.journals_count} />
      </div>

      <div className="mt-6 flex items-center gap-2">
        <button
          type="button"
          onClick={() => setDialog("create")}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-sm bg-accent px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
          title={t("welcome.newProject")}
        >
          <PlusCircle size={15} aria-hidden />
          {t("welcome.newProject")}
        </button>
        <button
          type="button"
          onClick={() => void handleOpenClick()}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-sm border border-border bg-surface px-3 py-1.5 text-sm hover:bg-surface-higher disabled:opacity-50"
          title={t("welcome.openProject")}
        >
          <FolderOpen size={15} aria-hidden />
          {t("welcome.openProject")}
        </button>
      </div>

      {recent.length > 0 && (
        <div className="mt-7">
          <h2 className="font-heading text-text-secondary">{t("welcome.recentProjects")}</h2>
          <ul className="mt-2 space-y-1">
            {recent.map((path) => (
              <li key={path}>
                <button
                  type="button"
                  onClick={() => openProject(path)}
                  disabled={busy}
                  className="flex w-full max-w-xl items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-surface-higher disabled:opacity-50"
                >
                  <FolderOpen size={14} className="shrink-0 text-text-secondary" aria-hidden />
                  <span className="truncate">{path}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {dialog && <ProjectFormDialog mode={dialog} onClose={() => setDialog(null)} />}
    </div>
  );
}
