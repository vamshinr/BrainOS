export interface SeedSource {
  kind: "slack" | "email" | "doc" | "wiki" | "ticket" | "meeting" | "code" | "other";
  title: string;
  content: string;
  url?: string;
}

export const SEED_SOURCES: SeedSource[] = [
  {
    kind: "slack",
    title: "Refund Policy Update",
    content:
      "Hey team, just a heads up on the new refund policy. If a customer requests a refund within 30 days and the product is unused, we approve it automatically via Stripe. Anything past 30 days needs manual approval from Dave in Finance. Do NOT issue refunds manually without the Jira ticket being approved first.",
  },
  {
    kind: "doc",
    title: "Server Deployment Runbook",
    content:
      "When deploying the vLLM container, ensure the GPU device env var (HIP_VISIBLE_DEVICES or CUDA_VISIBLE_DEVICES) is set correctly. The default port is 8081. If you encounter OOM errors, reduce the max_model_len to 4096.",
  },
  {
    kind: "email",
    title: "Pricing API Migration",
    content:
      "To: DevOps\nSubject: Pricing API\nThe Pricing API endpoint has been moved from /v1/prices to /v2/pricing as of last Tuesday. Please update all frontend services. The old v1 endpoint will be completely deprecated by end of Q3.",
  },
  {
    kind: "slack",
    title: "Enterprise Account Ownership",
    content:
      "Who owns the enterprise accounts now that Sarah left?\n\nThread reply from Dave: I'm handling them temporarily until the new VP of Sales starts next month. Ping me for anything above $50k ARR.",
  },
];
