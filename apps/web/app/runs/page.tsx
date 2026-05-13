import * as React from "react";

import { StrategyRunsView } from "@/components/runs/strategy-runs-view";

export default function RunsIndexPage() {
  // The view reads `?mode=` and renders a strategy-bucket queue. We
  // wrap in Suspense because Next 15 requires it for `useSearchParams`.
  return (
    <React.Suspense fallback={null}>
      <StrategyRunsView />
    </React.Suspense>
  );
}
