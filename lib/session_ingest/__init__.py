"""Gated session ingestion: distil quiet harness sessions into candidate captures.

A transcript never enters the archive. Each reader streams one harness's session files
and keeps only typed prompts, assistant text and tool names; the excerpt module bounds
and cleans that. A reader is any module with TOOL, LANE_PREFIX, list_transcripts(home)
and scan(path, cwd_check=None); a Codex reader plugs in here with prefix codex-memory.
"""
from . import claude_code

READERS = {"claude-code": claude_code}
