import type { Variants } from "framer-motion";

export const smoothEase = [0.22, 1, 0.36, 1] as const;

export const springMotion = {
  type: "spring",
  stiffness: 220,
  damping: 28,
  mass: 0.9
} as const;

export const sectionViewport = {
  once: true,
  amount: 0.2,
  margin: "0px 0px -12% 0px"
} as const;

export const pageTransition = {
  duration: 0.7,
  ease: smoothEase
} as const;

export const sectionReveal: Variants = {
  hidden: { opacity: 1, y: 28, scale: 0.985 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: pageTransition
  }
};

export const staggerContainer: Variants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.05
    }
  }
};

export const subtleItemReveal: Variants = {
  hidden: { opacity: 1, y: 14 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.45,
      ease: smoothEase
    }
  }
};
