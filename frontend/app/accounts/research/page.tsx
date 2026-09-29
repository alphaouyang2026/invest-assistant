import { ResearchWorkspace } from "./research-workspace";

export default async function Page({ searchParams }: {
  searchParams: Promise<{ source?: string; run?: string }>;
}) {
  const query = await searchParams;
  return <ResearchWorkspace sourceId={query.source ?? ""} initialRun={query.run ?? ""} />;
}
