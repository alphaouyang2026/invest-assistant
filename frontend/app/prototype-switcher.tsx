"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

type Variant = { key: string; name: string };

export function PrototypeSwitcher({ variants, current }: { variants: Variant[]; current: string }) {
  const router = useRouter();
  const index = Math.max(0, variants.findIndex(variant => variant.key === current));

  function go(offset: number) {
    const next = variants[(index + offset + variants.length) % variants.length];
    const url = new URL(window.location.href);
    url.searchParams.set("variant", next.key);
    router.replace(`${url.pathname}?${url.searchParams.toString()}`);
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, [contenteditable='true']")) return;
      if (event.key === "ArrowLeft") go(-1);
      if (event.key === "ArrowRight") go(1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (process.env.NODE_ENV === "production") return null;
  const active = variants[index];
  return <div className="prototype-switcher" role="group" aria-label="Mock 方案切换">
    <button type="button" onClick={() => go(-1)} aria-label="上一个方案">←</button>
    <span><b>{active.key}</b> {active.name}</span>
    <button type="button" onClick={() => go(1)} aria-label="下一个方案">→</button>
  </div>;
}
