/**
 * Extract/Download right bar — the paper linked to the focused (or clicked)
 * study, rendered with the shared `PdfCanvasViewer` so it is themed exactly
 * like the coding view's centre panel (the `.qc-pdf-canvas` OLED inversion)
 * and lazily pulls the pdf.js worker only when a PDF is actually opened.
 *
 * `MetaView` mirrors the selected `MetaDocument` into `metaUi`; this pane
 * keeps the bar shell (header + "open in new tab" fallback) and delegates the
 * loading/error/empty document states to the viewer.
 */
import { ExternalLink, FileText } from "lucide-react";
import { sourceFileUrl } from "@/lib/api";
import {
  BarHeader,
  BarTitle,
  Button,
  EmptyState,
  IconButton,
  LeftBar,
} from "@/components/ui/orchestrator";
import { PdfCanvasViewer } from "@/features/pdf/PdfCanvasViewer";
import { useI18n } from "@/lib/i18n";
import { useWorkspaceStore } from "@/stores/workspace";

export function MetaPdfPane() {
  const { t } = useI18n();
  const doc = useWorkspaceStore((s) => s.metaUi.selectedDocument);
  const sourceId = doc?.source_id ?? null;

  // The raw file endpoint serves an attachment, so this is the same fallback
  // the old blob viewer used when framing failed.
  const openExternal = () => {
    if (sourceId) window.open(sourceFileUrl(sourceId), "_blank", "noopener,noreferrer");
  };

  return (
    <LeftBar
      borderSide="l"
      className="h-full min-h-0"
      scroll={false}
      header={
        <BarHeader
          title={<BarTitle icon={FileText} label={t("meta.linkedPaper")} />}
          actions={
            sourceId ? (
              <IconButton
                label={t("meta.openInNewTab")}
                title={t("meta.openInNewTab")}
                size="sm"
                onClick={openExternal}
              >
                <ExternalLink size={13} aria-hidden />
              </IconButton>
            ) : undefined
          }
        />
      }
    >
      <div className="flex min-h-0 flex-1 flex-col">
        {!sourceId ? (
          <EmptyState icon={<FileText size={24} aria-hidden />}>{t("meta.noPdfLinked")}</EmptyState>
        ) : (
          <PdfCanvasViewer
            key={sourceId}
            sourceId={sourceId}
            title={doc?.title ?? t("meta.linkedPaper")}
            controls="minimal"
            loadingLabel={t("meta.loadingPdf")}
            className="min-h-0 flex-1"
            errorAction={
              <Button
                variant="secondary"
                icon={<ExternalLink size={12} aria-hidden />}
                onClick={openExternal}
              >
                {t("meta.openInNewTab")}
              </Button>
            }
          />
        )}
      </div>
    </LeftBar>
  );
}
