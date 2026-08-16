/**
 * MaintenanceTab — Settings "Maintenance" section: the compact-on-close
 * switch (the full compaction runs automatically on project close) and the
 * semantic index (build / rebuild / purge).
 */
import { useCallback, useEffect, useState } from "react";
import { HelpCircle, LoaderCircle, RotateCw, Trash2 } from "lucide-react";
import { api, type AiIndexStatus } from "@/lib/api";
import { errorDetail } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import { Button, ErrorBanner, HelpFlyout, IconButton, Toggle } from "@/components/ui/orchestrator";

export function MaintenanceTab() {
  const { t } = useI18n();

  // Project compaction (automatic only — no manual "compact now").
  const [compactOnClose, setCompactOnClose] = useState(false);
  const [compactError, setCompactError] = useState<string | null>(null);

  // Semantic index
  const [indexStatus, setIndexStatus] = useState<AiIndexStatus | null>(null);
  const [indexBusy, setIndexBusy] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);

  const loadIndex = useCallback(async () => {
    try {
      setIndexStatus(await api.aiIndexStatus());
      setIndexError(null);
    } catch (e) {
      setIndexError(errorDetail(e, t("settings.aiLoadError")));
    }
  }, [t]);

  useEffect(() => {
    void loadIndex();
    api
      .maintenanceSettings()
      .then((s) => setCompactOnClose(s.compact_on_close))
      .catch(() => undefined);
  }, [loadIndex]);

  async function toggleCompactOnClose() {
    const next = !compactOnClose;
    setCompactOnClose(next);
    try {
      await api.saveMaintenanceSettings({ compact_on_close: next });
      setCompactError(null);
    } catch (e) {
      setCompactError(errorDetail(e, "Could not save maintenance settings"));
      setCompactOnClose(!next);
    }
  }

  async function buildIndex() {
    if (indexBusy) return;
    setIndexBusy(true);
    setIndexError(null);
    try {
      setIndexStatus(await api.aiIndexBuild());
    } catch (err) {
      setIndexError(errorDetail(err, "Index build failed"));
    } finally {
      setIndexBusy(false);
    }
  }

  async function deleteIndex() {
    try {
      await api.aiIndexDelete();
      await loadIndex();
    } catch (err) {
      setIndexError(errorDetail(err, "Could not delete index"));
    }
  }

  return (
    <div className="p-3">
      {compactError && <ErrorBanner>{compactError}</ErrorBanner>}

      {/* Project compaction — the "Compact on close" switch only; the full
          pass runs automatically when the project is closed. */}
      <h2 className="text-sm font-semibold text-text-primary">{t("settings.maintenanceSection")}</h2>
      <div className="mt-2">
        <Toggle
          checked={compactOnClose}
          onChange={() => void toggleCompactOnClose()}
          label={t("settings.compactOnClose")}
          hint={t("settings.compactOnCloseHint")}
        />
      </div>

      {/* Semantic index */}
      <section className="mt-4 border-t border-border pt-3">
        <div className="flex items-center gap-1.5">
          <h2 className="text-sm font-semibold text-text-primary">{t("ai.indexSection")}</h2>
          <IconButton
            label={t("ai.indexHint")}
            title={t("ai.indexHint")}
            size="sm"
            aria-expanded={helpOpen}
            onClick={(e) => {
              setHelpAnchor(e.currentTarget);
              setHelpOpen((v) => !v);
            }}
          >
            <HelpCircle size={12} aria-hidden />
          </IconButton>
          {helpOpen && helpAnchor && (
            <HelpFlyout anchor={helpAnchor} onClose={() => setHelpOpen(false)}>
              <p className="text-xs leading-relaxed text-text-secondary">{t("ai.indexHint")}</p>
            </HelpFlyout>
          )}
        </div>

        <div className="mt-2 flex h-6 items-center gap-1.5" title={indexError ?? undefined}>
          <span
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${
              indexError ? "bg-danger" : indexStatus?.indexed ? "bg-success" : "bg-border"
            }`}
            aria-hidden
          />
          <p className="min-w-0 truncate text-xs text-text-secondary">
            {indexError
              ? indexError
              : indexStatus?.indexed
                ? t("ai.indexStatusReady", {
                    chunks: String(indexStatus.chunks),
                    model: indexStatus.model,
                  })
                : t("ai.indexStatusNone")}
          </p>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => void buildIndex()}
            disabled={indexBusy}
            icon={
              indexBusy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <RotateCw size={12} aria-hidden />
              )
            }
          >
            {indexStatus?.indexed ? t("ai.indexRebuild") : t("ai.indexBuild")}
          </Button>
          {indexStatus?.indexed && (
            <Button
              variant="danger"
              onClick={() => void deleteIndex()}
              icon={<Trash2 size={12} aria-hidden />}
            >
              {t("ai.indexDelete")}
            </Button>
          )}
        </div>
      </section>
    </div>
  );
}
