# Project_Serina v0.1 最小 Demo 实现说明

## 1. 这份文档是做什么的

前面的文档：

- `01_prd_v0.1.md`
- `02_persona.md`
- `04_dialogue_policy.md`
- `05_architecture.md`

更偏向“产品目标”和“设计原则”。

这份文档的作用是补上另外半边：

> **当前仓库里的代码，究竟是怎么把这些想法落成一个最小可运行程序的。**

你可以把它理解成一份“面向项目主人的源码导览”。

它会回答这些问题：

- 这个 Demo 现在到底能做什么、不能做什么
- 目录结构为什么这样分
- 一条用户消息是怎么流到 DeepSeek，再流回来的
- prompt 是怎么拼出来的
- 为什么没有直接把所有逻辑都塞进 `main.py`
- 为什么现在不急着实现记忆、数据库、scheduler
- 后面要继续扩展，应该从哪里下手

---

## 2. 当前 Demo 的目标边界

这一版实现的是 **Phase 1 的最小可用文本聊天 Demo**。

它已经具备：

- 本地命令行聊天
- 连续多轮对话
- DeepSeek API 接入
- 基于人格配置与对话策略生成回复
- 最近若干轮上下文保留
- 比较清晰的模块拆分

它暂时没有实现：

- 长期记忆
- 数据库存储逻辑
- 主动提醒
- 主动开场
- 联网检索
- 语音输入输出
- Web / GUI

这不是“没做完”，而是**刻意收边界**。

原因很简单：

> v0.1 最重要的是先把“自然私聊 + 稳定人格”跑通，而不是过早把系统做重。

---

## 3. 你可以先把整个系统理解成什么

如果用一句最直观的话说，这个 Demo 现在其实就是下面这个流程：

```text
用户在命令行输入一句话
-> 程序读取配置
-> 程序整理最近几轮聊天记录
-> 程序按照人格和对话策略拼出 prompt
-> 程序调用 DeepSeek chat model
-> 程序对输出做轻量清理
-> 程序把结果显示回命令行
```

再稍微工程化一点，可以理解成：

```text
CLI UI
  -> Coordinator
    -> Dialogue Engine
      -> Prompt Builder
      -> LLM Gateway
        -> DeepSeek Provider
      -> Postprocess
```

这里最重要的一点是：

> **每一层只做自己那一层该做的事。**

这也是后续可扩展的关键。

---

## 4. 当前目录结构怎么理解

当前和这次 Demo 最相关的目录如下：

```text
docs/
  01_prd_v0.1.md
  02_persona.md
  04_dialogue_policy.md
  05_architecture.md
  06_mvp_demo_implementation_guide.md

src/
  app/
    main.py
    coordinator.py
    ui_adapter.py

  config/
    loader.py
    persona_config.yaml
    policy_config.yaml
    runtime_config.yaml

  dialogue/
    engine.py
    prompt_builder.py
    postprocess.py

  llm/
    gateway.py
    providers/
      deepseek.py

  utils/
    logger.py
    text_utils.py
    time_utils.py

  memory/
  scheduler/
  storage/
```

可以把它们理解成三类：

### 4.1 `docs/`

这是“人读的设计文档”。

它们负责表达：

- 这个项目想成为什么
- Serina 应该像什么
- 她怎么说话才算对
- 架构层面为什么这样拆

这些文档是**设计源头**，但不是程序运行时直接输入。

### 4.2 `src/config/`

这是“程序真正读取的结构化配置”。

它负责把设计文档里的抽象描述，变成代码可以消费的数据。

例如：

- 人格名字
- 对用户称呼
- 核心气质
- 禁止风格
- 默认模型
- 温度、超时、历史轮数

### 4.3 `src/...`

这是运行时逻辑。

也就是程序真正工作的地方。

---

## 5. 为什么要有三份 YAML 配置

这一步很关键，因为它体现了一个重要架构思想：

> **不要让程序在运行时直接解析长篇 markdown 设计文档。**

为什么？

因为设计文档适合人读，但不适合程序稳定消费。

例如 `02_persona.md` 里面会有：

- 大段描述
- 示例对话
- 边界说明
- 风格解释

这些很适合你以后继续打磨设定，但不适合每次启动时都拿来“现解析现理解”。

所以现在采用的是“两层结构”：

```text
设计文档（给人读）
-> 抽取成 YAML（给程序读）
-> 代码按 YAML 运行
```

这样做的好处：

- 程序行为更稳定
- 配置字段更明确
- 改设定时更容易知道该改哪里
- 以后可以做配置版本化

---

## 6. 三份 YAML 分别负责什么

### 6.1 `persona_config.yaml`

它描述的是：

> **Serina 是谁。**

这里放的是“人格层”信息，例如：

- `name`
- `user_name`
- `core_traits`
- `relationship_style`
- `tone_rules`
- `forbidden_styles`
- `correction_style`

这类内容的本质是：

- 她的身份感
- 她和用户的关系感
- 她说话的底色
- 她不能滑向哪些错误风格

### 6.2 `policy_config.yaml`

它描述的是：

> **Serina 在不同场景下应该怎么说。**

这里放的是“对话行为层”信息，例如：

- 默认回复风格
- 哪些情况适合短答
- 哪些情况适合展开
- 安慰规则
- 纠偏规则
- 记忆使用边界

人格和策略的区别可以这样理解：

- `persona` 决定“她像谁”
- `policy` 决定“她怎么做”

### 6.3 `runtime_config.yaml`

它描述的是：

> **程序怎么运行。**

例如：

- 使用哪个 provider
- 当前模型是什么
- 预留的 `reasoner_model`
- API key
- base URL
- temperature
- max_tokens
- timeout
- 最大上下文轮数

这是“运行参数层”，不是人格层。

---

## 7. 为什么 `main.py` 很薄

`src/app/main.py` 是程序入口。

它的职责只有几个：

1. 加载配置
2. 初始化日志
3. 初始化 UI 和 Coordinator
4. 进入命令行循环
5. 处理 `exit` / `quit`

它故意不做这些事：

- 不自己拼 prompt
- 不自己管会话历史
- 不直接调 API
- 不自己处理模型输出

为什么？

因为 `main.py` 只应该负责：

> **把应用启动起来。**

如果后面把它塞得很重，会出现两个问题：

- 程序难维护
- 以后 CLI 换 Web 时，逻辑很难复用

这也是为什么 `main.py` 只做“入口”和“循环”，而把业务逻辑交给 `Coordinator`。

---

## 8. `ui_adapter.py` 为什么单独存在

`src/app/ui_adapter.py` 现在看起来很简单，似乎只是包了一层 `input()` 和 `print()`。

但它的意义不在“复杂”，而在“隔离”。

它把 UI 的责任单独收起来了：

- `get_user_input()`
- `display_assistant_message()`
- `display_system_message()`

这样做的价值是：

### 8.1 避免 UI 细节污染业务层

如果以后输出格式变了，例如：

- 换成彩色 CLI
- 换成 Web UI
- 换成桌面窗口

你只需要换适配器层，而不是重写对话逻辑。

### 8.2 保持应用逻辑可迁移

也就是说：

> 现在是 CLI，不代表以后一直只能是 CLI。

---

## 9. `Coordinator` 为什么是核心协调层

`src/app/coordinator.py` 是这次架构里一个非常关键的位置。

它不是模型，不是 UI，也不是配置。

它是：

> **应用协调层。**

你可以把它理解成“程序的大脑外壳”。

当前它负责：

- 接收来自 UI 的用户输入
- 清理输入
- 拿到当前会话历史
- 调用 `DialogueEngine`
- 把本轮 user / assistant 消息加入历史
- 控制只保留最近 N 轮

### 9.1 为什么上下文管理放在这里

因为“当前会话历史”属于应用状态，不属于模型 provider，也不属于 UI。

它更接近“会话管理”。

所以放在 `Coordinator` 最合适。

### 9.2 为什么不直接放到 `DialogueEngine`

因为 `DialogueEngine` 更应该像一个“纯对话生成器”：

- 给它输入
- 给它上下文
- 它返回结果

而不是自己偷偷维护全局状态。

这样后面做测试、重用、扩展会更轻松。

---

## 10. 当前会话上下文是怎么管理的

现在的上下文管理非常克制，只做了最小方案。

核心逻辑：

- 每轮对话保存两条消息
  - 一条 `user`
  - 一条 `assistant`
- 只保留最近 `max_history_turns * 2` 条消息

例如：

如果 `max_history_turns = 8`，那就最多保留：

- 8 轮用户输入
- 8 轮 Serina 回复

总共最多 16 条消息。

### 10.1 为什么用这种最小方式

因为 v0.1 的重点不是做复杂记忆系统，而是：

- 先保证多轮对话能正常延续
- 避免 prompt 无限变长
- 给后续记忆模块留接口

### 10.2 现在没有做什么

目前还没做：

- 会话摘要
- 长期记忆提取
- 相似事件检索
- 最近事件权重管理

这些都属于 v0.2 以后再接的部分。

---

## 11. `DialogueEngine` 的定位

`src/dialogue/engine.py` 是对话生成的总调度器。

它当前做的事情很清晰：

1. 接收：
   - 用户输入
   - 会话上下文
   - 配置
2. 调用 `prompt_builder`
3. 调用 `llm.gateway`
4. 调用 `postprocess`
5. 返回最终结果

所以它不是：

- UI 层
- 配置层
- provider 层

它更像一个“对话编排器”。

### 11.1 为什么这个模块很重要

因为后面很多新能力，理论上都应该接到这里，而不是散落在别处。

例如未来你可能会在这里加：

- 记忆检索
- 会话摘要
- 主动消息生成
- reply quality check
- 安全过滤

所以 `DialogueEngine` 是未来演进的重要支点。

---

## 12. `prompt_builder.py` 是整个项目最“人格相关”的地方

如果说哪一层最直接体现“Serina 像不像 Serina”，那就是 `src/dialogue/prompt_builder.py`。

它干了三件核心事情：

### 12.1 场景判断 `infer_scene`

现在的做法是一个最小启发式规则：

- 命中安慰关键词 -> `comfort`
- 命中纠偏关键词 -> `correction`
- 命中深度讨论关键词 -> `deep_discussion`
- 命中问候关键词且较短 -> `greeting`
- 否则 -> `casual_chat`

这不是复杂 NLP，也不是分类模型。

这是一个故意轻量的实现，因为当前阶段只需要：

> 先把“不同场景下不要都说得一样”这件事做出来。

### 12.2 构造 system prompt

当前 system prompt 不是一个巨大硬编码字符串，而是分块构造的：

- 人格块
- 对话策略块
- 当前场景块
- 记忆边界块
- 输出要求块

这样做有几个好处：

- 更容易读
- 更容易改
- 不容易变成“字符串拼接地狱”
- 以后更容易插入记忆模块、反思模块

### 12.3 组装最终 messages

最后它会得到：

- 一条 `system`
- 若干历史 `user/assistant`
- 当前这轮 `user`

然后把它们打包成 `PromptPackage`，交给后面的模型调用层。

---

## 13. 为什么 system prompt 要分块

这是一个值得特别学一下的点。

很多初学时常见的做法是：

```text
把所有人格、规则、限制、格式、禁令都塞进一个超长字符串
```

这种方式短期能跑，但长期会越来越难维护。

所以这次实现刻意拆成几个清晰块：

### 13.1 人格块

回答“她是谁”。

### 13.2 策略块

回答“她怎么说”。

### 13.3 场景块

回答“这一轮重点是什么”。

### 13.4 记忆边界块

回答“什么能用、什么不能假装有”。

### 13.5 输出块

回答“模型最后该怎么出字”。

这背后的思想其实就是：

> **把 prompt 也当成一种可维护的程序结构，而不是一次性文本。**

---

## 14. `postprocess.py` 为什么很轻

`src/dialogue/postprocess.py` 只做了几件小事：

- 清理多余空白
- 去掉 `Serina:` / `助手:` 这类机械前缀
- 去掉明显的 AI 自我声明开头
- 防止空回复

它故意不做复杂 NLP。

为什么？

因为当前后处理的目标不是“重写模型输出”，而是：

> **做最低限度的清洁，避免破坏自然感。**

如果后处理太重，会出现一个问题：

- 模型原本写得自然
- 后处理反而把它改怪了

所以目前只做轻量修整，这是合理的。

---

## 15. `LLMGateway` 为什么要存在

很多人刚开始写这种项目时，会直接在业务代码里写 API 调用。

例如在 `DialogueEngine` 里直接：

- 组织 HTTP 请求
- 发请求
- 解析 JSON
- 抛异常

这短期能跑，但架构上不够干净。

所以这里加了 `src/llm/gateway.py`。

它的作用是：

> **隔离“业务层”与“模型 provider 细节”。**

这样上层只需要关心：

- 我有一组 messages
- 我想要一段回复

而不用关心：

- URL 是什么
- headers 怎么拼
- HTTP 错误怎么处理
- 哪个 provider 在底层工作

### 15.1 未来的价值

以后如果你要加：

- OpenAI
- Claude
- 本地模型
- chat / reasoner 路由

只需要改 gateway/provider 层，而不是把整个上层业务改一遍。

---

## 16. `deepseek.py` 当前的实现原理

`src/llm/providers/deepseek.py` 采用的是：

> **OpenAI 兼容风格的 `/chat/completions` 调用。**

核心请求参数包括：

- `model`
- `messages`
- `temperature`
- `max_tokens`
- `stream = False`

### 16.1 为什么用标准库 `urllib`

当前实现没有强依赖 `requests` 或 OpenAI SDK。

这是有意为之：

- 依赖更少
- 更容易在一个干净环境里跑起来
- 调用过程更透明

当然，后面如果你更想要：

- 更舒服的错误处理
- 重试策略
- 流式输出

那时再换 SDK 也完全可以。

### 16.2 provider 现在支持什么

它现在只支持：

- DeepSeek chat completions

但配置里已经预留了：

- `model: deepseek-chat`
- `reasoner_model: deepseek-reasoner`

这意味着后面做 chat / reasoner 的切换时，不需要重新改配置结构。

---

## 17. `loader.py` 为什么比较长

`src/config/loader.py` 是当前代码里相对“工程味”更强的一个文件。

因为它负责：

- 读 YAML
- 校验字段
- 转 dataclass
- 处理错误

### 17.1 为什么要用 dataclass

因为配置不是随手读个字典就结束了。

如果后面到处都是：

```python
config["persona"]["name"]
config["runtime"]["timeout"]
```

会有几个问题：

- 字段拼错时不容易发现
- 代码可读性差
- 结构边界不清晰

所以这里把配置分成了几个 dataclass：

- `PersonaConfig`
- `PolicyConfig`
- `RuntimeConfig`
- `AppConfig`

这样读起来就更清楚：

```python
config.persona.name
config.runtime.model
config.policy.comfort_rules
```

### 17.2 为什么还写了一个“最小 YAML 解析器”

这个点很实用。

正常情况下，Python 项目会直接依赖 `PyYAML`。

但为了让这个 Demo 在“尽量少依赖”的环境下也能跑起来，当前 loader 做了两层处理：

1. 优先尝试 `PyYAML`
2. 如果没有安装，就退回到一个内置的最小 YAML 解析器

这个 fallback 解析器不是通用 YAML 引擎，它只支持当前这几份配置实际用到的简单结构：

- 顶层映射
- 嵌套映射
- 字符串列表
- 数字 / 布尔 / 空值

这样做的目的是：

> 保证最小 Demo 尽量“不因为缺一个依赖就起不来”。

---

## 18. `utils/` 里的几个工具文件分别有什么意义

### 18.1 `logger.py`

负责统一日志初始化。

现在只做控制台日志，但已经留了以后接文件日志的入口。

### 18.2 `text_utils.py`

放一些轻量文本处理函数，例如：

- 空白规范化
- 去角色前缀
- 去 AI 自我声明
- 关键词匹配
- 日志预览截断

这类函数如果散落在各处，会很快变乱，所以集中到这里。

### 18.3 `time_utils.py`

主要提供：

- 当前本地时间
- 时间段判断（早上/中午/下午/晚上/深夜）

然后在 prompt 里注入“当前时间上下文”。

这类信息虽然简单，但很适合独立出来，因为以后：

- 主动问候
- 晚间追问
- 时间敏感表达

都会依赖这层。

---

## 19. 一条消息从输入到输出，完整经历了什么

这是最值得牢牢记住的主链路。

### 第 1 步：用户输入

在 CLI 中输入一句话，例如：

```text
你好
```

### 第 2 步：`main.py`

`main.py` 读取这句话，并把它交给 `Coordinator`。

### 第 3 步：`Coordinator`

`Coordinator` 做几件事：

- 清理输入
- 读取当前会话历史
- 调用 `DialogueEngine`

### 第 4 步：`DialogueEngine`

`DialogueEngine` 调用 `prompt_builder`：

- 判断当前场景
- 构造 system prompt
- 拼接历史对话
- 添加当前 user 输入

### 第 5 步：`LLMGateway`

`DialogueEngine` 把 messages 交给 `LLMGateway`。

### 第 6 步：`DeepSeekProvider`

provider 发 HTTP 请求到 DeepSeek：

```text
POST /chat/completions
```

拿回模型响应。

### 第 7 步：`postprocess`

对模型输出做轻量清理。

### 第 8 步：返回给 `Coordinator`

`Coordinator` 把：

- 当前 user 消息
- 当前 assistant 消息

一起加入会话历史。

### 第 9 步：UI 显示

CLI 输出：

```text
Serina > 老师，晚上好呀。
```

这就是当前 Demo 的完整生命线。

---

## 20. 为什么现在没有真正实现 memory / scheduler / storage

这是一个非常重要的架构判断题。

因为这三个模块一旦认真做，复杂度会迅速上升：

- memory 需要写入规则、读取规则、衰减规则、检索规则
- scheduler 需要时间判断、打扰边界、频率控制
- storage 需要 schema、迁移、查询接口

如果在 v0.1 一开始就把这些全部做满，会很容易出现：

- 代码很多
- 体验却不一定更好
- 人格和对话反而没有先打磨稳

所以当前策略是：

> **先为这些模块预留位置，但不假装它们已经实现。**

这也是为什么你会在代码里看到：

- `memory_service = None`
- `scheduler_service = None`
- `memory_write_candidate = None`
- `proactive_followup_candidate = None`

它们不是废代码，而是明确的扩展接口。

---

## 21. 当前设计里最重要的几个原则

### 21.1 单一职责

每个文件做一类事：

- 入口是入口
- 协调是协调
- prompt 是 prompt
- provider 是 provider

### 21.2 先最小闭环，再做大系统

先保证：

- 能启动
- 能聊天
- 有人格方向
- 有最近上下文

再逐层加记忆和主动性。

### 21.3 不假装未实现能力

这是这次实现里一个非常重要的态度。

比如：

- 没有长期记忆，就明确说没有
- 没有 scheduler，就不要伪装主动关心已经来自真实计划系统
- 没有数据库，就不要做一堆“像是有”的假接口

这种克制会让后续版本更健康。

### 21.4 结构先于功能堆叠

有时“多做点功能”看起来像进展，但如果结构不对，后面会越来越难改。

所以这次优先保证：

- 模块边界正确
- 数据流清晰
- 后续能自然扩展

---

## 22. 如果你想自己读源码，建议按这个顺序

这是最推荐的阅读顺序：

### 第一轮：先看程序怎么跑起来

1. `src/config/runtime_config.yaml`
2. `src/app/main.py`
3. `src/app/ui_adapter.py`
4. `src/app/coordinator.py`

这样你先知道入口和主循环。

### 第二轮：看回复怎么生成

5. `src/dialogue/engine.py`
6. `src/dialogue/prompt_builder.py`
7. `src/dialogue/postprocess.py`

这样你会明白“人格 + 场景 + 上下文”是怎么进入模型的。

### 第三轮：看模型怎么调用

8. `src/llm/gateway.py`
9. `src/llm/providers/deepseek.py`

这样你会知道代码如何和外部模型服务连接。

### 第四轮：看底层支撑

10. `src/config/loader.py`
11. `src/utils/text_utils.py`
12. `src/utils/time_utils.py`
13. `src/utils/logger.py`

这样你会知道工程上的支撑层是怎么搭起来的。

---

## 23. 你可以如何理解“架构”和“实现原理”的区别

这个问题对后续学习很有帮助。

### 23.1 架构

架构回答的是：

- 模块怎么拆
- 数据怎么流
- 谁依赖谁
- 哪些能力现在不做
- 未来扩展从哪里接

例如：

- 有 `Coordinator`
- 有 `DialogueEngine`
- provider 被放到 `llm/providers/`

这些都属于架构。

### 23.2 实现原理

实现原理回答的是：

- 场景是怎么判断的
- prompt 是怎么拼的
- HTTP 请求怎么发的
- 上下文是怎么裁剪的

例如：

- `infer_scene()` 用关键词分类
- `postprocess_response()` 轻量清洗输出
- `DeepSeekProvider` 用 `urllib` 发请求

这些属于实现原理。

### 23.3 两者的关系

可以这么记：

- 架构 = 地图
- 实现原理 = 地图上每个站点是怎么工作的

---

## 24. 后续比较自然的演进路线

如果以后继续迭代，比较推荐按下面的顺序：

### 24.1 先补可观察性

例如：

- 保存日志到文件
- 增加 prompt 调试开关
- 增加当前 scene 输出开关

这样后面调人格时会轻松很多。

### 24.2 再补“最小记忆”

建议不要一上来做复杂向量检索。

更稳的路线是：

- 最近事件记录
- 简单长期偏好档案
- 很少量的人工规则读取

### 24.3 再补主动性

建议在记忆稍微稳定后再做：

- 晚间追问
- 约定提醒
- 低频主动开场

因为主动性如果没有“记忆依据”，会很容易显得像脚本。

### 24.4 最后再考虑语音 / GUI

因为这些更多是“入口形式变化”，不应该抢在核心对话体验之前。

---

## 25. 当前实现的已知局限

这份文档也需要诚实地指出当前不足。

### 25.1 场景识别仍然很粗

现在只是关键词启发式，不是高精度分类器。

优点是简单稳定。

缺点是：

- 有时会误判
- 有时过于粗粒度

### 25.2 还没有做回复质量自检

虽然 prompt 已经约束风格，但还没有额外的“生成后再检查一遍像不像 Serina”的模块。

### 25.3 还没有做 prompt 长度管理策略

现在只有最近 N 轮裁剪，没有摘要机制。

### 25.4 还没有把 `reasoner_model` 用起来

目前只是预留字段。

也就是说：

- 配置结构支持了
- 路由策略还没写

### 25.5 API key 目前是明文放在本地配置里

这对私人本地项目是可以接受的临时方案，但长期仍建议更多依赖环境变量。

---

## 26. 这一版实现最值得你学会的，不是语法，而是这几个思路

如果从“以后能继续自己推进项目”的角度看，我最希望你真正学到的是下面这些思路。

### 26.1 先定义边界，再写代码

不是一上来就写，而是先明确：

- 这一版做什么
- 不做什么

### 26.2 让设计文档和运行配置分层

不要让“给人看的描述”直接成为“给程序吃的输入”。

### 26.3 让每层只做自己的职责

这会让项目越做越顺，而不是越做越乱。

### 26.4 先做可运行的最小闭环

只要链路先跑通，后续迭代就有抓手。

### 26.5 不假装复杂能力已经存在

这会让系统更诚实，也更容易升级。

---

## 27. 一句话总结当前这套实现

> **这套 v0.1 最小 Demo 的核心价值，不在于它做了多少功能，而在于它已经把“人格配置 -> prompt 组织 -> 模型调用 -> 多轮会话”这条主链路，用一种清晰、可扩展、不过度设计的方式搭起来了。**

如果后面要继续做下去，这条链路就是整个 Project_Serina 的第一根主骨架。

