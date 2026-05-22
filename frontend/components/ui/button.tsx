import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-semibold transition duration-200 ease-out hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black disabled:pointer-events-none disabled:translate-y-0 disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-gradient-to-r from-white via-cyan-50 to-pink-50 text-black shadow-[0_18px_55px_rgba(255,255,255,.14)] hover:shadow-[0_0_56px_rgba(34,211,238,.35)]",
        ghost:
          "border border-white/10 bg-white/[0.055] text-white shadow-[inset_0_1px_0_rgba(255,255,255,.08)] backdrop-blur-xl hover:border-white/20 hover:bg-white/[0.095] hover:shadow-[0_18px_50px_rgba(0,0,0,.22)]",
        red:
          "bg-gradient-to-r from-pink-600 via-red-600 to-rose-500 text-white shadow-glow-red hover:shadow-[0_0_72px_rgba(236,72,153,.38)]"
      },
      size: {
        default: "px-5 py-2.5",
        lg: "px-7 py-3 text-base",
        icon: "size-12"
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default"
    }
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";

    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
