import { RunsView } from "@/components/runs/runs-view";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function RunPage({ params }: PageProps) {
  const { id } = await params;
  return <RunsView runId={id} />;
}
