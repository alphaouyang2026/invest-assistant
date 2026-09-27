"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";

/** The top bar's reminder of how fresh the data is; a link to the data page. */
export function DataBadge() {
  const [latest, setLatest] = useState<string | null | undefined>(undefined); // undefined: not read yet

  useEffect(() => {
    void (async () => {
      const { data } = await api.GET("/api/data/status");
      setLatest(data ? data.latest_date : null);
    })();
  }, []);

  if (latest === undefined) return null;
  return (
    <Link href="/data" className={latest ? "badge ok" : "badge warn"} style={{ textDecoration: "none" }}>
      <span className="dot" />
      {latest ? `数据至 ${latest}` : "尚无数据"}
    </Link>
  );
}
