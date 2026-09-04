/**
 * ImageCoder — view an image and create rectangular code regions on it.
 *
 * Region coordinates are stored in IMAGE pixel space (x1/y1/width/height
 * relative to the natural image size). The zoom transform maps image pixels
 * to screen pixels: screen = image * zoom.
 */
import { errorMessage } from "@/lib/utils";
import { useAsyncEffect } from "@/lib/useAsync";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, Pencil, Trash2, Undo2, ZoomIn, ZoomOut } from "lucide-react";
import { api, fetchSourceFile, type ImageCoding, type Source } from "@/lib/api";
import { useCoder } from "@/features/coding/useCoder";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { codingWeight, useCodeMaps } from "@/features/coding/codingApi";
import { useAssignCode } from "@/features/coding/shared/events";
import { useEscapeStack } from "@/features/coding/shared/useEscapeStack";
import { useSegmentActions } from "@/features/coding/shared/useSegmentActions";
import { WeightStepper } from "@/features/coding/shared/WeightStepper";
import { codeTint } from "@/features/coding/tint";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  ErrorBanner,
  IconButton,
  Input,
  LoadingState,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { cls } from "@/components/ui/tokens";
import { useCoderStore } from "@/stores/coder";
import { useInspectorStore } from "@/stores/inspector";
import { usePrefsStore } from "@/stores/prefs";

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

/** String draft of a region's geometry while the inline editor is open. */
interface RectDraft {
  x1: string;
  y1: string;
  width: string;
  height: string;
}

/** Parse a geometry draft; null when any field is missing/negative. */
function parseDraftRect(draft: RectDraft): RectState | null {
  const vals = [draft.x1, draft.y1, draft.width, draft.height].map((v) => Number(v));
  if (vals.some((n) => !Number.isFinite(n) || n < 0)) return null;
  return { x1: vals[0], y1: vals[1], width: vals[2], height: vals[3] };
}

export function ImageCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  const activeCodeId = useCoderStore((s) => s.activeCodeId);
  const hiddenCodes = useCoderStore((s) => s.hiddenCodes);
  /** When OFF, creating a coding does NOT auto-select it in the details
   *  panel (clicking a region still views it). */
  const autoShowDetails = usePrefsStore((s) => s.autoShowSegmentDetails);
  const { loading, error, setError, codings, codes, reload } = useCoder(
    source,
    api.imageCodings,
    t("coder.loadCodingsError"),
  );
  const [zoom, setZoom] = useState(1);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [naturalSize, setNaturalSize] = useState<{ w: number; h: number } | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingRect, setPendingRect] = useState<RectState | null>(null);
  const [selected, setSelected] = useState<ImageCoding | null>(null);
  const [editDraft, setEditDraft] = useState<RectDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [imgSrc, setImgSrc] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imageWrapRef = useRef<HTMLDivElement | null>(null);
  const pendingRectRef = useRef<RectState | null>(null);
  const dragRef = useRef<DragState | null>(null);

  useEffect(() => {
    pendingRectRef.current = pendingRect;
  }, [pendingRect]);

  const { colorByCid, nameByCid } = useCodeMaps(codes);

  // Fetch the full-resolution image through the shared base-resolving
  // helper (the raw URL builders are the sync dev fallback until the App
  // boot gate settles) and hand it to <img> as a blob URL. A transport
  // failure re-resolves the base and retries once inside the helper.
  // Stale fetches (rapid source.id churn) are ignored so they cannot orphan
  // object URLs or overwrite the current image.
  const requestIdRef = useRef(0);
  const objectUrlRef = useRef<string | null>(null);
  useAsyncEffect(async (signal) => {
    const requestId = ++requestIdRef.current;
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    setImgSrc(null);
    setImageLoaded(false);
    try {
      const res = await fetchSourceFile(source.id);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      signal.throwIfAborted();
      if (requestId !== requestIdRef.current) return;
      const url = URL.createObjectURL(blob);
      objectUrlRef.current = url;
      setImgSrc(url);
    } catch (e) {
      if (requestId !== requestIdRef.current) return;
      signal.throwIfAborted();
      setError(errorMessage(e, t("imageCoder.loadFileError")));
    }
  }, [source.id, t, setError]);

  // Revoke the blob URL on unmount.
  useEffect(() => {
    return () => {
      requestIdRef.current += 1;
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, []);

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
  const createRect = useCallback(
    async (cid: number, rect: { x1: number; y1: number; width: number; height: number }) => {
      const created = await api.createImageCoding({
        id: source.id,
        x1: rect.x1,
        y1: rect.y1,
        width: rect.width,
        height: rect.height,
        cid,
        owner: "default",
      });
      return created;
    },
    [source.id],
  );

  const codeRect = useCallback(
    async (cid: number, rect: { x1: number; y1: number; width: number; height: number }) => {
      setPickerOpen(false);
      setSaving(true);
      setError(null);
      try {
        const created = await createRect(cid, rect);
        setPendingRect(null);
        const fresh = await reload();
        setEditDraft(null);
        // Show the details of the freshly assigned region automatically
        // (gated on the "Auto-show segment details" pref — when OFF the
        // bar stays closed; clicking a region still views it).
        if (autoShowDetails) {
          setSelected(fresh.find((c) => c.imid === created.imid) ?? null);
        } else {
          setSelected(null);
        }
      } catch (e) {
        setError(errorMessage(e, t("coder.createError")));
      } finally {
        setSaving(false);
      }
    },
    [createRect, reload, t, autoShowDetails, setError],
  );

  // Clicking a code in the left sidebar assigns it to the pending rectangle.
  useAssignCode((cid) => {
    setPickerOpen(false);
    const rect = pendingRectRef.current;
    if (rect) void codeRect(cid, rect);
  });

  // Escape dismisses the picker first, then the details panel.
  useEscapeStack([
    () => {
      if (!pickerOpen) return false;
      setPickerOpen(false);
      setPendingRect(null);
      return true;
    },
    () => {
      if (!selected && !editDraft) return false;
      setSelected(null);
      setEditDraft(null);
      return true;
    },
  ]);

  async function handlePick(codes: PickedCode[]) {
    setPickerOpen(false);
    const rect = pendingRectRef.current;
    if (!rect || codes.length === 0) return;
    // Create all codings first, then ONE reload — parallel create+reload
    // loops used to race each other's refreshes.
    setSaving(true);
    setError(null);
    let last: ImageCoding | undefined;
    try {
      for (const code of codes) {
        last = await createRect(code.cid, rect);
      }
      setPendingRect(null);
      setEditDraft(null);
      const fresh = await reload();
      const created = last;
      if (autoShowDetails && created) {
        setSelected(fresh.find((c) => c.imid === created.imid) ?? null);
      } else {
        setSelected(null);
      }
    } catch (e) {
      setError(errorMessage(e, t("coder.createError")));
    } finally {
      setSaving(false);
    }
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

  // Shared mutation actions (memo/weight/important/delete) with a
  // recoverable-delete undo stack — deletes confirm AND push here.
  const actions = useSegmentActions({
    kind: "image",
    rows: codings,
    idOf: (r) => r.imid,
    deleteRow: (imid) => api.deleteImageCoding(imid),
    refresh: () => reload(),
    onError: setError,
    onDeleted: () => {
      setSelected(null);
      setEditDraft(null);
    },
  });
  const { undo } = actions;

  async function handleDelete(coding: ImageCoding) {
    if (
      !window.confirm(
        t("imageCoder.deleteConfirm", {
          name: nameByCid.get(coding.cid) ?? t("coder.plainCode"),
        }),
      )
    )
      return;
    actions.remove(coding.imid);
  }

  /** Stepper update of a region's weight (0-100; 0 = no weight); the
   *  details panel re-selects the fresh row so the value updates. */
  function updateCodingWeight(coding: ImageCoding, weight: number) {
    void actions.updateWeight(coding.imid, weight).then((fresh) => {
      if (Array.isArray(fresh)) {
        setSelected((fresh as ImageCoding[]).find((c) => c.imid === coding.imid) ?? null);
      }
    });
  }

  function startEditGeometry(coding: ImageCoding) {
    setEditDraft({
      x1: String(Math.round(coding.x1)),
      y1: String(Math.round(coding.y1)),
      width: String(Math.round(coding.width)),
      height: String(Math.round(coding.height)),
    });
  }

  async function applyEditGeometry() {
    if (!editDraft || !selected) return;
    const rect = parseDraftRect(editDraft);
    if (!rect) {
      setError(t("imageCoder.regionSaveError"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.patchImageCoding(selected.imid, rect);
      const fresh = await reload();
      setEditDraft(null);
      setSelected(fresh.find((c) => c.imid === selected.imid) ?? null);
    } catch (e) {
      setError(errorMessage(e, t("imageCoder.regionSaveError")));
    } finally {
      setSaving(false);
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
          <Button variant="secondary" className="mt-3" onClick={() => void reload()}>
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
            {undo.canUndo && (
              <Button
                variant="secondary"
                className="ml-1 py-0.5"
                icon={<Undo2 size={12} aria-hidden />}
                onClick={undo.undoLast}
                title={t("coder.unmarkTitle")}
              >
                {t("coder.unmarkLast")}
              </Button>
            )}
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
          role="img"
          aria-label={t("imageCoder.dragHint")}
        >
          <img
            src={imgSrc ?? undefined}
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
                setEditDraft(null);
                setSelected(coding);
                // Choosing a code occasion also shows its details in the
                // right-bar Inspector.
                void useInspectorStore.getState().selectCode(coding.cid);
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

          {/* Live overlay of the geometry being edited */}
          {editDraft && (() => {
            const rect = parseDraftRect(editDraft);
            if (!rect) return null;
            return (
              <div
                className="pointer-events-none absolute border-2 border-accent bg-accent/20"
                style={{ left: rect.x1, top: rect.y1, width: rect.width, height: rect.height }}
              />
            );
          })()}

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
        <div className="qc-enter shrink-0 border-t border-border bg-surface px-3 py-2">
          <div className="flex items-center gap-3">
            <span
              className="h-3 w-3 shrink-0 rounded-sm border border-border"
              style={{ backgroundColor: codeColor(selected) }}
              aria-hidden
            />
            <span className="truncate text-sm font-medium text-text-primary" title={selected.date}>
              {nameByCid.get(selected.cid) ?? t("coder.fallbackCodePlain", { id: selected.cid })}
            </span>
            <span className="truncate text-xs text-text-secondary">
              {selected.memo || t("common.noMemo")} · {Math.round(selected.x1)},{Math.round(selected.y1)} ·{" "}
              {Math.round(selected.width)}×{Math.round(selected.height)}px
            </span>
            <div className="flex-1" />
            {!editDraft && (
              <>
                <span className="flex items-center gap-1">
                  <span className="text-xs text-text-secondary">{t("coder.weight")}</span>
                  <WeightStepper
                    value={codingWeight(selected)}
                    onChange={(next) => updateCodingWeight(selected, next)}
                  />
                </span>
                <Button
                  variant="secondary"
                  icon={<Pencil size={12} aria-hidden />}
                  onClick={() => startEditGeometry(selected)}
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
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSelected(null);
                    setEditDraft(null);
                  }}
                >
                  {t("common.close")}
                </Button>
              </>
            )}
          </div>
          {editDraft && (
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <CoordField
                label={t("imageCoder.x")}
                value={editDraft.x1}
                onChange={(v) => setEditDraft((d) => (d ? { ...d, x1: v } : d))}
              />
              <CoordField
                label={t("imageCoder.y")}
                value={editDraft.y1}
                onChange={(v) => setEditDraft((d) => (d ? { ...d, y1: v } : d))}
              />
              <CoordField
                label={t("imageCoder.w")}
                value={editDraft.width}
                onChange={(v) => setEditDraft((d) => (d ? { ...d, width: v } : d))}
              />
              <CoordField
                label={t("imageCoder.h")}
                value={editDraft.height}
                onChange={(v) => setEditDraft((d) => (d ? { ...d, height: v } : d))}
              />
              <div className="flex-1" />
              <Button variant="secondary" onClick={() => setEditDraft(null)}>
                {t("common.cancel")}
              </Button>
              <Button variant="primaryCompact" onClick={() => void applyEditGeometry()}>
                {t("common.apply")}
              </Button>
            </div>
          )}
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
        <div className={`pointer-events-none bg-bg/40 ${cls.modalOverlay} qc-modal-backdrop`}>
          <LoaderCircle size={20} className="animate-spin text-text-secondary" aria-hidden />
        </div>
      )}
    </div>
  );
}

/** Small labeled number input for one region-coordinate field. */
function CoordField({
  label,
  value,
  onChange,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-[10px] font-medium uppercase tracking-wide text-text-secondary">{label}</span>
      <Input
        type="number"
        min={0}
        step={1}
        value={value}
        aria-label={label}
        onChange={(e) => onChange(e.target.value)}
        className="w-16"
      />
    </label>
  );
}
