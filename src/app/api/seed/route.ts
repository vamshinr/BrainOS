import { SEED_SOURCES } from "@/lib/seed-data";
import { invalidateCache } from "@/lib/store";

export const runtime = "nodejs";
export const maxDuration = 600;

export async function POST() {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: Record<string, unknown>) =>
        controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));

      send({ type: "start", total: SEED_SOURCES.length });

      let totalUnits = 0;
      let totalEntities = 0;

      for (let i = 0; i < SEED_SOURCES.length; i++) {
        const seed = SEED_SOURCES[i];
        send({ type: "source:start", index: i, title: seed.title, kind: seed.kind });

        try {
          // Route through the Python backend so extraction runs on the 70B model
          // on the AMD MI300X and embeddings land in ChromaDB.
          const res = await fetch(`${BACKEND_URL}/api/ingest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              kind: seed.kind,
              title: seed.title,
              content: seed.content,
              url: seed.url,
            }),
          });

          if (!res.ok) {
            const errText = await res.text();
            throw new Error(`Backend ${res.status}: ${errText}`);
          }

          const data = await res.json();

          // Invalidate the Next.js cache after every write so the dashboard
          // always reflects the state Python just persisted to brain.json.
          invalidateCache();

          totalUnits += data.units_stored ?? 0;
          totalEntities += data.entities_stored ?? 0;

          send({
            type: "source:done",
            index: i,
            title: seed.title,
            units: data.units_stored ?? 0,
            entities: data.entities_stored ?? 0,
          });
        } catch (e) {
          send({ type: "source:error", index: i, title: seed.title, error: String(e) });
        }
      }

      send({ type: "done", totalUnits, totalEntities });
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson",
      "Cache-Control": "no-cache",
    },
  });
}
