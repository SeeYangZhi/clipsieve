import { type ClassValue, cn as mergeClassNames } from "cn";

/** Merge Tailwind classes; target of the shadcn `utils` alias in components.json. */
export function cn(...inputs: ClassValue[]): string {
  return mergeClassNames(...inputs);
}
