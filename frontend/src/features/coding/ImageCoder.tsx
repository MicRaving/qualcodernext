/**
 * ImageCoder — view an image and create rectangular code regions on it.
 *
 * Region coordinates are stored in IMAGE pixel space (x1/y1/width/height
 * relative to the natural image size). The zoom transform maps image pixels
 * to screen pixels: screen = image * zoom.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, Pencil, Trash2, ZoomIn, ZoomOut } from "lucide-react";
import { api, sourceFileUrl, type CodeTreeItem, type ImageCoding, type Source } from "@/lib/api";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { codeTint } from "@/features/coding/tint";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  ErrorBanner,
  IconButton,
  LoadingState,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { cls } from "@/components/ui/tokens";
import { useProjectStore } from "@/stores/project";

interface DragState {
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
}

interface RectState {
  x1: number;
  y1: number;
  width: number;
  height: number;
}

export function ImageCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  const activeCodeId = useProjectStore((s) => s.activeCodeId);
  const hiddenCodes = useProjectStore((s) => s.hiddenCodes);
  const [codings, setCodings] = useState<ImageCoding[]>([]);
  const [codes, setCodes] = useState<CodeTreeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [naturalSize, setNaturalSize] = useState<{ w: number; h: number } | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingRect, setPendingRect] = useState<RectState | null>(null);
  const [selected, setSelected] = useState<ImageCoding | null>(null);
  const [saving, setSaving] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const imageWrapRef = useRef<HTMLDivElement | null>(null);
  const pendingRectRef = useRef<RectState | null>(null);
  const dragRef = useRef<DragState | null>(null);

  useEffect(() => {
    pendingRectRef.current = pendingRect;
  }, [pendingRect]);

  const colorByCid = useMemo(() => {
    const map = new Map<number, string>();
    for (const c of codes) if (c.kind === "code" && c.color) map.set(c.id, c.color);
    return map;
  }, [codes]);

  const nameByCid = useMemo(() => {
    const map = new Map<number, string>();
    for (const c of codes) if (c.kind === "code") map.set(c.id, c.name);
    return map;
  }, [codes]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cs, flat] = await Promise.all([api.imageCodings(source.id), api.codesFlat()]);
      setCodings(cs);
      setCodes(flat);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("coder.loadCodingsError"));
    } finally {
      setLoading(false);
    }
  }, [source.id, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const codeColor = (coding: ImageCoding) => colorByCid.get(coding.cid) ?? "rgba(0,0,0,0.15)";

  const fitZoom = useCallback(() => {
    const el = containerRef.current;
    if (!el || !naturalSize) return;
    const avail = el.clientWidth - 8;
    if (avail > 0) setZoom(Math.max(0.1, Math.min(3, avail / naturalSize.w)));
  }, [naturalSize]);

  useEffect(() => {
    if (imageLoaded && naturalSize) fitZoom();
  }, [imageLoaded, naturalSize, fitZoom]);

  // --- drag-to-select -------------------------------------------------

  const toImageCoords = useCallback(
    (clientX: number, clientY: number): { x: number; y: number } => {
      const el = imageWrapRef.current;
      if (!el) return { x: 0, y: 0 };
      const rect = el.getBoundingClientRect();
      return {
        x: Math.max(0, (clientX - rect.left) / zoom),
        y: Math.max(0, (clientY - rect.top) / zoom),
      };
    },
    [zoom],
  );

  function handleMouseDown(e: React.MouseEvent) {
    if (e.button !== 0) return;
    const p = toImageCoords(e.clientX, e.clientY);
    const next = { startX: p.x, startY: p.y, currentX: p.x, currentY: p.y };
    dragRef.current = next;
    setDrag(next);
  }

  /** Code the pending drag rectangle with the given code id. */
  const codeRect = useCallback(
    async (cid: number, rect: { x1: number; y1: number; width: number; height: number }) => {
      setPickerOpen(false);
      setSaving(true);
      setError(null);
      try {
        await api.createImageCoding({
          id: source.id,
          x1: rect.x1,
          y1: rect.y1,
          width: rect.width,
          height: rect.height,
          cid,
          owner: "default",
        });
        setPendingRect(null);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : t("coder.createError"));
      } finally {
        setSaving(false);
      }
    },
    [source.id, load, t],
  );

  // Clicking a code in the left sidebar assigns it to the pending rectangle.
  useEffect(() => {
    const onAssign = (e: Event) => {
      const cid = (e as CustomEvent<{ cid: number }>).detail?.cid;
      if (typeof cid !== "number") return;
      setPickerOpen(false);
      const rect = pendingRectRef.current;
      if (rect) void codeRect(cid, rect);
    };
    window.addEventListener("qc:assign-code", onAssign);
    return () => window.removeEventListener("qc:assign-code", onAssign);
  }, [codeRect]);

  async function handlePick(code: PickedCode) {
    setPickerOpen(false);
    const rect = pendingRectRef.current;
    if (rect) await codeRect(code.cid, rect);
  }

  // The drag must survive leaving the picture: track it on the window and
  // finish on any mouseup (a mouseleave on the container used to abort it).
  useEffect(() => {
    if (!drag) return;
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const p = toImageCoords(e.clientX, e.clientY);
      const next = { ...d, currentX: p.x, currentY: p.y };
      dragRef.current = next;
      setDrag(next);
    };
    const onUp = () => {
      const d = dragRef.current;
      dragRef.current = null;
      setDrag(null);
      if (!d) return;
      const x1 = Math.min(d.startX, d.currentX);
      const y1 = Math.min(d.startY, d.currentY);
      const width = Math.abs(d.currentX - d.startX);
      const height = Math.abs(d.currentY - d.startY);
      if (width < 3 || height < 3) return;
      const rect = { x1: Math.round(x1), y1: Math.round(y1), width: Math.round(width), height: Math.round(height) };
      setPendingRect(rect);
      if (activeCodeId != null) {
        void codeRect(activeCodeId, rect);
      } else {
        setPickerOpen(true);
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [drag, zoom, activeCodeId, codeRect, toImageCoords]);

  async function handleDelete(coding: ImageCoding) {
    if (
      !window.confirm(
        t("imageCoder.deleteConfirm", {
          name: nameByCid.get(coding.cid) ?? t("coder.plainCode"),
        }),
      )
    )
      return;
    try {
      await api.deleteImageCoding(coding.imid);
      setSelected(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("coder.deleteError"));
    }
  }

  async function handleEditGeometry(coding: ImageCoding) {
    const current = `${Math.round(coding.x1)},${Math.round(coding.y1)},${Math.round(coding.width)},${Math.round(coding.height)}`;
    const raw = window.prompt(t("imageCoder.regionGeometry"), current);
    if (raw === null) return;
    const parts = raw.split(",").map((p) => Number(p.trim()));
    if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n) || n < 0)) {
      setError(t("imageCoder.regionSaveError"));
      return;
    }
    try {
      await api.patchImageCoding(coding.imid, {
        x1: parts[0],
        y1: parts[1],
        width: parts[2],
        height: parts[3],
      });
      setSelected(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("imageCoder.regionSaveError"));
    }
  }

  const dragRect = useMemo(() => {
    if (!drag) return null;
    return {
      left: Math.min(drag.startX, drag.currentX),
      top: Math.min(drag.startY, drag.currentY),
      width: Math.abs(drag.currentX - drag.startX),
      height: Math.abs(drag.currentY - drag.startY),
    };
  }, [drag]);

  if (loading) {
    return <LoadingState>{t("imageCoder.loading")}</LoadingState>;
  }

  if (error && codings.length === 0 && !imageLoaded) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="text-center">
          <p className="text-danger">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void load()}>
            {t("common.retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      {/* Toolbar */}
      <ViewHeader
        title={source.name}
        meta={`· ${t("imageCoder.dragHint")}`}
        actions={
          <div className="flex items-center gap-1">
            <IconButton label={t("imageCoder.zoomOut")} onClick={() => setZoom((z) => Math.max(0.1, +(z - 0.1).toFixed(2)))}>
              <ZoomOut size={16} aria-hidden />
            </IconButton>
            <span className="w-10 text-center text-xs text-text-secondary">{Math.round(zoom * 100)}%</span>
            <IconButton label={t("imageCoder.zoomIn")} onClick={() => setZoom((z) => Math.min(3, +(z + 0.1).toFixed(2)))}>
              <ZoomIn size={16} aria-hidden />
            </IconButton>
            <Button variant="secondary" className="ml-1 py-0.5" onClick={fitZoom}>
              {t("imageCoder.fit")}
            </Button>
          </div>
        }
      />

      {error && <ErrorBanner>{error}</ErrorBanner>}

      {/* Canvas */}
      <div ref={containerRef} className="min-h-0 flex-1 overflow-auto p-1">
        <div
          ref={imageWrapRef}
          className="relative inline-block cursor-crosshair"
          style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
          onMouseDown={handleMouseDown}
        >
          <img
            src={sourceFileUrl(source.id)}
            alt={source.name}
            draggable={false}
            onDragStart={(e) => e.preventDefault()}
            onLoad={(e) => {
              const el = e.currentTarget;
              setNaturalSize({ w: el.naturalWidth, h: el.naturalHeight });
              setImageLoaded(true);
            }}
            onError={() => setError(t("imageCoder.loadFileError"))}
            className="block select-none"
          />

          {/* Coded regions */}
          <div>
          {codings.map((coding) => (
            <div
              key={coding.imid}
              onClick={(e) => {
                e.stopPropagation();
                setSelected(coding);
              }}
              title={`${nameByCid.get(coding.cid) ?? t("coder.plainCode")}${coding.memo ? ` — ${coding.memo}` : ""}`}
              className={`absolute cursor-pointer border qc-seg ${
                hiddenCodes.includes(coding.cid) ? "qc-seg-hidden" : ""
              }`}
              style={{
                // The wrapper div already applies scale(zoom); children must
                // use UNSCALED image-space coordinates (fixes double-scaling).
                left: coding.x1,
                top: coding.y1,
                width: coding.width,
                height: coding.height,
                backgroundColor: codeTint(codeColor(coding)),
                borderColor: codeColor(coding),
              }}
            />
          ))}
          </div>

          {/* Selection preview */}
          {dragRect && (
            <div
              className="pointer-events-none absolute border-2 border-accent bg-accent/20"
              style={{ left: dragRect.left, top: dragRect.top, width: dragRect.width, height: dragRect.height }}
            />
          )}
        </div>
      </div>

      {/* Details panel */}
      {selected && (
        <div className="flex shrink-0 items-center gap-3 border-t border-border bg-surface px-3 py-2">
          <span
            className="h-3 w-3 shrink-0 rounded-sm border border-border"
            style={{ backgroundColor: codeColor(selected) }}
            aria-hidden
          />
          <span className="truncate text-sm font-medium text-text-primary">
            {nameByCid.get(selected.cid) ?? t("coder.fallbackCodePlain", { id: selected.cid })}
          </span>
          <span className="truncate text-xs text-text-secondary">
            {selected.memo || t("common.noMemo")} · {Math.round(selected.width)}×{Math.round(selected.height)}px
          </span>
          <div className="flex-1" />
          <Button
            variant="secondary"
            icon={<Pencil size={12} aria-hidden />}
            onClick={() => void handleEditGeometry(selected)}
          >
            {t("imageCoder.editRegion")}
          </Button>
          <Button
            variant="danger"
            icon={<Trash2 size={12} aria-hidden />}
            onClick={() => void handleDelete(selected)}
          >
            {t("common.delete")}
          </Button>
          <Button variant="secondary" onClick={() => setSelected(null)}>
            {t("common.close")}
          </Button>
        </div>
      )}

      <CodePicker
        open={pickerOpen}
        codes={codes}
        onClose={() => {
          setPickerOpen(false);
          setPendingRect(null);
        }}
        onPick={(code) => void handlePick(code)}
      />
      {saving && (
        <div className={`pointer-events-none bg-bg/40 ${cls.modalOverlay}`}>
          <LoaderCircle size={20} className="animate-spin text-text-secondary" aria-hidden />
        </div>
      )}
    </div>
  );
}
