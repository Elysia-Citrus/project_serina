# 05_architecture.md

> **本文档反映 v0.1 架构设计，已不作为当前实现的事实描述。**
> 当前 v0.2 代码的现实以以下文档为准：
> - `docs/00_product_overview.md` —— 当前能力范围与设计原则
> - `docs/01_repo_guide.md` —— 仓库结构与模块导览
> - `docs/17_voice_cli_usage.md` —— 语音 CLI 运行形态
> - `docs/13_assist_llm_lane.md` —— 辅助 LLM 通道
> - `docs/11_reply_guard_regression_hardening.md` —— 回复护栏系统

## 1. 文档目的

本文档最初用于定义 Project_Serina v0.1 的整体架构。当前代码已经越过纯文本 v0.1：语音 CLI、session memory、assist-llm lane 和本地 TTS runtime 都已进入仓库。下面的 v0.1 叙事保留为架构来路。

它回答的问题不是“她说什么”，而是：

- 这个程序由哪些模块组成
- 各模块分别负责什么
- 数据如何在模块之间流动
- v0.1 的最小实现边界在哪里
- 哪些设计是为了给 v0.2 的语音与环境感知预留空间

本文档的目标是：

> 让 Project_Serina 在 v0.1 阶段具备一个清晰、可扩展、不过度复杂的最小可用架构。

---

## 2. 架构目标

Project_Serina v0.1 的架构需要满足以下目标：

### 2.1 独立于社交平台
核心逻辑不依附于 QQ 或其他 IM 平台。  
Serina 应首先是一个独立程序，而不是某个平台内的 bot。

### 2.2 支持人格、记忆、主动性分层
程序必须天然支持以下三层能力：

- 人格层
- 记忆层
- 主动性层

这三者不能揉成一团写在一个 prompt 里。

### 2.3 文本主链路优先，语音复用主链路
文本入口仍是最小稳定链路。  
当前语音入口已经通过 `src/app/main_voice.py` 和 `src/voice/` 接入，并复用 `Coordinator / DialogueEngine / MemoryManager / ReplyGuard`。

### 2.4 本地优先，部署灵活
v0.1 优先支持本地运行。  
同时允许后续迁移到远程服务器或“本地前端 + 远程后端”的模式。

### 2.5 保持轻量
v0.1 不引入复杂的分布式系统、重型中间件或大规模检索系统。  
优先使用简单、可控、可调试的实现方案。

---

## 3. v0.1 的总体边界

v0.1 原始边界只做以下事情：

- 单用户文本对话
- 基础人格控制
- 基础记忆写入与读取
- 定时提醒与轻主动消息
- 基础日志与配置管理

当前仍不追求：

- 环境感知
- 联网检索
- 多用户系统
- 群聊支持
- 复杂向量检索
- 多 Agent 协同

语音能力已经存在，但定位是本地 voice CLI 和本地 runtime 工具链，不是常驻多模态平台。

因此，架构必须优先服务“稳定可用”，而不是“能力堆满”。

---

## 4. 总体架构概览

Project_Serina v0.1 的推荐总体架构如下：

```text
[ Text UI / Local Web UI / Desktop Chat Window ]
                    |
                    v
               [ Serina App ]
                    |
    -----------------------------------------
    |            |            |             |
    v            v            v             v
[ Dialogue ] [ Memory ] [ Scheduler ] [ Config/Persona ]
[ Engine   ] [ Manager] [ Manager   ] [ Loader         ]
    |            |            |             |
    -------------------|---------------------
                        v
                 [ LLM Gateway ]
                        |
                        v
                 [ DeepSeek API ]

                    +------------------+
                    |     Storage      |
                    |------------------|
                    | profile_memory   |
                    | recent_memory    |
                    | relationship_mem |
                    | convo_summary    |
                    | schedules        |
                    | logs             |
                    +------------------+
```


## 5. 核心模块划分

v0.1 建议拆成 7 个核心模块。

### 5.1 UI Layer

作用

负责用户可见的文本交互界面。

v0.1 推荐形态

任选其一即可：

本地 Web 聊天页面
简单桌面聊天窗口
终端聊天界面（仅供早期调试）
职责
接收用户输入
展示 Serina 回复
展示基础聊天历史
可选地提供“手动保存记忆”“查看摘要”“查看日志”等调试入口
不应承担的职责
不直接操作模型
不直接读写复杂记忆逻辑
不直接实现主动性逻辑

UI 只负责“展示与输入”。

### 5.2 Serina App（应用协调层）
作用

作为 v0.1 的主应用层，负责协调各个模块。

职责
接收来自 UI 的消息
调用 Dialogue Engine 生成回复
调用 Memory Manager 进行记忆检索与写入
调用 Scheduler Manager 处理提醒与主动消息
调用 Config/Persona Loader 加载设定
管理程序生命周期
定位

Serina App 是“程序主脑”，但不是“内容生成器”。
它更像一个 orchestration layer。

### 5.3 Dialogue Engine（对话引擎）
作用

负责把“当前输入 + 人格 + 记忆 + 对话策略”组合成一次模型调用，并输出最终回复。

职责
分析当前用户输入
判断本轮对话属于什么场景
从 Memory Manager 获取相关记忆
从 Persona 配置中读取人格约束
组装 prompt
调用 LLM Gateway
对模型输出做基础后处理
核心输入
用户当前输入
当前会话上下文
人格配置
对话策略
检索到的相关记忆
核心输出
Serina 的文本回复
可选的记忆写入候选
可选的会话摘要候选
可选的主动性追问候选
v0.1 约束

Dialogue Engine 不负责真正保存记忆，它只负责“生成”和“建议”。

### 5.4 Memory Manager（记忆管理器）
作用

负责 Serina 的记忆写入、读取、摘要、衰减与升格。

职责
管理 profile_memory
管理 recent_memory
管理 relationship_memory
管理 conversation_summary
根据规则判断哪些内容值得写入
根据当前话题判断哪些记忆值得调取
执行记忆衰减、过期、摘要沉淀与升格
设计原则

Memory Manager 必须遵守：

记忆服务于连续陪伴，不服务于信息囤积
读取以自然为优先，不以展示能力为优先
允许遗忘
允许轻微模糊
允许把重复问题抽象成模式
v0.1 最重要的功能
维护近 7 天活跃事件记忆
对 14 天内事件进行弱衰减
保存长期档案偏好
保存少量关系记忆
### 5.5 Scheduler Manager（调度与主动性管理器）
作用

负责提醒、晚间追问、轻主动消息等时间驱动行为。

职责
管理定时提醒
管理晚间问候与复盘
管理对白天提到事项的追问
判断当前时间是否适合主动发言
限制主动消息频率
防止主动性失控
设计原则

主动性应当：

自然
克制
有理由
低频
不打扰用户高专注场景
v0.1 范围

只实现 B 级主动性：

定时问候
晚间追问
简单提醒
轻量主动开场

### 5.6 Config / Persona Loader（配置与人格加载器）
作用

负责加载项目配置、人格文档、对话规则和行为边界。

职责
加载 02_persona.md 的结构化版本
加载 04_dialogue_policy.md
加载模型配置
加载主动性参数
加载记忆规则参数
向其他模块提供统一配置访问接口
说明

在工程实现上，Markdown 文档不应直接作为运行时输入。
更合理的方式是：

Markdown 作为人类可编辑文档
再抽取出一份结构化配置（如 JSON/YAML/Python dict）供程序使用
### 5.7 LLM Gateway（模型网关）
作用

负责封装对大模型服务的调用。

职责
统一调用 DeepSeek API
封装请求参数
控制模型切换
处理错误重试
记录模型调用日志
隔离上层业务与具体 API 细节
好处

这样上层只关心：

给模型什么输入
要什么输出

而不用反复处理：

请求格式
token 参数
超时与失败
模型名称切换
v0.1 建议

默认使用单一主模型即可。
后续若要增加“复杂场景切换推理模型”，只改 Gateway，不改核心业务层。

## 6. 存储层设计

v0.1 建议采用轻量存储。

推荐方案：

SQLite 作为主存储
本地文件作为补充配置存储
日志以文件形式保存

### 6.1 建议的数据域
profile_memory

保存稳定档案：

兴趣
厌恶
长期目标
偏好
特殊日期
稳定设定
recent_memory

保存近日事件：

事件内容
时间戳
权重
类别
是否可提醒
是否已过期
是否已升格
relationship_memory

保存共同历史：

共同梗
重要对话节点
设定修改
双方共同记忆片段
conversation_summary

保存会话摘要：

会话时间
摘要内容
主题
情绪标签（可选）
后续跟进点（可选）
schedule_items

保存提醒与约定：

事项内容
时间点
提醒窗口
是否完成
是否重复提醒
logs

保存程序日志：

消息输入
回复输出
记忆写入
记忆读取
主动任务触发
模型调用情况
## 7. 关键数据流
### 7.1 被动对话流程

用户输入
  -> UI Layer
  -> Serina App
  -> Dialogue Engine
      -> 读取 Persona / Dialogue Policy
      -> infer_scene
      -> 向 Memory Manager 请求少量相关记忆
      -> 组装 prompt
      -> 调用 LLM Gateway
      -> postprocess
      -> reply_guard（rewrite / retry once / safe fallback）
      -> 得到回复
  -> 返回回复给 UI
  -> Memory Manager 在回合结束后判断是否写入
  -> 生成会话摘要候选
  -> 写入 conversation_summary

说明

这是 v0.1 最核心的主链路。
它必须尽量简单、可调试、可观察。

补充说明

- memory 的读取发生在生成前
- memory 的写入发生在本轮完成后
- reply_guard 不引入第二个 LLM，只做低成本规则检查与一次保守重试

### 7.2 主动消息流程
定时器触发 / 调度轮询
  -> Scheduler Manager
  -> 检查当前时段是否适合主动发言
  -> 查询 recent_memory / schedule_items
  -> 判断是否存在值得追问或提醒的内容
  -> 调用 Dialogue Engine 生成主动消息
  -> 通过 UI 推送或展示
  -> 记录日志
说明

主动性不是独立模型能力，而是：

时间条件
记忆条件
频率限制
风格控制

共同作用的结果。

### 7.3 记忆衰减与整理流程
后台定时任务
  -> Memory Manager
  -> 扫描 recent_memory
  -> 对超过窗口的项目降权
  -> 对重复事件做摘要沉淀
  -> 对重要事件做升格
  -> 对过期无价值项目归档或删除
说明

这一步可以低频运行。
不需要每条消息都触发。

## 8. Prompt 组装策略

v0.1 不建议把所有要求硬塞进一个 system prompt。
推荐拆成以下几部分：

### 8.1 Persona Block

来自 02_persona.md 的核心人格约束，包括：

她是谁
她的语气
她和老师的关系
她的表达边界
### 8.2 Dialogue Policy Block

来自 04_dialogue_policy.md，包括：

长答/短答策略
安慰、提醒、批评时的风格
禁止项
当前场景规则
### 8.3 Memory Context Block

由 Memory Manager 动态注入，包括：

当前相关的档案记忆
当前相关的近日事件
当前相关的关系记忆
最近会话摘要
### 8.4 User Input Block

当前用户输入。

### 8.5 Optional Reflection Block

可选，用于需要更谨慎表达时加入一层简短内部约束，例如：

不要客服腔
不要过度说教
有批评时保持温柔诚实
9. v0.1 的工程目录建议
project_serina/
├─ docs/
│  ├─ 01_prd_v0.1.md
│  ├─ 02_persona.md
│  ├─ 03_memory_design.md
│  ├─ 04_dialogue_policy.md
│  └─ 05_architecture.md
├─ src/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ main_voice.py
│  │  ├─ runtime.py
│  │  ├─ coordinator.py
│  │  └─ ui_adapter.py
│  ├─ dialogue/
│  │  ├─ engine.py
│  │  ├─ prompt_builder.py
│  │  └─ postprocess.py
│  ├─ memory/
│  │  ├─ manager.py
│  │  ├─ writer.py
│  │  ├─ reader.py
│  │  ├─ decay.py
│  │  └─ summarizer.py
│  ├─ scheduler/
│  │  ├─ manager.py
│  │  ├─ reminder.py
│  │  └─ proactive.py
│  ├─ llm/
│  │  ├─ gateway.py
│  │  └─ providers/
│  │     └─ deepseek.py
│  ├─ config/
│  │  ├─ loader.py
│  │  ├─ models.py
│  │  ├─ validators.py
│  │  ├─ yaml_utils.py
│  │  ├─ persona_config.yaml
│  │  ├─ policy_config.yaml
│  │  ├─ runtime_config.yaml
│  │  ├─ voice_config.yaml
│  │  ├─ voice_profiles.yaml
│  │  └─ local_tts_runtime.yaml
│  ├─ voice/
│  │  ├─ controller.py
│  │  ├─ recorder.py
│  │  ├─ asr.py
│  │  ├─ synthesis.py
│  │  ├─ tts.py
│  │  ├─ playback.py
│  │  └─ local_runtime_server.py
│  ├─ storage/
│  │  ├─ db.py
│  │  ├─ models.py
│  │  └─ repositories.py
│  └─ utils/
│     ├─ logger.py
│     ├─ time_utils.py
│     └─ text_utils.py
└─ data/
   ├─ serina.db
   └─ logs/

## 10. v0.1 的推荐实现顺序
Step 1

先跑通最小文本对话链路：

UI
Serina App
Dialogue Engine
LLM Gateway
Step 2

接入最小记忆：

profile_memory
recent_memory
conversation_summary
Step 3

加入关系记忆与记忆衰减：

relationship_memory
recent_memory 的 7~14 天衰减机制
Step 4

加入主动性：

晚间追问
约定提醒
低频主动开场
Step 5

补日志、测试与可观察性。

## 11. v0.2 预留接口

语音已经从预留接口升级为当前子系统。环境感知仍是未来预留。

推荐未来扩展为：

[ Voice Input / Microphone / Endpoint / ASR ]
                    |
                    v
               [ Serina App ]
                    |
    -----------------------------------------
    |            |            |             |
    v            v            v             v
[ Dialogue ] [ Memory ] [ Scheduler ] [ Voice Runtime ] [ Context Sensing ]
[ Engine   ] [ Manager] [ Manager   ] [ Local TTS     ] [ (future)        ]
预留原则
UI 层可替换
Dialogue Engine 不依赖“输入来自文本还是语音”
Memory Manager 不依赖“事件来自键盘还是麦克风”
Scheduler Manager 可接入更多状态判断

## 12. 非目标

以下不是 v0.1 架构的追求方向：

高并发
多用户权限系统
插件生态
分布式架构
多模型路由编排
复杂 RAG 平台
实时多模态系统

Project_Serina v0.1 是一个面向单用户的私人程序。
它首先要“像她”，其次才是“像一个很大的系统”。

## 13. 架构评估标准

如果这套架构设计是好的，那么它应当满足：

逻辑清楚，模块边界明确
后续人格、记忆、主动性都能独立迭代
文本入口和语音入口能共享同一条对话核心
代码不会因为平台变化而重写
调试时能看清每一步发生了什么
v0.1 不会因为过度设计而迟迟无法落地

## 14. 一句话总结

Project_Serina v0.1 的架构，应当先把她做成一个清晰、可扩展、独立存在的程序核心，再让人格、记忆与主动性逐层长出来。
