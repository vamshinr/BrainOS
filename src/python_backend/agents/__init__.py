"""Agent singletons — import these everywhere instead of instantiating locally."""
from agents.ingestion import IngestionAgent
from agents.structuring import StructuringAgent
from agents.execution import ExecutionAgent
from agents.feedback import FeedbackAgent

ingest_agent    = IngestionAgent()
struct_agent    = StructuringAgent()
exec_agent      = ExecutionAgent()
feedback_agent  = FeedbackAgent()
