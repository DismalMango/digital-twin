# digital-secretary

[中文](README.md)

`digital-secretary` is an auto-reply Agent for Feishu. It combines large language models (LLMs), a personal knowledge base, and retrieval-augmented generation (RAG), so the Agent can retrieve relevant context before composing a reply. The goal is to produce responses that better match the user's background, communication style, and current context.

The project extends [nanobot](https://github.com/HKUDS/nanobot). nanobot provides the Agent runtime, tool calling, message channels, and scheduled jobs. This repository adds the Feishu bridge, diary knowledge-base indexing, hybrid retrieval, and a LangGraph-based RAG flow.

## Project goal

This project aims to build a personal auto-reply system that can be connected to Feishu. When a Feishu message is received, the Agent parses the conversation, retrieves relevant information from diary entries, long-term memory, and workspace files, and then uses an LLM to generate a reply that fits the user's tone and context.

The system is not intended to be a generic chatbot. It is an auto-reply Agent with personal context awareness. Its long-term goal is to help handle low-risk, repetitive communication while preserving the user's expression style and background information.

## Core capabilities

- Connects to Feishu private chats, monitors chat changes, and converts Feishu messages into events that the Agent can process.
- Uses LLMs to generate replies, with support for providers such as OpenRouter, Anthropic, and OpenAI.
- Reads Markdown diary files from `~/.nanobot/workspace/diary/` as a personal knowledge source.
- Performs hybrid retrieval with ChromaDB, OpenAI embeddings, BM25, jieba tokenization, and a reranker.
- Uses LangGraph to decide whether a query needs RAG and injects retrieved context when needed.
- Reuses nanobot's Agent loop, tools, memory files, channels, cron jobs, and CLI.

## Workflow

```text
Feishu message
  -> feishu_bridge monitors and converts events
  -> nanobot message bus dispatches the message
  -> Agent decides whether personal context is needed
  -> agentic_search retrieves relevant diary and memory snippets
  -> LLM generates a reply with the retrieved context
  -> The reply is returned through the Feishu response flow
```

## Project structure

```text
agentic_search/   Diary indexing, vector retrieval, BM25, reranker, and LangGraph RAG nodes
feishu_bridge/    Feishu chat monitoring, event bridge, and data schemas
nanobot/          Agent runtime, CLI, channels, cron, config, memory, and tools
diary/            Synthetic diary data generation scripts
tests/            Tests for the RAG graph and RAG node
```

## Installation

Python 3.11 or later is required.

```bash
uv sync
```

You can also install the project as a local package:

```bash
pip install .
```

Install development dependencies:

```bash
uv sync --extra dev
```

## Configuration

Initialize the local config and workspace:

```bash
digital-secretary onboard
```

Then configure the LLM provider API key in `~/.nanobot/config.json`. Diary RAG currently uses the OpenAI API for embeddings, so `OPENAI_API_KEY` is also required:

```bash
export OPENAI_API_KEY="..."
```

Diary files should be placed in:

```text
~/.nanobot/workspace/diary/
```

The Agent also reads `SOUL.md`, `USER.md`, and `memory/MEMORY.md` from the workspace. These files describe the persona, user information, and long-term memory.

Feishu-related features depend on a locally available `lark-cli` and require Feishu identity authorization.

## Usage

Run a local Agent conversation:

```bash
digital-secretary agent -m "Help me reply to this Feishu message"
```

Start the gateway for channels and scheduled jobs:

```bash
digital-secretary gateway
```

Check the current status:

```bash
digital-secretary status
```

Manage scheduled jobs:

```bash
digital-secretary cron list
digital-secretary cron add "0 9 * * *" "Summarize today's communication items"
```

## Relationship with nanobot

nanobot provides a lightweight personal Agent foundation. This project keeps its runtime and CLI while focusing its extensions on Feishu auto-reply and personal RAG: Feishu is the message entry point, diary and memory files provide context, and the LLM generates the final reply.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=DismalMango/digital-twin&type=Date)](https://star-history.com/#DismalMango/digital-twin&Date)

## License

MIT
