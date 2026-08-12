/**
 * CodingWorkspace — fetches the source for a coding view and dispatches to
 * the right coder based on media type / file extension.
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { CircleAlert } from "lucide-react";
import { Button, LoadingState } from "@/components/ui/orchestrator";
import { api, type Source } from "@/lib/api";
import { isPdf } from "@/lib/media";
import { useI18n } from "@/lib/i18n";
import { TextCoder } from "@/features/coding/TextCoder";
import { ImageCoder } from "@/features/coding/ImageCoder";
import { AvCoder } from "@/features/coding/AvCoder";

// pdfjs-dist is heavy (~1.2 MB worker); load it only when a PDF is opened.
const PdfCoder = lazy(() =>
  import("@/features/coding/PdfCoder").then((m) => ({ default: m.PdfCoder })),
);

function LazyPdfCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  return (
    <Suspense
      fallback={
        <LoadingState>{t("pdfCoder.loadingViewer")}</LoadingState>
      }
    >
      <PdfCoder source={source} />
    </Suspense>
  );
}

export function CodingWorkspace({ sourceId }: { sourceId: number }) {
  const { t } = useI18n();
  const [source, setSource] = useState<Source | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSource(null);
    void (async () => {
      try {
        const src = await api.getSource(sourceId);
        if (!cancelled) setSource(src);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : t("coder.loadError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sourceId, reloadTick, t]);

  if (loading) {
    return <LoadingState>{t("coder.loading")}</LoadingState>;
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="max-w-md text-center">
          <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
            <CircleAlert size={16} aria-hidden />
            {error}
          </p>
          <Button variant="secondary" className="mt-3" onClick={() => setReloadTick((t) => t + 1)}>
            {t("common.retry")}
          </Button>
        </div>
      </div>
    );
  }

  if (!source) return null;

  if (source.media_type === "text" && isPdf(source.name)) {
    return <LazyPdfCoder source={source} />;
  }
  if (source.media_type === "text") {
    return <TextCoder sourceId={sourceId} />;
  }
  if (source.media_type === "image") {
    return <ImageCoder source={source} />;
  }
  return <AvCoder source={source} />;
}
