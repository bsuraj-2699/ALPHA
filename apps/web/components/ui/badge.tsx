import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider transition-colors",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-secondary text-secondary-foreground",
        outline: "text-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
        buy: "border-transparent bg-buy/15 text-buy ring-1 ring-inset ring-buy/30",
        sell: "border-transparent bg-sell/15 text-sell ring-1 ring-inset ring-sell/30",
        warn: "border-transparent bg-warn/15 text-warn ring-1 ring-inset ring-warn/30",
        gold: "border-transparent bg-gold/15 text-gold ring-1 ring-inset ring-gold/40",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
