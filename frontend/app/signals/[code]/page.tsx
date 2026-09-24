import { SecurityDetail } from "../security-detail";
import { DEFAULT_STRATEGY, STRATEGIES, type StrategyName } from "@/lib/labels";

const known = (name: string | undefined): name is StrategyName => STRATEGIES.some((s) => s.name === name);

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ strategy?: string }>;
}) {
  const { code } = await params;
  const { strategy } = await searchParams;
  return <SecurityDetail code={code} strategy={known(strategy) ? strategy : DEFAULT_STRATEGY} />;
}
