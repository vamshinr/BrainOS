"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { ReactNode } from "react";

const SUGGESTED_PROMPTS = [
  "What do we know about our authentication system?",
  "Who owns the data pipeline?",
  "Find gaps in our knowledge about the payments team",
  "Summarize everything we know about our infrastructure",
];

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolsUsed?: string[];
  loading?: boolean;
};

function ToolPills({ tools }: { tools: string[] }) {
  if (!tools.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {tools.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] border border-[var(--border)] px-2 py-0.5 text-[10px] font-mono text-[var(--muted-foreground)]"
        >
          <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
          </svg>
          {t}
        </span>
      ))}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-3 py-2">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-1.5 rounded-full bg-[var(--muted-foreground)] animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(
        <strong key={`${match.index}-strong`} className="font-semibold text-[var(--foreground)]">
          {token.slice(2, -2)}
        </strong>
      );
    } else {
      nodes.push(
        <code
          key={`${match.index}-code`}
          className="rounded bg-[var(--muted)] px-1 py-0.5 font-mono text-[0.86em] text-[var(--foreground)]"
        >
          {token.slice(1, -1)}
        </code>
      );
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

function normalizeMarkdownLine(line: string) {
  return line.replace(/\s+/g, " ").trim();
}

function FormattedAssistantMessage({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    const heading = trimmed.match(/^#{1,4}\s+(.+)$/);
    const boldHeading = trimmed.match(/^\*\*(.+?)\*\*:?\s*$/);

    if (heading || boldHeading) {
      blocks.push(
        <h3
          key={`heading-${i}`}
          className="mt-4 first:mt-0 text-[15px] font-semibold leading-snug text-[var(--foreground)]"
        >
          {renderInlineMarkdown(heading?.[1] ?? boldHeading?.[1] ?? trimmed)}
        </h3>
      );
      i += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: { depth: number; text: string }[] = [];

      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        const itemLine = lines[i];
        const match = itemLine.match(/^(\s*)[-*]\s+(.+)$/);
        if (match) {
          items.push({
            depth: Math.min(2, Math.floor(match[1].length / 2)),
            text: normalizeMarkdownLine(match[2]),
          });
        }
        i += 1;
      }

      blocks.push(
        <div key={`list-${i}`} className="my-3 space-y-2">
          {items.map((item, itemIndex) => {
            const listHeading = item.text.match(/^\*\*(.+?)\*\*:?\s*$/);

            if (listHeading) {
              return (
                <h4
                  key={`${item.text}-${itemIndex}`}
                  className="pt-2 first:pt-0 text-[14px] font-semibold leading-6 text-[var(--foreground)]"
                  style={{ marginLeft: `${item.depth * 14}px` }}
                >
                  {listHeading[1]}
                </h4>
              );
            }

            return (
              <div
                key={`${item.text}-${itemIndex}`}
                className="grid grid-cols-[0.75rem_1fr] gap-2 text-[14px] leading-6 text-[var(--foreground)]"
                style={{ marginLeft: `${item.depth * 14}px` }}
              >
                <span className="mt-[0.55rem] size-1.5 rounded-full bg-[var(--accent)]" aria-hidden="true" />
                <span>{renderInlineMarkdown(item.text)}</span>
              </div>
            );
          })}
        </div>
      );
      continue;
    }

    const paragraph: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !lines[i].trim().match(/^#{1,4}\s+(.+)$/) &&
      !lines[i].trim().match(/^\*\*(.+?)\*\*:?\s*$/)
    ) {
      paragraph.push(normalizeMarkdownLine(lines[i]));
      i += 1;
    }

    blocks.push(
      <p key={`paragraph-${i}`} className="my-3 first:mt-0 last:mb-0 text-[14px] leading-6 text-[var(--foreground)]">
        {renderInlineMarkdown(paragraph.join(" "))}
      </p>
    );
  }

  return <div className="space-y-1">{blocks}</div>;
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      {!isUser && (
        <div className="size-7 shrink-0 rounded-md bg-[var(--accent)] grid place-items-center text-white text-[10px] font-bold mr-2 mt-0.5">
          AI
        </div>
      )}
      <div className={isUser ? "max-w-[70%]" : "w-full max-w-[92%] min-w-0"}>
        <div
          className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? "whitespace-pre-wrap bg-[var(--accent)] text-white rounded-br-sm"
              : "bg-[var(--card)] border border-[var(--border)] text-[var(--foreground)] rounded-bl-sm"
          }`}
        >
          {msg.loading ? (
            <TypingIndicator />
          ) : isUser ? (
            msg.content
          ) : (
            <FormattedAssistantMessage content={msg.content} />
          )}
        </div>
        {!isUser && msg.toolsUsed && msg.toolsUsed.length > 0 && (
          <ToolPills tools={msg.toolsUsed} />
        )}
      </div>
      {isUser && (
        <div className="size-7 shrink-0 rounded-md bg-[var(--muted)] border border-[var(--border)] grid place-items-center text-[var(--muted-foreground)] text-[10px] font-bold ml-2 mt-0.5">
          You
        </div>
      )}
    </div>
  );
}

function EmptyState({ onPrompt }: { onPrompt: (p: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 px-4 text-center">
      <div>
        <div className="size-14 rounded-2xl bg-[var(--accent)] grid place-items-center text-white text-xl font-bold mx-auto mb-3">
          AI
        </div>
        <h2 className="text-lg font-semibold">BrainOS Agent</h2>
        <p className="text-sm text-[var(--muted-foreground)] mt-1 max-w-sm">
          Ask questions, ingest knowledge, find gaps — the agent picks the right tools automatically.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
        {SUGGESTED_PROMPTS.map((p) => (
          <button
            key={p}
            onClick={() => onPrompt(p)}
            className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-left text-sm text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  );
}

const SESSION_KEY = "brainos-agent-session";

type StoredSession = {
  sid: string;
  msgs: Message[];
};

function readStoredSession(): StoredSession | null {
  if (typeof window === "undefined") return null;

  const stored = sessionStorage.getItem(SESSION_KEY);
  if (!stored) return null;

  try {
    const parsed = JSON.parse(stored) as Partial<StoredSession>;
    if (typeof parsed.sid === "string" && Array.isArray(parsed.msgs)) {
      return { sid: parsed.sid, msgs: parsed.msgs as Message[] };
    }
  } catch {
    sessionStorage.removeItem(SESSION_KEY);
  }

  return null;
}

// BrainOS Agent feature is kept in the codebase, but the interactive page is disabled.
// export default function AgentPage() {
export function AgentPageDisabledImplementation() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const restored = readStoredSession();
    if (!restored) return;

    const id = window.setTimeout(() => {
      setSessionId(restored.sid);
      setMessages(restored.msgs);
    }, 0);

    return () => window.clearTimeout(id);
  }, []);

  useEffect(() => {
    if (sessionId && messages.length > 0) {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({ sid: sessionId, msgs: messages }));
    }
  }, [messages, sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;

      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: trimmed,
      };
      const loadingMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        loading: true,
      };

      setMessages((prev) => [...prev, userMsg, loadingMsg]);
      setInput("");
      setLoading(true);

      try {
        // BrainOS Agent feature is kept in the codebase, but calls are disabled.
        // const res = await fetch("/api/agent", {
        //   method: "POST",
        //   headers: { "Content-Type": "application/json" },
        //   body: JSON.stringify({ session_id: sessionId || undefined, message: trimmed }),
        // });
        //
        // if (!res.ok) {
        //   throw new Error(`Server error ${res.status}`);
        // }
        //
        // const data = await res.json();
        //
        // if (!sessionId && data.session_id) {
        //   setSessionId(data.session_id);
        // }
        //
        // const assistantMsg: Message = {
        //   id: crypto.randomUUID(),
        //   role: "assistant",
        //   content: data.reply || "No response.",
        //   toolsUsed: data.tools_used || [],
        // };
        //
        // setMessages((prev) => [...prev.slice(0, -1), assistantMsg]);
        throw new Error("BrainOS Agent feature is disabled");
      } catch (err) {
        const errMsg: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Unknown error"}. Check that the backend is running.`,
          toolsUsed: [],
        };
        setMessages((prev) => [...prev.slice(0, -1), errMsg]);
      } finally {
        setLoading(false);
      }
    },
    [loading]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  const clearSession = () => {
    if (sessionId) {
      // BrainOS Agent feature is kept in the codebase, but session clearing is disabled.
      // fetch(`/api/agent/session/${sessionId}`, { method: "DELETE" }).catch(() => {});
    }
    setMessages([]);
    setSessionId("");
    sessionStorage.removeItem(SESSION_KEY);
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col overflow-hidden md:-mb-24 md:h-screen">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3 shrink-0">
        <div>
          <h1 className="font-semibold text-base">BrainOS Agent</h1>
          <p className="text-[11px] text-[var(--muted-foreground)]">
            Powered by Gemma 4 · auto skill routing
          </p>
        </div>
        {!isEmpty && (
          <button
            onClick={clearSession}
            className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors px-3 py-1.5 rounded-md hover:bg-[var(--muted)] border border-transparent hover:border-[var(--border)]"
          >
            Clear chat
          </button>
        )}
      </div>

      {/* Message area */}
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        {isEmpty ? (
          <EmptyState onPrompt={(p) => { setInput(p); textareaRef.current?.focus(); }} />
        ) : (
          <div className="flex min-h-full w-full flex-col justify-end">
            <div className="mx-auto w-full max-w-4xl">
              {messages.map((msg) => (
                <MessageBubble key={msg.id} msg={msg} />
              ))}
              <div ref={bottomRef} />
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-[var(--border)] bg-[var(--background)]/95 px-4 py-4 backdrop-blur">
        <div className="mx-auto w-full max-w-4xl">
          <div className="flex items-end gap-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 shadow-[0_16px_50px_rgba(0,0,0,0.18)] focus-within:border-[var(--accent)] focus-within:ring-2 focus-within:ring-[var(--accent)]/20">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask BrainOS anything..."
              rows={1}
              className="min-h-10 max-h-36 flex-1 resize-none overflow-y-auto bg-transparent py-2 text-sm leading-6 text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:outline-none disabled:cursor-not-allowed disabled:opacity-70"
              style={{ fieldSizing: "content" } as React.CSSProperties}
              disabled={loading}
            />
            <button
              type="button"
              aria-label={loading ? "Sending" : "Send message"}
              title={loading ? "Sending" : "Send message"}
              onClick={() => send(input)}
              disabled={loading || !input.trim()}
              className="grid size-10 shrink-0 place-items-center rounded-xl bg-[var(--accent)] text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? (
                <svg className="size-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              ) : (
                <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m22 2-7 20-4-9-9-4Z" />
                  <path d="M22 2 11 13" />
                </svg>
              )}
            </button>
          </div>
          <div className="mt-2 flex items-center justify-between px-1 text-[10px] text-[var(--muted-foreground)]">
            <span>Enter to send</span>
            <span>Shift+Enter for newline</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AgentPage() {
  return (
    <main className="flex min-h-[calc(100dvh-3.5rem)] items-center justify-center px-6 py-12 md:min-h-screen">
      <section className="w-full max-w-xl rounded-lg border border-[var(--border)] bg-[var(--card)] p-6">
        <h1 className="text-lg font-semibold">BrainOS Agent disabled</h1>
        <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
          The autonomous agent feature is currently commented out in this build.
        </p>
      </section>
    </main>
  );
}
