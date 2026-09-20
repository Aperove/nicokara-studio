"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { THEME_COPY } from "@/lib/ui-copy";

export type ThemeChoice = "light" | "dark" | "system";

const STORAGE_KEY = "nicokara-theme";
const CHANGE_EVENT = "nicokara-theme-change";
const ORDER: ThemeChoice[] = ["light", "dark", "system"];

/** Runs before the first paint so the page never flashes the wrong theme. */
export const THEME_BOOT_SCRIPT = `(function(){try{var c=localStorage.getItem("${STORAGE_KEY}")||"system";var d=c==="dark"||(c==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d)}catch(e){}})()`;

function storedChoice(): ThemeChoice {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(choice: ThemeChoice) {
  const dark =
    choice === "dark" ||
    (choice === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

function subscribe(onChange: () => void) {
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  const update = () => {
    apply(storedChoice());
    onChange();
  };
  system.addEventListener("change", update);
  window.addEventListener("storage", update);
  window.addEventListener(CHANGE_EVENT, update);
  return () => {
    system.removeEventListener("change", update);
    window.removeEventListener("storage", update);
    window.removeEventListener(CHANGE_EVENT, update);
  };
}

const ICONS = { light: Sun, dark: Moon, system: Monitor } as const;

export function ThemeToggle() {
  const choice = useSyncExternalStore<ThemeChoice>(
    subscribe,
    storedChoice,
    () => "system",
  );
  const next = ORDER[(ORDER.indexOf(choice) + 1) % ORDER.length];
  const Icon = ICONS[choice];

  return (
    <button
      type="button"
      title={THEME_COPY.switchTo(THEME_COPY.names[next])}
      aria-label={`${THEME_COPY.label}：${THEME_COPY.names[choice]}`}
      onClick={() => {
        try {
          localStorage.setItem(STORAGE_KEY, next);
        } catch {
          // private mode: the choice simply lasts for this page
        }
        apply(next);
        window.dispatchEvent(new Event(CHANGE_EVENT));
      }}
      className="focus-ring inline-flex h-9 items-center gap-2 rounded-lg border bg-card px-3 text-sm font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
    >
      <Icon className="size-4" />
      <span className="hidden sm:inline">{THEME_COPY.names[choice]}</span>
    </button>
  );
}
