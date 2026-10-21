import { ResearchWorkspace, type Mode } from "./research-workspace";

const MODES: Mode[] = ["manual", "regime", "experiment"];

export default async function Page({ searchParams }: {
  searchParams: Promise<{ source?: string; run?: string; mode?: string; discovery?: string; batch?: string; experiment?: string }>;
}) {
  const query = await searchParams;
  const mode = MODES.find(m => m === query.mode) ?? "manual";
  // Keyed on the run so a segment's 查看详情 link, which lands on this same route, reloads the workspace.
  return <ResearchWorkspace key={query.run ?? ""} sourceId={query.source ?? ""} initialRun={query.run ?? ""}
    initialMode={mode} initialDiscovery={query.discovery ?? ""} initialBatch={query.batch ?? ""}
    initialExperiment={query.experiment ?? ""} />;
}
