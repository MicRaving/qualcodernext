export interface ChartRow {
  name: string;
  color: string | null;
  count: number;
}

export interface ChartBar {
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  count: number;
  label: string;
}

export interface ChartLayout {
  maxCount: number;
  total: number;
  labelWidth: number;
  barAreaWidth: number;
  rowHeight: number;
  top: number;
  left: number;
  bars: ChartBar[];
}

const OUTER_PAD = 16;
const HEADER_HEIGHT = 80;
const LABEL_CHAR_WIDTH = 7;
const LABEL_MIN = 72;
const LABEL_MAX = 280;
const LABEL_BAR_GAP = 12;
const COUNT_ZONE = 56;
const BAR_RADIUS = 3;
const DEFAULT_BAR_COLOR = "#9a9ab0";

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

export function chartLayout(rows: ChartRow[], width: number, height: number): ChartLayout {
  const maxCount = rows.length > 0 ? Math.max(...rows.map((r) => r.count)) : 0;
  const total = rows.reduce((sum, r) => sum + r.count, 0);
  const longestName = rows.reduce((len, r) => Math.max(len, r.name.length), 0);
  const labelWidth =
    rows.length > 0 ? clamp(longestName * LABEL_CHAR_WIDTH, LABEL_MIN, LABEL_MAX) : 0;
  const left = OUTER_PAD + labelWidth + LABEL_BAR_GAP;
  const barAreaWidth = Math.max(0, width - left - COUNT_ZONE);
  const rowHeight = rows.length > 0 ? Math.max(26, (height - HEADER_HEIGHT) / rows.length) : 0;
  const top = HEADER_HEIGHT;
  const barHeight = Math.max(8, Math.min(rowHeight - 6, 22));
  const bars: ChartBar[] = rows.map((row, i) => ({
    x: left,
    y: top + i * rowHeight + (rowHeight - barHeight) / 2,
    w: maxCount > 0 ? (row.count / maxCount) * barAreaWidth : 0,
    h: barHeight,
    color: row.color ?? DEFAULT_BAR_COLOR,
    count: row.count,
    label: row.name,
  }));
  return { maxCount, total, labelWidth, barAreaWidth, rowHeight, top, left, bars };
}

function pngBlobFromDataUrl(dataUrl: string): Blob {
  const base64 = dataUrl.split(",")[1] ?? "";
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: "image/png" });
}

export function renderBarChartPng(rows: ChartRow[], width = 900, height = 520): Blob | null {
  try {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    const dpr = window.devicePixelRatio > 0 ? window.devicePixelRatio : 1;
    canvas.width = Math.max(1, Math.round(width * dpr));
    canvas.height = Math.max(1, Math.round(height * dpr));
    ctx.scale(dpr, dpr);

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "#d9d9dc";
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, width - 1, height - 1);

    ctx.textBaseline = "middle";
    ctx.fillStyle = "#1d1d23";
    ctx.font = "bold 16px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Code frequencies", OUTER_PAD, 26);
    ctx.fillStyle = "#6b6b76";
    ctx.font = "12px system-ui, sans-serif";
    const total = rows.reduce((sum, r) => sum + r.count, 0);
    ctx.fillText(`${rows.length} codes · ${total} codings`, OUTER_PAD, 44);

    const layout = chartLayout(rows, width, height);
    if (layout.bars.length === 0) {
      ctx.fillStyle = "#6b6b76";
      ctx.font = "14px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("0 codings", width / 2, height / 2);
      return pngBlobFromDataUrl(canvas.toDataURL("image/png"));
    }

    for (const bar of layout.bars) {
      ctx.fillStyle = bar.color;
      ctx.beginPath();
      if (typeof ctx.roundRect === "function") {
        ctx.roundRect(bar.x, bar.y, bar.w, bar.h, BAR_RADIUS);
      } else {
        ctx.rect(bar.x, bar.y, bar.w, bar.h);
      }
      ctx.fill();

      ctx.fillStyle = "#1d1d23";
      ctx.font = "12px system-ui, sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(bar.label, bar.x - LABEL_BAR_GAP, bar.y + bar.h / 2);
      ctx.textAlign = "left";
      ctx.fillText(String(bar.count), bar.x + bar.w + 8, bar.y + bar.h / 2);
    }
    return pngBlobFromDataUrl(canvas.toDataURL("image/png"));
  } catch {
    return null;
  }
}

export async function downloadChartPng(filename: string, rows: ChartRow[]): Promise<boolean> {
  const blob = renderBarChartPng(rows);
  if (!blob) return false;
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    return true;
  } catch {
    return false;
  } finally {
    URL.revokeObjectURL(url);
  }
}
