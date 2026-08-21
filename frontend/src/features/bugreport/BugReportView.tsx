/**
 * Bug report composer (modal) — screenshot + painting + GitHub issue.
 *
 * Opened from the ribbon's bug button. Captures the app view (html2canvas,
 * done BEFORE the modal opens), lets the user paint over the picture
 * (highlight with red/yellow, redact with thick black) and composes a
 * GitHub issue: title, body (prefilled with the environment block: app
 * version, OS, last action, last error), labels, assignee, milestone.
 *
 * Submission: the DEFAULT flow (no token) opens a prefilled GitHub
 * `issues/new` page in the system browser (via the Tauri opener plugin in
 * the packaged app) — no account/token needed inside QCnext; the user
 * completes and submits the issue there, attaching the downloaded
 * screenshot. With a GitHub token configured (optional) the screenshot is
 * uploaded through the issues web editor's attachment endpoint and the
 * issue is created via the REST API instead.
 */
import { errorMessage } from "@/lib/utils";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bug,
  CheckCircle2,
  Download,
  Eraser,
  ExternalLink,
  LoaderCircle,
  RotateCcw,
  Send,
  Trash2,
  Undo2,
} from "lucide-react";
import { Button, Field, IconButton, Input, Modal, Textarea } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { APP_VERSION } from "@/lib/version";
import { useProjectStore, type BugReportState } from "@/stores/project";
import { errorDetail } from "@/features/ai/format";
import {
  createGitHubIssue,
  githubNewIssueUrl,
  openExternal,
  splitRepo,
  uploadIssueAttachment,
} from "@/features/bugreport/github";

const COMMON_LABELS = ["bug", "enhancement", "question"];

const BRUSH_COLORS = [
  { name: "bugReport.colorRed", value: "#ef4444" },
  { name: "bugReport.colorYellow", value: "#eab308" },
  { name: "bugReport.colorBlack", value: "#000000" },
];

const BRUSH_SIZES = [
  { name: "bugReport.sizeSmall", value: 3 },
  { name: "bugReport.sizeMedium", value: 8 },
  { name: "bugReport.sizeLarge", value: 18 },
];

/** Max backing-store size of the paint canvas (the capture can be large). */
const CANVAS_MAX_W = 640;
const CANVAS_MAX_H = 420;

interface Stroke {
  color: string;
  size: number;
  erase: boolean;
  points: { x: number; y: number }[];
}

/** Build the environment block prefilling the issue body. */
function envBlock(version: string, os: string, lastAction: string | null, lastError: string | null): string {
  const lines = [
    `**${version}**`,
    `**${os}**`,
    `**Last action:** ${lastAction ?? "—"}`,
    `**Last error:** ${lastError ?? "—"}`,
  ];
  return `${lines.join("\n")}\n\n`;
}

/**
 * The paint surface: screenshot + overlay strokes (undo/clear/reset, brush
 * colors + sizes, erase via destination-out). Strokes are replayed over the
 * base image on every change so undo/clear always produce exact results.
 */
function PaintCanvas({
  imageUrl,
  onCaptured,
}: {
  imageUrl: string | null;
  /** Reports the annotated PNG data-URL after each stroke change. */
  onCaptured: (dataUrl: string | null) => void;
}) {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const baseRef = useRef<HTMLCanvasElement | null>(null);
  const strokesRef = useRef<Stroke[]>([]);
  const activeRef = useRef<Stroke | null>(null);
  const drawingRef = useRef(false);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [color, setColor] = useState(BRUSH_COLORS[0].value);
  const [size, setSize] = useState(BRUSH_SIZES[1].value);
  const [erase, setErase] = useState(false);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const base = baseRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !base || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(base, 0, 0);
    for (const s of strokesRef.current) {
      if (s.points.length === 0) continue;
      ctx.save();
      ctx.globalCompositeOperation = s.erase ? "destination-out" : "source-over";
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.size;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      s.points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.stroke();
      ctx.restore();
    }
  }, []);

  // (Re)load the screenshot into the base canvas and clear the strokes.
  useEffect(() => {
    if (!imageUrl) return;
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, CANVAS_MAX_W / img.width, CANVAS_MAX_H / img.height);
      const w = Math.max(1, Math.round(img.width * scale));
      const h = Math.max(1, Math.round(img.height * scale));
      if (!baseRef.current) baseRef.current = document.createElement("canvas");
      baseRef.current.width = w;
      baseRef.current.height = h;
      baseRef.current.getContext("2d")?.drawImage(img, 0, 0, w, h);
      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = w;
        canvas.height = h;
      }
      strokesRef.current = [];
      setStrokes([]);
      redraw();
      onCaptured(canvasRef.current?.toDataURL("image/png") ?? null);
    };
    img.onerror = () => onCaptured(null);
    img.src = imageUrl;
  }, [imageUrl, redraw, onCaptured]);

  const commitStrokes = useCallback(
    (next: Stroke[]) => {
      strokesRef.current = next;
      setStrokes(next);
      redraw();
      onCaptured(canvasRef.current?.toDataURL("image/png") ?? null);
    },
    [redraw, onCaptured],
  );

  const pointOf = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * canvas.width,
      y: ((e.clientY - rect.top) / rect.height) * canvas.height,
    };
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {BRUSH_COLORS.map((c) => (
          <button
            key={c.value}
            type="button"
            aria-label={t(c.name)}
            title={t(c.name)}
            aria-pressed={!erase && color === c.value}
            onClick={() => {
              setColor(c.value);
              setErase(false);
            }}
            className={`h-6 w-6 rounded-sm border ${
              !erase && color === c.value ? "border-accent ring-1 ring-accent" : "border-border"
            }`}
            style={{ backgroundColor: c.value }}
          />
        ))}
        <span className="mx-1 h-5 w-px bg-border" aria-hidden />
        {BRUSH_SIZES.map((s) => (
          <button
            key={s.value}
            type="button"
            aria-label={t(s.name)}
            title={t(s.name)}
            aria-pressed={!erase && size === s.value}
            onClick={() => {
              setSize(s.value);
              setErase(false);
            }}
            className={`flex h-6 w-6 items-center justify-center rounded-sm border ${
              !erase && size === s.value ? "border-accent bg-surface-higher" : "border-border"
            }`}
          >
            <span
              className="rounded-full bg-text-secondary"
              style={{ width: s.value, height: s.value }}
            />
          </button>
        ))}
        <span className="mx-1 h-5 w-px bg-border" aria-hidden />
        <IconButton
          label={t("bugReport.erase")}
          title={t("bugReport.erase")}
          size="sm"
          aria-pressed={erase}
          className={erase ? "bg-surface-higher text-accent" : ""}
          onClick={() => setErase((v) => !v)}
        >
          <Eraser size={13} aria-hidden />
        </IconButton>
        <IconButton
          label={t("bugReport.undo")}
          title={t("bugReport.undo")}
          size="sm"
          disabled={strokes.length === 0}
          onClick={() => commitStrokes(strokesRef.current.slice(0, -1))}
        >
          <Undo2 size={13} aria-hidden />
        </IconButton>
        <IconButton
          label={t("bugReport.clear")}
          title={t("bugReport.clear")}
          size="sm"
          disabled={strokes.length === 0}
          onClick={() => commitStrokes([])}
        >
          <Trash2 size={13} aria-hidden />
        </IconButton>
        <IconButton
          label={t("bugReport.reset")}
          title={t("bugReport.reset")}
          size="sm"
          onClick={() => commitStrokes([])}
        >
          <RotateCcw size={13} aria-hidden />
        </IconButton>
      </div>
      {imageUrl ? (
        <canvas
          ref={canvasRef}
          data-testid="bugreport-canvas"
          className="max-h-[26rem] max-w-full touch-none rounded-sm border border-border bg-white"
          style={{ width: "100%", height: "auto" }}
          onPointerDown={(e) => {
            e.preventDefault();
            drawingRef.current = true;
            activeRef.current = {
              color,
              size,
              erase,
              points: [pointOf(e)],
            };
            commitStrokes([...strokesRef.current, activeRef.current]);
            (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (!drawingRef.current || !activeRef.current) return;
            activeRef.current.points.push(pointOf(e));
            redraw();
          }}
          onPointerUp={(e) => {
            if (!drawingRef.current) return;
            drawingRef.current = false;
            activeRef.current = null;
            (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
          }}
          onPointerCancel={() => {
            drawingRef.current = false;
            activeRef.current = null;
          }}
        />
      ) : (
        <div className="flex h-48 items-center justify-center rounded-sm border border-border text-xs text-text-secondary">
          {t("bugReport.noScreenshot")}
        </div>
      )}
      <p className="text-xs leading-relaxed text-text-secondary">{t("bugReport.paintHint")}</p>
    </div>
  );
}

export function BugReportView() {
  const { t } = useI18n();
  const open = useProjectStore((s) => s.bugReport.open);
  const screenshot = useProjectStore((s) => s.bugReport.rawScreenshot);
  const captureFailed = useProjectStore((s) => s.bugReport.captureFailed);
  const title = useProjectStore((s) => s.bugReport.title);
  const body = useProjectStore((s) => s.bugReport.body);
  const labels = useProjectStore((s) => s.bugReport.labels);
  const assignee = useProjectStore((s) => s.bugReport.assignee);
  const milestone = useProjectStore((s) => s.bugReport.milestone);
  const githubToken = useProjectStore((s) => s.bugReport.githubToken);
  const githubRepo = useProjectStore((s) => s.bugReport.githubRepo);
  const [submitting, setSubmitting] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<null | "browser" | "done" | "error">(null);
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [attachNote, setAttachNote] = useState<string | null>(null);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<string | null>(null);

  // Seed the issue body with the environment block once per open (the user's
  // edits are never overwritten — a re-open keeps what they typed).
  useEffect(() => {
    const st = useProjectStore.getState().bugReport;
    if (!open || st.body) return;
    const block = envBlock(
      APP_VERSION,
      typeof navigator !== "undefined" ? navigator.userAgent : "unknown",
      st.lastAction,
      st.lastError,
    );
    useProjectStore.getState().updateBugReport({ body: block });
  }, [open, body, t]);

  const update = useCallback((patch: Partial<BugReportState>) => {
    useProjectStore.getState().updateBugReport(patch);
  }, []);

  const close = () => {
    useProjectStore.getState().closeBugReport();
    setSubmitStatus(null);
    setResultUrl(null);
    setSubmitError(null);
    setAttachNote(null);
    setFallbackUrl(null);
    setDownloadStatus(null);
  };

  const labelsText = labels.join(", ");
  const setLabelsText = (text: string) =>
    update({
      labels: text
        .split(",")
        .map((l) => l.trim())
        .filter(Boolean),
    });
  const toggleLabel = (label: string) =>
    update({
      labels: labels.includes(label)
        ? labels.filter((l) => l !== label)
        : [...labels, label],
    });

  // Latest annotated pixels from the PaintCanvas (falls back to the raw
  // screenshot until a stroke is made).
  const paintRef = useRef<string | null>(null);
  const onCaptured = useCallback((dataUrl: string | null) => {
    paintRef.current = dataUrl;
  }, []);

  const onSubmit = async () => {
    if (submitting || !title.trim()) return;
    setSubmitting(true);
    setSubmitStatus(null);
    setResultUrl(null);
    setSubmitError(null);
    setAttachNote(null);
    setFallbackUrl(null);
    const st = useProjectStore.getState().bugReport;
    try {
      // The annotated canvas pixels (falls back to the raw screenshot when
      // the canvas has not produced a frame yet).
      const dataUrl = paintRef.current ?? screenshot;
      let finalBody = st.body;
      const token = st.githubToken.trim();
      if (token) {
        let attached = false;
        if (dataUrl) {
          try {
            const blob = await (await fetch(dataUrl)).blob();
            const md = await uploadIssueAttachment(
              st.githubRepo,
              blob,
              "qcnext-screenshot.png",
              token,
            );
            if (md) {
              finalBody += `\n\n${md}`;
              attached = true;
            }
          } catch (e) {
            setAttachNote(
              t("bugReport.attachFailed", {
                detail: errorMessage(e, String(e)),
              }),
            );
          }
        }
        if (!attached && dataUrl) {
          finalBody += `\n\n**${t("bugReport.screenshotSection")}:**\n![screenshot](${dataUrl})`;
        }
        const issue = await createGitHubIssue(
          st.githubRepo,
          {
            title: title.trim(),
            body: finalBody,
            labels,
            assignee,
            milestone,
          },
          token,
        );
        setResultUrl(issue.htmlUrl);
        setSubmitStatus("done");
      } else {
        const pageBody =
          finalBody +
          (dataUrl
            ? `\n\n**${t("bugReport.screenshotSection")}:**\n![screenshot](${t("bugReport.pasteImagePlaceholder")})`
            : "");
        const url = githubNewIssueUrl(st.githubRepo, title.trim(), pageBody);
        setFallbackUrl(url);
        await openExternal(url);
        setSubmitStatus("browser");
      }
    } catch (e) {
      setSubmitError(errorDetail(e, t("bugReport.submitFailed")));
      setSubmitStatus("error");
    } finally {
      setSubmitting(false);
    }
  };

  const repoLabel = (() => {
    const { owner, name } = splitRepo(githubRepo);
    return owner && name ? `${owner}/${name}` : githubRepo;
  })();

  // Download the annotated screenshot as a PNG so the user can attach it to
  // the issue on GitHub (the token-less flow cannot upload it for them).
  const downloadScreenshot = async () => {
    const dataUrl = paintRef.current ?? screenshot;
    if (!dataUrl) {
      setDownloadStatus(t("bugReport.noScreenshot"));
      return;
    }
    try {
      const blob = await (await fetch(dataUrl)).blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "qcnext-screenshot.png";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setDownloadStatus(t("bugReport.screenshotDownloaded"));
    } catch {
      setDownloadStatus(t("bugReport.downloadFailed"));
    }
  };

  return (
    <Modal
      open={open}
      onClose={close}
      icon={<Bug size={15} aria-hidden />}
      title={
        <span className="flex items-center gap-2">
          {t("bugReport.title")}
          <span className="rounded-sm bg-surface-higher px-1.5 py-px text-[10px] font-normal text-text-secondary">
            {repoLabel}
          </span>
        </span>
      }
      ariaLabel={t("bugReport.title")}
      panelClassName="flex w-[60rem] max-w-[95vw] max-h-[92dvh] flex-col"
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex min-h-0 flex-1 flex-col gap-0 md:flex-row">
          {/* Left: the issue form */}
          <div className="qc-scroll min-w-0 flex-1 overflow-y-auto p-3">
            <div className="flex flex-col gap-3">
              {captureFailed && (
                <p role="alert" className="rounded-sm border border-danger/50 bg-danger/10 px-2 py-1.5 text-xs text-danger">
                  {t("bugReport.captureFailed")}
                </p>
              )}
              <Field label={t("bugReport.titleLabel")}>
                <Input
                  value={title}
                  onChange={(e) => update({ title: e.target.value })}
                  placeholder={t("bugReport.titlePlaceholder")}
                  className="w-full"
                />
              </Field>
              <Field label={t("bugReport.bodyLabel")}>
                <Textarea
                  value={body}
                  onChange={(e) => update({ body: e.target.value })}
                  className="h-40 w-full resize-y p-2"
                />
              </Field>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Field label={t("bugReport.labelsLabel")}>
                  <Input
                    value={labelsText}
                    onChange={(e) => setLabelsText(e.target.value)}
                    placeholder="bug, enhancement, question"
                    className="w-full"
                  />
                </Field>
                <Field label={t("bugReport.assigneeLabel")}>
                  <Input
                    value={assignee}
                    onChange={(e) => update({ assignee: e.target.value })}
                    placeholder={t("settings.optional")}
                    className="w-full"
                  />
                </Field>
                <Field label={t("bugReport.milestoneLabel")}>
                  <Input
                    value={milestone}
                    onChange={(e) => update({ milestone: e.target.value })}
                    placeholder={t("settings.optional")}
                    className="w-full"
                  />
                </Field>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {COMMON_LABELS.map((l) => (
                  <button
                    key={l}
                    type="button"
                    aria-pressed={labels.includes(l)}
                    onClick={() => toggleLabel(l)}
                    className={`rounded-full border px-2 py-px text-xs ${
                      labels.includes(l)
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border text-text-secondary hover:bg-surface-higher"
                    }`}
                  >
                    {l}
                  </button>
                ))}
              </div>
              {githubToken.trim() ? (
                <p className="text-xs text-text-secondary">{t("bugReport.permissionsHint")}</p>
              ) : (
                <p className="text-xs text-text-secondary">{t("bugReport.noTokenHint")}</p>
              )}
            </div>
          </div>

          {/* Right: the screenshot + paint toolbar */}
          <div className="flex shrink-0 flex-col gap-2 border-l border-border p-3 md:w-96">
            <div className="text-xs font-medium text-text-primary">{t("bugReport.screenshotLabel")}</div>
            <PaintCanvas imageUrl={screenshot} onCaptured={onCaptured} />
          </div>
        </div>

        {/* Footer: status + submit */}
        <div className="flex items-center gap-2 border-t border-border px-3 py-2">
          <div className="min-w-0 flex-1">
            {submitStatus === "done" && resultUrl && (
              <p className="flex items-center gap-1.5 text-xs text-success" role="status">
                <CheckCircle2 size={13} aria-hidden />
                {t("bugReport.created")}{" "}
                <a
                  href={resultUrl}
                  onClick={(e) => {
                    e.preventDefault();
                    void openExternal(resultUrl);
                  }}
                  className="inline-flex items-center gap-0.5 text-accent underline"
                >
                  {resultUrl}
                  <ExternalLink size={11} aria-hidden />
                </a>
              </p>
            )}
            {submitStatus === "browser" && (
              <p className="text-xs text-text-secondary" role="status">
                {t("bugReport.browserOpened")}
              </p>
            )}
            {attachNote && (
              <p className="text-xs text-warning" role="alert">
                {attachNote}
              </p>
            )}
            {downloadStatus && (
              <p className="text-xs text-text-secondary" role="status">
                {downloadStatus}
              </p>
            )}
            {submitStatus === "error" && (
              <div className="flex items-center gap-2">
                <p className="min-w-0 truncate text-xs text-danger" role="alert">
                  {submitError}
                </p>
                {fallbackUrl && (
                  <Button
                    variant="secondary"
                    className="shrink-0"
                    icon={<ExternalLink size={12} aria-hidden />}
                    onClick={() => void openExternal(fallbackUrl)}
                  >
                    {t("bugReport.openBrowser")}
                  </Button>
                )}
              </div>
            )}
          </div>
          <Button
            variant="secondary"
            disabled={!screenshot || submitting}
            onClick={() => void downloadScreenshot()}
            icon={<Download size={13} aria-hidden />}
            data-testid="bugreport-download"
          >
            {t("bugReport.downloadScreenshot")}
          </Button>
          <Button
            variant="primary"
            disabled={submitting || title.trim() === ""}
            onClick={() => void onSubmit()}
            icon={
              submitting ? (
                <LoaderCircle size={13} className="animate-spin" aria-hidden />
              ) : githubToken.trim() ? (
                <Send size={13} aria-hidden />
              ) : (
                <ExternalLink size={13} aria-hidden />
              )
            }
          >
            {githubToken.trim() ? t("bugReport.submit") : t("bugReport.openBrowser")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
