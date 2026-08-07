export function barWidth(count: number, max: number): string {
  if (max <= 0) return "0%";
  return `${Math.round((count / max) * 100)}%`;
}

export function fileTypeLabel(name: string, mediaType: string): string {
  if (name.toLowerCase().endsWith(".pdf")) return "PDF";
  return mediaType.charAt(0).toUpperCase() + mediaType.slice(1);
}

export function matrixCell(count: number): string {
  return count === 0 ? "—" : String(count);
}

export function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}
