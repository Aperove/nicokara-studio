export type SubtitleLayout = "staggered" | "centered";
export type SubtitleVerticalPosition = "bottom" | "middle" | "top";

export type SubtitleStyle = {
  font_name: string;
  font_size: number;
  sung_color: string;
  unsung_color: string;
  outline_color: string;
  show_ruby: boolean;
  glow: boolean;
  layout: SubtitleLayout;
  vertical_position: SubtitleVerticalPosition;
  lead_in_ms: number;
};

export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  font_name: "Noto Sans CJK JP",
  font_size: 120,
  sung_color: "#FF6B6B",
  unsung_color: "#FFFFFF",
  outline_color: "#1F2937",
  show_ruby: true,
  glow: true,
  layout: "staggered",
  vertical_position: "bottom",
  lead_in_ms: 3000,
};

export type ColorPreset = {
  id: string;
  label: string;
  sung_color: string;
  unsung_color: string;
  outline_color: string;
};

export const COLOR_PRESETS: ColorPreset[] = [
  { id: "coral", label: "珊瑚", sung_color: "#FF6B6B", unsung_color: "#FFFFFF", outline_color: "#1F2937" },
  { id: "sky", label: "晴空", sung_color: "#38BDF8", unsung_color: "#FFFFFF", outline_color: "#0F172A" },
  { id: "mint", label: "薄荷", sung_color: "#34D399", unsung_color: "#FFFFFF", outline_color: "#0F2A24" },
  { id: "amber", label: "琥珀", sung_color: "#FBBF24", unsung_color: "#FFFFFF", outline_color: "#292524" },
  { id: "lavender", label: "薰衣草", sung_color: "#A78BFA", unsung_color: "#FFFFFF", outline_color: "#1E1B4B" },
  { id: "sakura", label: "樱花", sung_color: "#F472B6", unsung_color: "#FFF1F7", outline_color: "#3B0A2A" },
  { id: "ink", label: "墨蓝", sung_color: "#2563EB", unsung_color: "#0F172A", outline_color: "#F8FAFC" },
  { id: "classic", label: "经典红", sung_color: "#FF0000", unsung_color: "#000000", outline_color: "#FFFFFF" },
];
