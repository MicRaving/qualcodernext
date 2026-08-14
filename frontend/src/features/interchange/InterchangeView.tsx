/**
 * Interchange — Import / Export section of the Settings pane (General
 * area). No ribbon entry: the chrome-free embedded variant renders inside
 * SettingsView.
 *
 * Export: one-click REFI-QDA download (codebook, sources, codings, cases).
 * Import: an "Import…" button opens the manager in an overlay (Modal) —
 * drop zone, per-file format override + status, content preview,
 * qualitative-column customization and a batch confirm bar. Closing the
 * overlay while an import runs keeps the import going in the background:
 * progress rides the store's task queue (ribbon chip / queue flyout).
 */
import { useState } from "react";
import { Download, HelpCircle, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { Button, HelpFlyout, IconButton, Modal } from "@/components/ui/orchestrator";
import { cls } from "@/components/ui/tokens";
import { ImportPreview } from "@/features/interchange/ImportPreview";
import { FORCEABLE_FORMATS } from "@/features/interchange/importApi";
import { importLabel } from "@/features/interchange/format";
import { useI18n } from "@/lib/i18n";

/** Display label for a format kind (localized where a key exists). */
function formatLabel(t: (key: string) => string, kind: string): string {
  const key = `interchange.format${kind.charAt(0).toUpperCase()}${kind.slice(1)}`;
  const localized = t(key);
  return localized !== key ? localized : importLabel(kind);
}

/** Per-format help text (localized; empty when no key exists). */
function formatHelp(t: (key: string) => string, kind: string): string {
  const key = `interchange.help${kind.charAt(0).toUpperCase()}${kind.slice(1)}`;
  const localized = t(key);
  return localized !== key ? localized : "";
}

function FormatHelpList() {
  const { t } = useI18n();
  const kinds = [...FORCEABLE_FORMATS, "zotero"];
  return (
    <ul className="space-y-1.5">
      {kinds.map((kind) => (
        <li key={kind} className="text-xs leading-relaxed text-text-secondary">
          {formatLabel(t, kind)}
          {" — "}
          {formatHelp(t, kind)}
        </li>
      ))}
    </ul>
  );
}

export function InterchangeView() {
  const { t } = useI18n();
  const [helpOpen, setHelpOpen] = useState<null | "export" | "import">(null);
  const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  function toggleHelp(kind: "export" | "import", anchor: HTMLElement) {
    setHelpAnchor(anchor);
    setHelpOpen((cur) => (cur === kind ? null : kind));
  }

  return (
    <div>
      <h2 className="text-sm font-semibold text-text-primary">{t("settings.interchange")}</h2>
      <p className="mt-1 text-xs text-text-secondary">{t("settings.interchangeHint")}</p>

      {/* Button row: Import… (opens the overlay) + Export + export help */}
      <div className="mt-2 flex items-center gap-2">
        <Button
          variant="primary"
          icon={<Upload size={12} aria-hidden />}
          onClick={() => setImportOpen(true)}
        >
          {t("interchange.importButton")}
        </Button>
        <a
          href={api.interchange.exportRefiUrl()}
          download
          className={`inline-flex items-center gap-1.5 ${cls.secondary}`}
        >
          <Download size={13} aria-hidden />
          {t("interchange.exportButton")}
        </a>
        <IconButton
          label={t("interchange.exportHelp")}
          title={t("interchange.exportHelp")}
          size="sm"
          aria-expanded={helpOpen === "export"}
          onClick={(e) => toggleHelp("export", e.currentTarget)}
        >
          <HelpCircle size={12} aria-hidden />
        </IconButton>
        {helpOpen === "export" && helpAnchor && (
          <HelpFlyout anchor={helpAnchor} onClose={() => setHelpOpen(null)}>
            <p className="text-xs leading-relaxed text-text-secondary">
              {t("interchange.exportHelp")}
            </p>
          </HelpFlyout>
        )}
      </div>

      {/* Import manager overlay — the largest modal size; the body scrolls.
          Closing it mid-import is safe: the batch keeps running through the
          store's background task and shows up in the queue flyout. */}
      <Modal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        size="xl"
        icon={<Upload size={14} aria-hidden />}
        title={t("interchange.importDialog")}
      >
        <div className="qc-scroll max-h-[85vh] overflow-y-auto p-3">
          <div className="flex items-center gap-1.5">
            <h3 className="text-xs font-semibold text-text-primary">
              {t("interchange.importSection")}
            </h3>
            <IconButton
              label={t("interchange.helpTitle")}
              title={t("interchange.helpTitle")}
              size="sm"
              aria-expanded={helpOpen === "import"}
              onClick={(e) => toggleHelp("import", e.currentTarget)}
            >
              <HelpCircle size={12} aria-hidden />
            </IconButton>
            {helpOpen === "import" && helpAnchor && (
              <HelpFlyout anchor={helpAnchor} onClose={() => setHelpOpen(null)}>
                <FormatHelpList />
              </HelpFlyout>
            )}
          </div>
          <div className="mt-2">
            <ImportPreview />
          </div>
        </div>
      </Modal>
    </div>
  );
}
