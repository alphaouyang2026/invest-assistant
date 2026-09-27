"use client";

import { useEffect, useState } from "react";

/** The colours `globals.css` defines, for what draws on a canvas and cannot
 * use CSS variables. */
export type Palette = {
  text: string;
  muted: string;
  grid: string;
  line: string;
  up: string;
  down: string;
  topix: string;
  lines: string[];
  sans: string;
};

const DARK = "(prefers-color-scheme: dark)";

function read(): Palette {
  const style = getComputedStyle(document.documentElement);
  const value = (name: string) => style.getPropertyValue(name).trim();
  return {
    text: value("--text"),
    muted: value("--muted"),
    grid: value("--grid"),
    line: value("--line"),
    up: value("--up"),
    down: value("--down"),
    topix: value("--topix"),
    lines: value("--lines").split(/\s+/),
    sans: value("--sans"),
  };
}

/** The current palette, read again when the system switches between light
 * and dark; null until the page is in the browser. */
export function usePalette(): Palette | null {
  const [palette, setPalette] = useState<Palette | null>(null);

  useEffect(() => {
    setPalette(read());
    if (typeof window.matchMedia !== "function") return; // jsdom has none
    const scheme = window.matchMedia(DARK);
    const changed = () => setPalette(read());
    scheme.addEventListener("change", changed);
    return () => scheme.removeEventListener("change", changed);
  }, []);

  return palette;
}

/** `#1f5bd6` at `alpha` opacity. */
export const faded = (hex: string, alpha: number) => {
  const n = parseInt(hex.replace("#", ""), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};
