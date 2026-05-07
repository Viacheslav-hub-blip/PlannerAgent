# Portable Hermes-Inspired Patterns

This package extracts the most reusable Hermes Agent runtime patterns into
standalone Python modules that can be embedded into other agent stacks,
including LangChain and LangGraph projects.

## What Was Copied From Hermes

### Tool runtime

- Central registry with tool schemas and handlers
- Runtime availability checks
- Toolset-based surface shaping
- Safe async-to-sync bridging for tool handlers
- Structured dispatch errors instead of raw exceptions

Source inspiration:
- `tools/registry.py`
- `model_tools.py`

### Memory system

- Frozen prompt snapshot loaded once per session
- Live memory writes that only affect the next session snapshot
- Separate `memory` and `user` stores
- Recalled memory fenced as background context
- One built-in memory store plus optional external providers

Source inspiration:
- `tools/memory_tool.py`
- `agent/memory_manager.py`
- `agent/memory_provider.py`

### Skills system

- Progressive disclosure: list metadata first, load full skill later
- Skill directory layout: `SKILL.md`, `references/`, `templates/`, `scripts/`, `assets/`
- YAML frontmatter with machine-readable metadata
- Safe create/edit/patch/delete flow
- Prompt-friendly skill index instead of injecting all skill contents

Source inspiration:
- `tools/skills_tool.py`
- `tools/skill_manager_tool.py`
- `agent/skill_utils.py`

### Self-improvement loop

- Periodic memory nudges
- Tool-iteration-based skill nudges
- Background post-turn review after the user already got the answer
- Review worker that writes back into memory/skills

Source inspiration:
- `run_agent.py` review prompts and `_spawn_background_review()`

## Package Layout

- `tool_runtime.py`: registry and toolset layer
- `memory.py`: memory store, provider contract, memory manager
- `skills.py`: skills store and skill editing workflow
- `self_improvement.py`: nudge counters and background reviewer
- `langchain.py`: optional StructuredTool wrappers
- `langgraph.py`: optional node factories for StateGraph-style flows

## Suggested Integration Pattern

### 1. At session start

- Load `MemoryStore.load_from_disk()`
- Build a stable system prompt using:
  - identity / system policy
  - `memory_store.format_for_system_prompt("memory")`
  - `memory_store.format_for_system_prompt("user")`
  - `skills_store.build_system_prompt(...)`

### 2. Before each model call

- Ask `memory_manager.prefetch_all(user_message)`
- Inject the result via `build_memory_context_block()`
- Keep this out of the stable system prompt

### 3. During execution

- Route tool calls through `ToolRegistry.dispatch()`
- Reset memory/skill counters when the relevant tools are actually used

### 4. After the turn completes

- Sync external memory providers
- Check `ReviewNudger` for memory/skill review triggers
- Spawn `BackgroundReviewer.spawn_review(...)`

## LangGraph Sketch

```python
from portable_agent_patterns.langgraph import (
    make_counter_update_node,
    make_post_turn_review_node,
    make_prefetch_memory_node,
)

prefetch_memory = make_prefetch_memory_node(memory_manager)
update_counters = make_counter_update_node(nudger)
post_turn_review = make_post_turn_review_node(reviewer)
```

## LangChain Sketch

```python
from portable_agent_patterns.langchain import build_memory_tools, build_skill_tools

tools = []
tools.extend(build_memory_tools(memory_store))
tools.extend(build_skill_tools(skills_store))
```

