"use client";

import { RotateCcw } from "lucide-react";
import { useState } from "react";

import { STYLE_COPY } from "@/lib/ui-copy";
import {
  COLOR_PRESETS,
  DEFAULT_SUBTITLE_STYLE,
  type SubtitleLayout,
  type SubtitleStyle,
  type SubtitleVerticalPosition,
} from "@/types/style";

type FontOption = { name: string; label: string; note?: string };

const FONT_OPTIONS: FontOption[] = [
  { name: "Noto Sans CJK JP", label: "Noto Sans CJK", note: "Docker" },
  { name: "Noto Sans JP", label: "Noto Sans JP" },
  { name: "Noto Serif JP", label: "Noto Serif JP" },
  { name: "Yu Gothic", label: "游ゴシック" },
  { name: "Yu Mincho", label: "游明朝" },
  { name: "Meiryo", label: "メイリオ" },
  { name: "BIZ UDGothic", label: "BIZ UDゴシック" },
  { name: "BIZ UDMincho", label: "BIZ UD明朝" },
  { name: "UD Digi Kyokasho N-B", label: "UD 教科書体" },
  { name: "MS Gothic", label: "MS ゴシック" },
  { name: "MS Mincho", label: "MS 明朝" },
];

const FONT_SAMPLE = "あ永 Aa";

const PREVIEW_BASE = "試験の歌詞";
const PREVIEW_SUNG_CHARS = 2;

type Props = {
  value: SubtitleStyle;
  onChange: (value: SubtitleStyle) => void;
  disabled?: boolean;
};

function outlineShadow(color: string, width: number): string {
  const offsets = [
    [-1, -1],
    [1, -1],
    [-1, 1],
    [1, 1],
    [0, -1],
    [0, 1],
    [-1, 0],
    [1, 0],
  ];
  return offsets
    .map(([x, y]) => `${x * width}px ${y * width}px 0 ${color}`)
    .join(", ");
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
  disabled,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex gap-2">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          disabled={disabled}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={`focus-ring flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition disabled:opacity-50 ${
            value === option.value
              ? "border-primary bg-primary/10 text-primary"
              : "bg-card text-muted-foreground hover:bg-muted"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function ColorField({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-lg border bg-card px-3 py-2 text-sm">
      <span>{label}</span>
      <span className="flex items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">{value}</span>
        <input
          type="color"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value.toUpperCase())}
          className="size-8 cursor-pointer rounded border bg-transparent p-0 disabled:cursor-not-allowed"
        />
      </span>
    </label>
  );
}

export function StylePanel({ value, onChange, disabled }: Props) {
  const set = <K extends keyof SubtitleStyle>(
    key: K,
    next: SubtitleStyle[K],
  ) => onChange({ ...value, [key]: next });

  const isListedFont = FONT_OPTIONS.some(
    (font) => font.name === value.font_name,
  );
  const [customFontOpen, setCustomFontOpen] = useState(!isListedFont);

  const previewSize = Math.round(value.font_size * 0.3);
  const outline = outlineShadow(
    value.outline_color,
    Math.max(1, previewSize / 14),
  );
  const alignItems =
    value.vertical_position === "top"
      ? "flex-start"
      : value.vertical_position === "middle"
        ? "center"
        : "flex-end";

  return (
    <div className="space-y-4">
      <div
        aria-hidden
        className="flex h-40 overflow-hidden rounded-2xl border p-4"
        style={{
          alignItems,
          justifyContent:
            value.layout === "centered" ? "center" : "flex-start",
          background:
            "linear-gradient(135deg, #334155 0%, #64748b 50%, #cbd5e1 100%)",
        }}
      >
        <div className="text-center leading-none">
          {value.show_ruby && (
            <div
              style={{
                color: value.unsung_color,
                fontFamily: `"${value.font_name}", sans-serif`,
                fontSize: previewSize * 0.4,
                fontWeight: 700,
                textShadow: outline,
                textAlign: "left",
                paddingLeft: previewSize * 0.15,
                marginBottom: 2,
              }}
            >
              しけん
            </div>
          )}
          <div
            style={{
              fontFamily: `"${value.font_name}", sans-serif`,
              fontSize: previewSize,
              fontWeight: 700,
              whiteSpace: "nowrap",
            }}
          >
            <span
              style={{
                color: value.sung_color,
                textShadow: value.glow
                  ? `0 0 ${previewSize / 3}px ${value.sung_color}`
                  : "none",
              }}
            >
              {PREVIEW_BASE.slice(0, PREVIEW_SUNG_CHARS)}
            </span>
            <span style={{ color: value.unsung_color, textShadow: outline }}>
              {PREVIEW_BASE.slice(PREVIEW_SUNG_CHARS)}
            </span>
          </div>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{STYLE_COPY.previewHint}</p>

      <div className="text-sm">
        <span className="mb-1.5 block font-medium">
          {STYLE_COPY.colorPresets}
        </span>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {COLOR_PRESETS.map((preset) => {
            const active =
              preset.sung_color === value.sung_color &&
              preset.unsung_color === value.unsung_color &&
              preset.outline_color === value.outline_color;
            return (
              <button
                key={preset.id}
                type="button"
                disabled={disabled}
                aria-label={preset.label}
                aria-pressed={active}
                onClick={() =>
                  onChange({
                    ...value,
                    sung_color: preset.sung_color,
                    unsung_color: preset.unsung_color,
                    outline_color: preset.outline_color,
                  })
                }
                className={`focus-ring flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition disabled:opacity-50 ${
                  active
                    ? "border-primary bg-primary/10 text-primary"
                    : "bg-card hover:bg-muted"
                }`}
              >
                <span
                  aria-hidden
                  className="flex h-5 w-9 shrink-0 overflow-hidden rounded-full border"
                  style={{ borderColor: preset.outline_color }}
                >
                  <span
                    className="flex-1"
                    style={{ background: preset.sung_color }}
                  />
                  <span
                    className="flex-1"
                    style={{ background: preset.unsung_color }}
                  />
                  <span
                    className="w-2"
                    style={{ background: preset.outline_color }}
                  />
                </span>
                <span className="truncate font-medium">{preset.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <ColorField
          label={STYLE_COPY.sungColor}
          value={value.sung_color}
          disabled={disabled}
          onChange={(next) => set("sung_color", next)}
        />
        <ColorField
          label={STYLE_COPY.unsungColor}
          value={value.unsung_color}
          disabled={disabled}
          onChange={(next) => set("unsung_color", next)}
        />
        <ColorField
          label={STYLE_COPY.outlineColor}
          value={value.outline_color}
          disabled={disabled}
          onChange={(next) => set("outline_color", next)}
        />
      </div>

      <div className="text-sm">
        <span className="mb-1.5 block font-medium">{STYLE_COPY.font}</span>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {FONT_OPTIONS.map((font) => {
            const active = font.name === value.font_name;
            return (
              <button
                key={font.name}
                type="button"
                disabled={disabled}
                aria-label={font.label}
                aria-pressed={active}
                onClick={() => {
                  set("font_name", font.name);
                  setCustomFontOpen(false);
                }}
                className={`focus-ring rounded-lg border px-3 py-2 text-left transition disabled:opacity-50 ${
                  active
                    ? "border-primary bg-primary/10 text-primary"
                    : "bg-card hover:bg-muted"
                }`}
              >
                <span
                  aria-hidden
                  className="block truncate text-xl font-bold leading-7"
                  style={{ fontFamily: `"${font.name}", sans-serif` }}
                >
                  {FONT_SAMPLE}
                </span>
                <span className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="truncate">{font.label}</span>
                  {font.note && (
                    <span className="rounded border px-1 text-[10px] leading-4">
                      {font.note}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
          <button
            type="button"
            disabled={disabled}
            aria-pressed={!isListedFont}
            aria-expanded={customFontOpen || !isListedFont}
            onClick={() => setCustomFontOpen((open) => !open)}
            className={`focus-ring rounded-lg border border-dashed px-3 py-2 text-left transition disabled:opacity-50 ${
              !isListedFont
                ? "border-primary bg-primary/10 text-primary"
                : "bg-card text-muted-foreground hover:bg-muted"
            }`}
          >
            <span className="block text-xl font-bold leading-7">…</span>
            <span className="mt-0.5 block text-xs">{STYLE_COPY.customFont}</span>
          </button>
        </div>
        {(customFontOpen || !isListedFont) && (
          <input
            type="text"
            value={value.font_name}
            maxLength={64}
            disabled={disabled}
            placeholder={STYLE_COPY.customFontPlaceholder}
            aria-label={STYLE_COPY.customFont}
            onChange={(event) => set("font_name", event.target.value)}
            className="focus-ring mt-2 w-full rounded-lg border bg-card px-3 py-2 disabled:bg-muted"
          />
        )}
        <span className="mt-1.5 block text-xs text-muted-foreground">
          {STYLE_COPY.fontHint}
        </span>
      </div>

      <div>
        <label className="block text-sm">
          <span className="mb-1.5 flex justify-between font-medium">
            <span>{STYLE_COPY.fontSize}</span>
            <span className="font-mono text-muted-foreground">
              {value.font_size}
            </span>
          </span>
          <input
            type="range"
            min={40}
            max={160}
            step={2}
            value={value.font_size}
            disabled={disabled}
            onChange={(event) => set("font_size", Number(event.target.value))}
            className="w-full accent-[var(--color-primary)]"
          />
          <span className="mt-1 block text-xs text-muted-foreground">
            {STYLE_COPY.fontSizeHint}
          </span>
        </label>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="text-sm">
          <span className="mb-1.5 block font-medium">{STYLE_COPY.layout}</span>
          <Segmented<SubtitleLayout>
            value={value.layout}
            disabled={disabled}
            onChange={(next) => set("layout", next)}
            options={[
              { value: "staggered", label: STYLE_COPY.layoutStaggered },
              { value: "centered", label: STYLE_COPY.layoutCentered },
            ]}
          />
        </div>
        <div className="text-sm">
          <span className="mb-1.5 block font-medium">
            {STYLE_COPY.verticalPosition}
          </span>
          <Segmented<SubtitleVerticalPosition>
            value={value.vertical_position}
            disabled={disabled}
            onChange={(next) => set("vertical_position", next)}
            options={[
              { value: "top", label: STYLE_COPY.positionTop },
              { value: "middle", label: STYLE_COPY.positionMiddle },
              { value: "bottom", label: STYLE_COPY.positionBottom },
            ]}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={value.show_ruby}
            disabled={disabled}
            onChange={(event) => set("show_ruby", event.target.checked)}
          />
          {STYLE_COPY.showRuby}
        </label>
        <label className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={value.glow}
            disabled={disabled}
            onChange={(event) => set("glow", event.target.checked)}
          />
          {STYLE_COPY.glow}
        </label>
        <label className="flex items-center justify-between gap-2 rounded-lg border bg-card px-3 py-2 text-sm">
          <span>{STYLE_COPY.leadIn}</span>
          <span className="flex items-center gap-1">
            <input
              type="number"
              min={0}
              max={10}
              step={0.5}
              value={value.lead_in_ms / 1000}
              disabled={disabled}
              onChange={(event) =>
                set(
                  "lead_in_ms",
                  Math.round(
                    Math.min(10, Math.max(0, Number(event.target.value) || 0)) *
                      1000,
                  ),
                )
              }
              className="focus-ring w-16 rounded border bg-card px-2 py-1 text-right"
            />
            <span className="text-xs text-muted-foreground">s</span>
          </span>
        </label>
      </div>

      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange(DEFAULT_SUBTITLE_STYLE)}
        className="focus-ring inline-flex items-center gap-1.5 rounded-sm text-xs text-muted-foreground underline-offset-4 hover:underline disabled:opacity-50"
      >
        <RotateCcw className="size-3.5" />
        {STYLE_COPY.reset}
      </button>
    </div>
  );
}
