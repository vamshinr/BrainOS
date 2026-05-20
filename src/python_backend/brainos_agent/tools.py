BRAINOS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_brain",
            "description": (
                "Query the BrainOS knowledge graph to answer questions about people, systems, "
                "processes, ownership, decisions, or policies. Use this when the user asks WHAT "
                "we know, WHO owns something, HOW something works, or WHY a decision was made. "
                "This READS from the brain — it does not add new information."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The natural language question to answer using stored knowledge",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ingest_text",
            "description": (
                "Add new information, facts, decisions, or policies into the BrainOS knowledge graph. "
                "Use this when the user says 'remember this', 'store this', 'add this info', or pastes "
                "raw text to be learned. This WRITES to the brain — do not use it to answer questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The raw text content to ingest",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title for this knowledge source",
                    },
                },
                "required": ["text", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_gaps",
            "description": (
                "Scan the knowledge graph for missing information: entities with no owner, "
                "undescribed systems, orphan gotchas, or open disputes. Use when the user asks "
                "'what are we missing', 'find gaps', 'what don't we know', or 'what needs attention'. "
                "No LLM call — fast and deterministic."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_graph_summary",
            "description": (
                "Return a structured summary of entities and relationships in the knowledge graph. "
                "Use when the user asks to 'show the graph', 'what connects to X', 'map relationships', "
                "or 'list all systems/teams/people'. Returns entity counts and key relationships."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_filter": {
                        "type": "string",
                        "description": "Optional entity name to focus on (e.g. 'auth system'). Leave empty for full summary.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_skills",
            "description": (
                "Generate a full SKILLS.md file from the BrainOS knowledge graph using the platform's "
                "generateSkills engine. The output includes: agent rules, ownership routing, policies, "
                "processes, gotchas, decisions, temporal notes, knowledge graph relationships, confidence "
                "scores, source index, and code map — all scoped to a department or the whole company. "
                "Use when the user asks to 'generate skills file', 'create agent context', 'export knowledge "
                "for team X', 'make SKILLS.md', 'what would an agent know about X', or 'give me the agent "
                "rules for Y team'. Valid departments: engineering, product, legal, finance, hr, sales, "
                "marketing, operations, security, general."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {
                        "type": "string",
                        "description": (
                            "Department to scope the skills file to. Must be one of: engineering, product, "
                            "legal, finance, hr, sales, marketing, operations, security, general. "
                            "Leave empty for all departments."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_failures",
            "description": (
                "Run anomaly and failure detection over the knowledge graph. Use when the user asks "
                "about 'failures', 'what broke', 'anomalies', 'incidents', or 'problems'."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metrics",
            "description": (
                "Return live GPU and model performance metrics: tokens/sec, latency, cache utilization. "
                "Use when the user asks about 'GPU performance', 'model speed', 'how fast is inference', "
                "'throughput', or 'metrics'."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in BRAINOS_TOOLS}

