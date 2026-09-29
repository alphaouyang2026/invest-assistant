import { ResearchWorkspace } from "./research-workspace";

export default async function Page({ searchParams }: {
  searchParams: Promise<{ source?: string; run?: string; mode?: string; discovery?: string; batch?: string }>;
}) {
  const query = await searchParams;
  // Keyed on the run so a segment's 查看详情 link, which lands on this same route, reloads the workspace.
  return <ResearchWorkspace key={query.run ?? ""} sourceId={query.source ?? ""} initialRun={query.run ?? ""}
    initialMode={query.mode === "regime" ? "regime" : "manual"}
    initialDiscovery={query.discovery ?? ""} initialBatch={query.batch ?? ""} />;
}
