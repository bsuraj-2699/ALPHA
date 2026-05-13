import { Briefcase } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";

export default function PortfolioPage() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Portfolio"
        title="Holdings"
        description="Your current book. Position sizes, unrealised P&L, and any active overrides flagged by OVR-O5 / OVR-O4."
        actions={
          <Button variant="outline" size="sm">
            Import positions
          </Button>
        }
      />

      <EmptyState
        icon={Briefcase}
        title="Portfolio is empty"
        description="Connect your broker (or paste positions) to see live P&L. Backed by GET /api/portfolio."
      />
    </div>
  );
}
