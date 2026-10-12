"""Business logic: pure, unit-testable functions over models + static data.

Deliberately free of MCP and I/O concerns (except carbon, which takes a repository),
so the math can be tested in isolation and the LLM never supplies figures.
"""
