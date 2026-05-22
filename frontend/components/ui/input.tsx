import * as React from "react";

import { cn } from "@/lib/utils";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-12 w-full rounded-full border border-white/10 bg-white/[0.065] px-5 text-base text-white shadow-[inset_0_1px_0_rgba(255,255,255,.06)] outline-none backdrop-blur-xl transition duration-200 ease-out file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-slate-400 hover:border-white/20 focus-visible:border-cyan-300/70 focus-visible:bg-white/[0.085] focus-visible:ring-4 focus-visible:ring-cyan-300/10 disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
