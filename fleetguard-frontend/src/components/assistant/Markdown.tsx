/**
 * The assistant's replies, rendered.
 *
 * The agent is told to answer in Markdown and to use tables when it compares
 * three or more things, so the panel has to render tables properly - a reply
 * that arrives as pipes and dashes reads as a broken product, and the
 * comparison is the part a fleet manager actually wanted.
 *
 * Every element is styled explicitly rather than through a typography plugin.
 * The panel is a 27rem column, which is narrower than any prose default
 * assumes: the type scale, the table padding and the list indents here are all
 * chosen for that width.
 *
 * Raw HTML is never rendered. `react-markdown` ignores it unless a plugin is
 * added to allow it, and none is - model output goes through the same door as
 * any other untrusted string.
 */

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/cn";

const COMPONENTS: Components = {
  p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0 leading-6">{children}</p>,

  h1: ({ children }) => (
    <h3 className="mb-1.5 mt-4 text-[0.9375rem] font-medium text-ink first:mt-0">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mb-1.5 mt-4 text-[0.875rem] font-medium text-ink first:mt-0">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mb-1 mt-3.5 text-[0.8125rem] font-medium text-ink first:mt-0">{children}</h4>
  ),
  h4: ({ children }) => (
    <h4 className="mb-1 mt-3 text-[0.8125rem] font-medium text-ink first:mt-0">{children}</h4>
  ),

  strong: ({ children }) => <strong className="font-medium text-ink">{children}</strong>,
  em: ({ children }) => <em className="italic text-muted">{children}</em>,

  ul: ({ children }) => (
    <ul className="my-2 list-disc space-y-1 pl-4 marker:text-faint first:mt-0 last:mb-0">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-2 list-decimal space-y-1 pl-4 marker:text-faint first:mt-0 last:mb-0">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="leading-6 [&>p]:my-0">{children}</li>,

  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-hairline pl-3 text-muted">{children}</blockquote>
  ),

  hr: () => <hr className="my-3 border-hairline" />,

  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-accent-ink underline underline-offset-2"
    >
      {children}
    </a>
  ),

  // A narrow panel cannot widen for a six-column table, so the table scrolls
  // inside its own box rather than pushing the conversation sideways.
  table: ({ children }) => (
    <div className="scroll-thin my-2.5 overflow-x-auto rounded-lg border border-hairline first:mt-0 last:mb-0">
      <table className="w-full border-collapse text-[0.75rem]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-canvas">{children}</thead>,
  tr: ({ children }) => <tr className="border-b border-hairline last:border-0">{children}</tr>,
  th: ({ children, style }) => (
    <th
      style={style}
      className="whitespace-nowrap px-2.5 py-1.5 text-left font-medium text-muted"
    >
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    // Figures are the reason the table exists; tabular numerals keep the
    // columns of digits aligned the way they are on every other screen.
    <td style={style} className="tabular px-2.5 py-1.5 align-top text-ink">
      {children}
    </td>
  ),

  code: ({ children }) => (
    <code className="rounded bg-canvas px-1 py-0.5 font-mono text-[0.75rem] text-ink">
      {children}
    </code>
  ),
  // The wrapper carries the block treatment and flattens the chip styling off
  // whichever `code` element lands inside it.
  pre: ({ children }) => (
    <pre
      className={cn(
        "scroll-thin my-2.5 overflow-x-auto rounded-lg border border-hairline bg-canvas",
        "px-3 py-2.5 font-mono text-[0.75rem] leading-5 text-ink first:mt-0 last:mb-0",
        "[&_code]:bg-transparent [&_code]:p-0 [&_code]:text-[inherit]",
      )}
    >
      {children}
    </pre>
  ),
};

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("text-[0.8125rem] text-ink", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
