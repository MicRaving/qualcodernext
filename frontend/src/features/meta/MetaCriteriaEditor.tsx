/**
 * Reusable inclusion-criterion editor (contract §1/§3).
 *
 * Each criterion carries the v2 fields the backend evaluates — `kind`
 * (verdict | classify | number), `options`, `pass_values`, `exclude_reason`,
 * `gating` and `help` — alongside the label and verbatim prompt text. The
 * component is controlled and self-contained: it renders an editable list and
 * emits the extended criterion payload, leaving persistence to the host
 * (MetaView wires it to `api.metaReplaceCriteria`).
 */
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import type { MetaCriterionKind } from "@/lib/api/types";
import { Button, IconButton, Input, Select, Textarea, Toggle } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";

export interface MetaCriterionDraft {
  id?: number;
  key: string;
  label: string;
  prompt_text: string;
  kind: MetaCriterionKind;
  options: string[];
  pass_values: string[];
  exclude_reason: string;
  gating: boolean;
  help: string;
}

const KINDS: MetaCriterionKind[] = ["verdict", "classify", "number"];

function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return /^[0-9]/.test(slug) ? `c_${slug}` : slug;
}

function blankCriterion(): MetaCriterionDraft {
  return {
    id: undefined,
    key: "",
    label: "",
    prompt_text: "",
    kind: "verdict",
    options: [],
    pass_values: ["yes"],
    exclude_reason: "",
    gating: true,
    help: "",
  };
}

function StringListEditor({
  label,
  values,
  onChange,
  addLabel,
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (next: string[]) => void;
  addLabel: string;
  placeholder: string;
}) {
  return (
    <div className="space-y-1">
      <span className="block text-[11px] text-text-secondary">{label}</span>
      {values.map((value, i) => (
        <div key={`${value}-${i}`} className="flex items-center gap-1">
          <Input
            value={value}
            onChange={(e) => onChange(values.map((v, j) => (j === i ? e.target.value : v)))}
            className="h-7 min-w-0 flex-1 text-xs"
            aria-label={placeholder}
          />
          <IconButton
            label={label}
            size="row"
            onClick={() => onChange(values.filter((_, j) => j !== i))}
          >
            <Trash2 size={12} aria-hidden />
          </IconButton>
        </div>
      ))}
      <Button
        variant="secondary"
        icon={<Plus size={12} aria-hidden />}
        onClick={() => onChange([...values, ""])}
      >
        {addLabel}
      </Button>
    </div>
  );
}

export function MetaCriteriaEditor({
  value,
  onChange,
  className = "",
}: {
  value: MetaCriterionDraft[];
  onChange: (next: MetaCriterionDraft[]) => void;
  className?: string;
}) {
  const { t } = useI18n();

  const patch = (index: number, update: Partial<MetaCriterionDraft>) =>
    onChange(value.map((c, i) => (i === index ? { ...c, ...update } : c)));

  const add = () => onChange([...value, blankCriterion()]);

  const remove = (index: number) => onChange(value.filter((_, i) => i !== index));

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= value.length) return;
    const next = [...value];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <div className={className}>
      {value.length === 0 && <p className="mb-2 text-xs text-text-secondary">{t("meta.noCriteria")}</p>}
      <div className="grid gap-2 md:grid-cols-2">
        {value.map((criterion, i) => {
          const showOptions = criterion.kind === "classify" || criterion.kind === "number";
          return (
            <div
              key={criterion.id ?? criterion.key ?? i}
              className="flex items-start gap-2 rounded-sm border border-border p-2"
            >
              <span className="mt-1.5 w-5 shrink-0 text-xs text-text-secondary">{i + 1}.</span>
              <div className="min-w-0 flex-1 space-y-1.5">
                <Input
                  value={criterion.label}
                  onChange={(e) => {
                    const label = e.target.value;
                    const auto = !criterion.key || criterion.key === slugify(criterion.label);
                    patch(i, { label, ...(auto ? { key: slugify(label) } : {}) });
                  }}
                  placeholder={t("meta.criterionLabel")}
                  className="h-7 w-full text-xs"
                  aria-label={t("meta.criterionLabel")}
                />
                <Textarea
                  value={criterion.prompt_text}
                  onChange={(e) => patch(i, { prompt_text: e.target.value })}
                  placeholder={t("meta.criterionPrompt")}
                  className="w-full text-xs"
                  rows={2}
                  aria-label={t("meta.criterionPrompt")}
                />
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  <label className="block min-w-0">
                    <span className="mb-1 block text-[11px] text-text-secondary">
                      {t("meta.criterionKind")}
                    </span>
                    <Select
                      value={criterion.kind}
                      onChange={(e) => patch(i, { kind: e.target.value as MetaCriterionKind })}
                      className="h-7 w-full text-xs"
                      aria-label={t("meta.criterionKind")}
                    >
                      {KINDS.map((kind) => (
                        <option key={kind} value={kind}>
                          {t(`meta.kind_${kind}`)}
                        </option>
                      ))}
                    </Select>
                  </label>
                  <label className="block min-w-0">
                    <span className="mb-1 block text-[11px] text-text-secondary">
                      {t("meta.criterionKey")}
                    </span>
                    <Input
                      value={criterion.key}
                      onChange={(e) => patch(i, { key: e.target.value })}
                      className="h-7 w-full text-xs"
                      aria-label={t("meta.criterionKey")}
                    />
                  </label>
                </div>

                {showOptions && (
                  <StringListEditor
                    label={t("meta.criterionOptions")}
                    addLabel={t("meta.addOption")}
                    placeholder={t("meta.optionPlaceholder")}
                    values={criterion.options}
                    onChange={(options) => patch(i, { options })}
                  />
                )}

                <StringListEditor
                  label={t("meta.criterionPassValues")}
                  addLabel={t("meta.addOption")}
                  placeholder={t("meta.optionPlaceholder")}
                  values={criterion.pass_values}
                  onChange={(pass_values) => patch(i, { pass_values })}
                />

                <label className="block min-w-0">
                  <span className="mb-1 block text-[11px] text-text-secondary">
                    {t("meta.criterionExcludeReason")}
                  </span>
                  <Input
                    value={criterion.exclude_reason}
                    onChange={(e) => patch(i, { exclude_reason: e.target.value })}
                    className="h-7 w-full text-xs"
                    aria-label={t("meta.criterionExcludeReason")}
                  />
                </label>

                <Textarea
                  value={criterion.help}
                  onChange={(e) => patch(i, { help: e.target.value })}
                  placeholder={t("meta.criterionHelp")}
                  className="w-full text-xs"
                  rows={2}
                  aria-label={t("meta.criterionHelp")}
                />

                <Toggle
                  checked={criterion.gating}
                  onChange={() => patch(i, { gating: !criterion.gating })}
                  label={t("meta.criterionGating")}
                />
              </div>

              <div className="flex shrink-0 flex-col items-center gap-0.5">
                <IconButton
                  label={t("meta.moveUp")}
                  size="sm"
                  disabled={i === 0}
                  className="disabled:opacity-30"
                  onClick={() => move(i, -1)}
                >
                  <ChevronUp size={12} aria-hidden />
                </IconButton>
                <IconButton
                  label={t("meta.moveDown")}
                  size="sm"
                  disabled={i === value.length - 1}
                  className="disabled:opacity-30"
                  onClick={() => move(i, 1)}
                >
                  <ChevronDown size={12} aria-hidden />
                </IconButton>
                <IconButton label={t("common.delete")} size="sm" onClick={() => remove(i)}>
                  <Trash2 size={12} aria-hidden />
                </IconButton>
              </div>
            </div>
          );
        })}
      </div>
      <Button
        variant="secondary"
        className="mt-2"
        icon={<Plus size={12} aria-hidden />}
        onClick={add}
      >
        {t("meta.addCriterion")}
      </Button>
    </div>
  );
}
