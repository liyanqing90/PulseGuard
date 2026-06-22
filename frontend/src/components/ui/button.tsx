import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-[var(--radius-tight)] border text-sm font-medium outline-none transition-[background-color,border-color,color,box-shadow,opacity,transform] duration-[var(--duration-fast)] ease-[var(--ease-out)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color-mix(in_srgb,var(--pg-accent)_72%,white)] focus-visible:shadow-[var(--focus-ring)] disabled:pointer-events-none disabled:opacity-55 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-[var(--pg-accent)] bg-[var(--pg-accent)] text-[var(--on-accent)] hover:border-[var(--accent-deep)] hover:bg-[var(--accent-deep)]",
        outline: "border-[var(--line)] bg-[var(--panel)] text-[var(--ink)] hover:border-[var(--pg-accent)] hover:text-[var(--accent-deep)]",
        secondary: "border-[var(--line)] bg-[var(--panel-strong)] text-[var(--ink)] hover:bg-[var(--panel)]",
        ghost: "border-transparent bg-transparent text-[var(--pg-muted)] hover:border-[var(--line)] hover:bg-[var(--panel-strong)] hover:text-[var(--ink)]",
        destructive: "border-[var(--danger-soft)] bg-[var(--danger-soft)] text-[var(--danger)] hover:border-[var(--danger)]",
        link: "border-transparent bg-transparent p-0 text-[var(--pg-accent)] hover:text-[var(--accent-deep)]"
      },
      size: {
        default: "h-9 px-3",
        sm: "h-8 px-2.5 text-[0.8125rem]",
        lg: "h-10 px-3.5",
        icon: "h-9 w-9 p-0",
        nav: "h-[46px] min-w-0 flex-col gap-[3px] px-1 py-[5px] text-xs leading-[1.1]"
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default"
    }
  }
);

const Button = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> &
    VariantProps<typeof buttonVariants> & {
      asChild?: boolean;
    }
>(({ className, variant = "default", size = "default", asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot.Root : "button";
  return <Comp ref={ref} data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />;
});
Button.displayName = "Button";

export { Button, buttonVariants };
