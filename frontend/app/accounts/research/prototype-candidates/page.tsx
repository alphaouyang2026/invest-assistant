import { CandidateResearchPrototype, type PrototypeStep, type PrototypeVariant } from "./prototype";

const VARIANTS: PrototypeVariant[] = ["A", "B", "C"];
const STEPS: PrototypeStep[] = ["draft", "development", "validation", "blind", "challenger"];

export default async function Page({ searchParams }: {
  searchParams: Promise<{ variant?: string; step?: string }>;
}) {
  const query = await searchParams;
  const variant = VARIANTS.includes(query.variant as PrototypeVariant) ? query.variant as PrototypeVariant : "A";
  const step = STEPS.includes(query.step as PrototypeStep) ? query.step as PrototypeStep : "draft";
  return <CandidateResearchPrototype initialVariant={variant} initialStep={step} />;
}
