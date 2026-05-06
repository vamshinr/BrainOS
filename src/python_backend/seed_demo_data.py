import json
import os
import uuid

def generate_seed_data():
    """Generates mock Slack, Notion, and Email data for the BrainOS."""
    
    mock_data = [
        {
            "id": str(uuid.uuid4()),
            "source_type": "slack",
            "author": "Alice (Support Lead)",
            "content": "Hey team, just a heads up on the new refund policy. If a customer requests a refund within 30 days and the product is unused, we approve it automatically via Stripe. Anything past 30 days needs manual approval from Dave in Finance. Do NOT issue refunds manually without the Jira ticket being approved first.",
            "timestamp": "2026-05-01T10:00:00Z"
        },
        {
            "id": str(uuid.uuid4()),
            "source_type": "notion",
            "author": "System Admin",
            "content": "Server Deployment Runbook: When deploying the new vLLM container on the MI300X, ensure that HIP_VISIBLE_DEVICES is set to 0. The default port is 8081. If you encounter OOM errors, reduce the max_model_len to 4096.",
            "timestamp": "2026-04-15T08:30:00Z"
        },
        {
            "id": str(uuid.uuid4()),
            "source_type": "email",
            "author": "Bob (Engineering)",
            "content": "To: DevOps\nSubject: Pricing API\nThe Pricing API endpoint has been moved from /v1/prices to /v2/pricing as of last Tuesday. Please update all frontend services. The old v1 endpoint will be completely deprecated by end of Q3.",
            "timestamp": "2026-05-03T14:15:00Z"
        },
        {
            "id": str(uuid.uuid4()),
            "source_type": "slack",
            "author": "Charlie (Sales)",
            "content": "Who owns the enterprise accounts now that Sarah left? \n\nThread reply from Dave: I'm handling them temporarily until the new VP of Sales starts next month. Ping me for anything above $50k ARR.",
            "timestamp": "2026-05-05T09:45:00Z"
        }
    ]

    # Ensure data directory exists relative to project root
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
    os.makedirs(data_dir, exist_ok=True)
    
    file_path = os.path.join(data_dir, "mock_sources.json")
    
    with open(file_path, "w") as f:
        json.dump(mock_data, f, indent=2)
        
    print(f"Successfully generated {len(mock_data)} seed data chunks into {file_path}")

if __name__ == "__main__":
    generate_seed_data()
