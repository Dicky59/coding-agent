"""
Repository Reader Agent — LangGraph Implementation
Phase 1 of the AI Coding Agent

This agent uses the MCP repo-reader tools to analyze a codebase
and answer questions about it.

Flow:
  [User query]
      ↓
  [Planner node]  — decides which tools to call
      ↓
  [Tool executor] — calls MCP tools
      ↓
  [Analyzer node] — synthesizes results into an answer
      ↓
  [Response]
"""

import json
import os
from typing import Annotated, Any, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# ─── Agent State ─────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    repo_path: str
    current_task: str
    analysis_result: str | None


# ─── System prompts ───────────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """You are an expert AI Coding Agent specializing in repository analysis.
You have deep knowledge of:
- Kotlin, Java, Spring Boot, Gradle (backend)
- TypeScript, JavaScript, React, CSS (frontend)
- Kotlin/Android, React Native (mobile)

You have access to these tools for analyzing codebases:

1. **get_repo_summary** — Start here. Get a high-level overview of the repository.
2. **get_repo_structure** — Get the full directory tree.
3. **list_files** — List files filtered by language.
4. **read_file** — Read a specific file's full content.
5. **search_code** — Search for patterns across the codebase.
6. **analyze_file_symbols** — Extract classes, functions, imports from a file.

Strategy:
- Always start with get_repo_summary to understand what you're working with.
- Use get_repo_structure to map the architecture.
- Drill down into specific files that are relevant to the user's question.
- Be thorough but efficient — don't read every file if a targeted search suffices.
- When analyzing Spring Boot projects, look for @RestController, @Service, @Repository patterns.
- When analyzing React projects, look for component structure, hooks, state management.
- When analyzing Android/Kotlin, look for Activity, Fragment, ViewModel, Repository patterns.
"""

ANALYZER_SYSTEM_PROMPT = """You are an expert code analyst. 
Given the tool results from repository analysis, provide a clear, structured answer.
Focus on what's most relevant to the user's original question.
Use concrete examples from the actual code you've seen.
Format your response with clear sections and code snippets where helpful.
"""


# ─── LLM setup ───────────────────────────────────────────────────────────────

def create_llm(tools: list) -> ChatAnthropic:
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_tokens=4096,
    )
    return llm.bind_tools(tools)


# ─── Graph nodes ──────────────────────────────────────────────────────────────

def planner_node(state: AgentState, llm_with_tools) -> AgentState:
    """Decides what tools to call based on the user's question."""
    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        *state["messages"],
    ]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """Route to tools or end based on last message."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "analyzer"


def analyzer_node(state: AgentState) -> AgentState:
    """Synthesizes tool results into a final answer."""
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_tokens=4096,
    )

    # Extract tool results from message history
    tool_results = []
    for msg in state["messages"]:
        if isinstance(msg, ToolMessage):
            tool_results.append(f"Tool: {msg.name}\nResult:\n{msg.content[:3000]}")

    tool_summary = "\n\n---\n\n".join(tool_results) if tool_results else "No tool results."

    analysis_prompt = f"""
Based on the repository analysis results below, answer the user's question.

USER QUESTION: {state["current_task"]}
REPO: {state["repo_path"]}

TOOL RESULTS:
{tool_summary}

Provide a thorough, well-structured analysis.
"""
    response = llm.invoke([
        SystemMessage(content=ANALYZER_SYSTEM_PROMPT),
        HumanMessage(content=analysis_prompt),
    ])

    return {
        "messages": [response],
        "analysis_result": response.content,
    }


# ─── Graph builder ────────────────────────────────────────────────────────────

async def build_agent(mcp_tools: list) -> Any:
    """Builds the LangGraph agent with MCP tools bound."""
    llm_with_tools = create_llm(mcp_tools)
    tool_node = ToolNode(mcp_tools)

    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("planner", lambda state: planner_node(state, llm_with_tools))
    graph.add_node("tools", tool_node)
    graph.add_node("analyzer", analyzer_node)

    # Add edges
    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        should_continue,
        {"tools": "tools", "analyzer": "analyzer"},
    )
    graph.add_edge("tools", "planner")  # Loop back for multi-step reasoning
    graph.add_edge("analyzer", END)

    return graph.compile()


# ─── MCP client setup ─────────────────────────────────────────────────────────

async def create_mcp_client() -> MultiServerMCPClient:
    """Creates the MCP client connected to the repo-reader server."""
    return MultiServerMCPClient(
        {
            "repo-reader": {
                "command": "python",
                "args": ["mcp-server/server.py"],
                "transport": "stdio",
            }
        }
    )


# ─── Main run function ────────────────────────────────────────────────────────

async def analyze_repo(repo_path: str, question: str) -> str:
    """
    Main entry point. Analyzes a repository and answers a question about it.

    Args:
        repo_path: Absolute path to the repository to analyze
        question: Natural language question about the codebase

    Returns:
        Analysis result as a string
    """
    async with create_mcp_client() as mcp_client:
        tools = await mcp_client.get_tools()
        agent = await build_agent(tools)

        initial_state: AgentState = {
            "messages": [HumanMessage(content=question)],
            "repo_path": repo_path,
            "current_task": question,
            "analysis_result": None,
        }

        config = {"recursion_limit": 25}  # Prevent infinite loops
        result = await agent.ainvoke(initial_state, config=config)

        return result.get("analysis_result", "Analysis could not be completed.")


# ─── CLI usage ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) < 3:
        print("Usage: python agent.py <repo_path> <question>")
        print('Example: python agent.py /path/to/my-spring-app "What are the main REST endpoints?"')
        sys.exit(1)

    repo = sys.argv[1]
    query = sys.argv[2]

    print(f"\n🔍 Analyzing: {repo}")
    print(f"❓ Question: {query}\n")
    print("─" * 60)

    result = asyncio.run(analyze_repo(repo, query))
    print(result)
