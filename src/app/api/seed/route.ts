import { SEED_SOURCES } from "@/lib/seed-data";
import {
  extractFromSource,
  ingestSourceShape,
  mergeIntoState,
  reconcileUnit,
} from "@/lib/extractor";
import { mutate } from "@/lib/store";
import { hasGatewayCreds } from "@/lib/ai";

export const runtime = "nodejs";
export const maxDuration = 600;

export async function POST() {
  if (!hasGatewayCreds()) {
    return new Response(
      JSON.stringify({ error: "No AI credentials configured." }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: Record<string, unknown>) => {
        controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
      };

      send({ type: "start", total: SEED_SOURCES.length });

      let totalUnits = 0;
      let totalEntities = 0;

      for (let i = 0; i < SEED_SOURCES.length; i++) {
        const seed = SEED_SOURCES[i];
        send({ type: "source:start", index: i, title: seed.title, kind: seed.kind });

        const source = ingestSourceShape(seed);
        let extraction;
        try {
          extraction = await extractFromSource(source);
        } catch (e) {
          send({ type: "source:error", index: i, error: String(e) });
          continue;
        }

        await mutate(async (state) => {
          const reconciliations = new Map<
            string,
            { supersedes: string[]; isDuplicate: boolean }
          >();
          for (const u of extraction.units) {
            try {
              const r = await reconcileUnit(u, state.units);
              reconciliations.set(u.id, r);
            } catch {
              reconciliations.set(u.id, { supersedes: [], isDuplicate: false });
            }
          }
          return mergeIntoState(
            state,
            source,
            extraction.entities,
            extraction.units,
            reconciliations,
          );
        });

        totalUnits += extraction.units.length;
        totalEntities += extraction.entities.length;
        send({
          type: "source:done",
          index: i,
          title: seed.title,
          units: extraction.units.length,
          entities: extraction.entities.length,
        });
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
