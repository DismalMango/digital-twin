# digital-secretary

[English](README_EN.md)

`digital-secretary` 是一个面向飞书场景的自动回复 Agent。项目结合大语言模型（LLM）、个人知识库与检索增强生成（RAG），使 Agent 能够在生成回复前检索相关上下文，从而输出更符合用户背景、表达习惯和当前状态的回复内容。

本项目基于 [nanobot](https://github.com/HKUDS/nanobot) 进行扩展。nanobot 提供 Agent 运行时、工具调用、消息通道和定时任务等基础能力；本项目在此基础上增加了飞书桥接、日记知识库索引、混合检索以及 LangGraph RAG 流程。

## 项目目标

本项目旨在构建一个可接入飞书的个人自动回复系统。当飞书收到消息时，Agent 会先解析对话内容，再从个人日记、长期记忆和工作区资料中检索相关信息，最后由 LLM 生成符合用户语气和上下文的回复。

该系统并非通用聊天机器人，而是一个具备个人上下文感知能力的自动回复 Agent。长期目标是在保留用户表达风格和背景信息的前提下，辅助处理日常沟通中的低风险、重复性消息。

## 主要能力

- 接入飞书私聊列表，监听聊天变化，并将飞书消息转换为 Agent 可处理的事件。
- 使用 LLM 生成回复，底层支持 OpenRouter、Anthropic 和 OpenAI 等 provider。
- 从 `~/.nanobot/workspace/diary/` 读取 Markdown 日记，作为个人知识库来源。
- 使用 ChromaDB、OpenAI embedding、BM25、jieba 分词和 reranker 进行混合检索。
- 通过 LangGraph 判断当前问题是否需要 RAG，并在需要时注入检索结果。
- 复用 nanobot 的 Agent loop、工具、记忆文件、channel、cron 和 CLI。

## 工作流程

```text
飞书消息
  -> feishu_bridge 监听并转换事件
  -> nanobot message bus 分发消息
  -> Agent 判断是否需要检索个人上下文
  -> agentic_search 从日记和记忆中召回相关片段
  -> LLM 结合上下文生成回复
  -> 返回到飞书回复链路
```

## 项目结构

```text
agentic_search/   日记索引、向量检索、BM25、reranker 和 LangGraph RAG 节点
feishu_bridge/    飞书聊天监听、事件桥接和数据结构
nanobot/          Agent 运行时、CLI、通道、定时任务、配置、记忆和工具
diary/            合成日记数据生成脚本
tests/            RAG graph 和 RAG node 的测试
```

## 安装

需要 Python 3.11 或更高版本。

```bash
uv sync
```

也可以通过本地包方式安装：

```bash
pip install .
```

安装开发依赖：

```bash
uv sync --extra dev
```

## 配置

初始化本地配置和工作区：

```bash
digital-secretary onboard
```

然后在 `~/.nanobot/config.json` 中配置 LLM provider 的 API key。日记 RAG 中的 embedding 当前使用 OpenAI 接口，因此还需要设置：

```bash
export OPENAI_API_KEY="..."
```

日记文件存放在：

```text
~/.nanobot/workspace/diary/
```

Agent 还会读取工作区中的 `SOUL.md`、`USER.md` 和 `memory/MEMORY.md`，这些文件用于描述人设、用户信息和长期记忆。

飞书相关能力依赖本地可用的 `lark-cli`，并需要完成飞书身份授权。

## 使用

运行一次本地 Agent 对话：

```bash
digital-secretary agent -m "帮我回复这条飞书消息"
```

启动 gateway，用于通道和定时任务：

```bash
digital-secretary gateway
```

查看当前状态：

```bash
digital-secretary status
```

管理定时任务：

```bash
digital-secretary cron list
digital-secretary cron add "0 9 * * *" "整理今天需要注意的沟通事项"
```

## 与 nanobot 的关系

nanobot 提供轻量级个人 Agent 基座。本项目保留其运行时和 CLI 能力，并将主要扩展方向集中在飞书自动回复与个人 RAG 上：飞书负责消息入口，日记和记忆提供上下文，LLM 负责生成最终回复。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=DismalMango/digital-twin&type=Date)](https://star-history.com/#DismalMango/digital-twin&Date)

## License

MIT
