# Minimal Research Agent Examples

This folder contains no-UI smoke examples for the research agent.

Run from the repository root:

```powershell
python examples\chat_run.py
```

The example uses `FakeListChatModel`, so it does not call an external LLM.

Files:

- `chat_run.py` - builds `ResearchAgent` and runs it through `ainvoke`.
- `fake_spark_tools.py` - ordinary LangChain tools that imitate slow Spark exports.
- `data/cspfs_repo_features3.hits_extra_info_129372427_view.csv` - bundled anti-fraud hit table loaded into `df_current`.
- `skills/insight-design/SKILL.md` - compact skill/design note loaded into the skills index.
- `memory/*.md` - small frozen memory files loaded by `context_builder`.
- `runs/` - output folder for generated `ResearchRun`, lineage snapshots, and artifacts.

This example is intentionally simple. It demonstrates the backend chat path:

```text
LangChain invoke -> AgentState -> LangGraph agent -> list[BaseMessage]
```

Branching and UI are not required for this path.

`fake_spark_tools.py` is intended for intermediate testing before real Spark
integrations exist. The tools are normal LangChain tools and do not know
anything about research-agent artifacts. Large returned lists are captured by
the agent runtime and saved as artifacts automatically.
