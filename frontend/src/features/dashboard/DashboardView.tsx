/**
 * Dashboard — the app's home. With a project open it shows statistics;
 * without one it shows the same dashboard chrome with placeholder stats,
 * the New/Open project actions and recent projects (the ribbon stays
 * disabled until a project loads). Picking a folder in the Open browse
 * flow opens the project immediately — no second click.
 */
import { useEffect, useState, type FormEvent } from "react";
import { BookOpen, FolderOpen, FolderTree, Hash, Layers, LoaderCircle, PlusCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Input, Modal, ViewHeader } from "@/components/ui/orchestrator";
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

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number | string }) {
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
    <Modal
      open
      onClose={busy ? undefined : onClose}
      closeDisabled={busy}
      size="md"
      ariaLabel={mode === "create" ? t("welcome.newProject") : t("welcome.openProject")}
    >
      <form onSubmit={(e) => void submit(e)}>
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
              <Input
                id={inputId}
                type="text"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder={t("welcome.pathPlaceholder")}
                className="min-w-0 flex-1"
              />
              {isTauriShell && (
                <Button variant="secondary" onClick={() => void browse()}>
                  {t("welcome.browse")}
                </Button>
              )}
            </div>
          </label>
          {error && (
            <p className="text-xs text-danger" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="primary"
              type="submit"
              disabled={busy || !path.trim()}
            >
              {busy
                ? mode === "create"
                  ? t("welcome.creating")
                  : t("welcome.opening")
                : mode === "create"
                  ? t("welcome.createButton")
                  : t("welcome.openButton")}
            </Button>
          </div>
        </div>
      </form>
    </Modal>
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
  const error = useProjectStore((s) => s.error);
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
    let cancelled = false;
    // Recent projects are shown with and without a project (the dashboard
    // is always visible).
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
  }, []);

  // Without a project the same dashboard chrome is shown (stats read "—")
  // and only the ribbon navigation stays disabled until a project loads.
  // While the packaged app auto-opens the recent project, the progress
  // indicator sits right of the Open button (the dashboard stays visible).
  const stats = summary
    ? [
        { icon: BookOpen, label: "Files", value: summary.files_count },
        { icon: FolderTree, label: "Codes", value: summary.codes_count },
        { icon: Layers, label: "Code categories", value: summary.code_categories_count },
        { icon: Hash, label: "Cases", value: summary.cases_count },
        { icon: BookOpen, label: "Attribute types", value: summary.attributes_count },
        { icon: BookOpen, label: "Journal entries", value: summary.journals_count },
      ]
    : [
        { icon: BookOpen, label: "Files", value: "—" },
        { icon: FolderTree, label: "Codes", value: "—" },
        { icon: Layers, label: "Code categories", value: "—" },
        { icon: Hash, label: "Cases", value: "—" },
        { icon: BookOpen, label: "Attribute types", value: "—" },
        { icon: BookOpen, label: "Journal entries", value: "—" },
      ];

  return (
    <div className="flex h-full flex-col bg-bg">
      <ViewHeader
        back={false}
        title={projectOpen ? projectName : t("app.name")}
        meta={
          projectOpen && summary
            ? `Database version ${summary.databaseversion} · created ${summary.project_date}`
            : t("app.version")
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {!projectOpen && error && (
          <div
            role="alert"
            className="mb-4 max-w-xl rounded-sm border border-danger/50 bg-danger/10 px-3 py-2 text-sm text-danger"
          >
            {error}
          </div>
        )}

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
          {stats.map((s) => (
            <Stat key={s.label} icon={<s.icon size={16} aria-hidden />} label={s.label} value={s.value} />
          ))}
        </div>

        <div className="mt-6 flex items-center gap-2">
        <Button
          variant="primary"
          className="px-3! py-1.5! text-sm!"
          onClick={() => setDialog("create")}
          disabled={busy}
          icon={<PlusCircle size={15} aria-hidden />}
          title={t("welcome.newProject")}
        >
          {t("welcome.newProject")}
        </Button>
        <Button
          variant="secondary"
          className="px-3! py-1.5! text-sm!"
          onClick={() => void handleOpenClick()}
          disabled={busy || autoOpening}
          icon={<FolderOpen size={15} aria-hidden />}
          title={t("welcome.openProject")}
        >
          {t("welcome.openProject")}
        </Button>
        {!projectOpen && autoOpening && (
          <div
            className="flex items-center gap-2"
            role="progressbar"
            aria-label={t("shell.openingRecent")}
          >
            <LoaderCircle size={15} className="animate-spin text-accent" aria-hidden />
            <span className="text-xs text-text-secondary">
              {autoOpenStage === "backend"
                ? t("shell.startingBackend")
                : t("shell.openingRecent")}
            </span>
          </div>
        )}
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
    </div>
  );
}
