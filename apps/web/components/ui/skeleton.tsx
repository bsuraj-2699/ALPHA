import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Plain skeleton block. Use the `animate-shimmer` utility (defined in
 * globals.css) for the moving-gradient effect — never a spinner.
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-md bg-card animate-shimmer",
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
