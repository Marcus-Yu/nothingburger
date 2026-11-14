"""Tests never send traces or call a model, whatever is in .env."""
import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["AGENT_NO_MODEL"] = "1"
