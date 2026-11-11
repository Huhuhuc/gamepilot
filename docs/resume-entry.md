# GamePilot 简历项目表述

## 可直接使用的项目条目

**GamePilot｜基于真实 Godot 游戏的任务型 Agent 与自动评测环境**  
个人项目｜Python、Godot 4、GDScript、Gymnasium、Stable-Baselines3、Ollama / OpenAI-compatible API

- 基于 Godot 2D 生存射击游戏接入 Gymnasium 环境，建立 76 维结构化状态、移动/射击双离散动作接口及显式 reset、terminated、truncated 语义；保留真实游戏的碰撞、敌人、道具和战斗结算逻辑。
- 将游戏目标配置为 4 类带版本与 SHA-256 内容指纹的任务（限时击杀、生存、受伤上限、拾取并生存），实现确定性任务裁判；支持随机、规则、PPO 与 LLM 策略按相同任务和固定种子进行逐局对照，区分游戏失败、外部截断和执行错误。
- 实现独立 LLM 工具调用 Agent，支持 Ollama 与 OpenAI-compatible Chat Completions；通过严格 `step_game` 参数校验、单次格式修复、单局请求/Token 预算和请求超时约束动作执行，Provider 异常、无效动作与游戏结果分别计量。
- 记录任务/代码哈希、逐局 JSON/CSV、动作与状态 trace、模型延迟、请求量和 Token 用量，生成 HTML 汇总；用模拟 HTTP 服务覆盖协议解析、超时、畸形参数、预算耗尽与错误请求计数。
- 增加离线配对比较器，拒绝不同任务哈希、重复或不匹配的种子集；对齐随机/规则/PPO 与 LLM 的逐局结果，报告有效样本、Wilson 95% 区间及配对成功差异，并明确不把描述统计写成显著性结论。

## 验证状态

当前自动化测试为 40 项通过，包含真实 Godot 环境测试。规则策略经 LLM 工具接口适配后的真实游戏 smoke 在 seed 2000 达成 `kill_target`：29.47 秒完成 20 杀。另用模拟 Provider 验证从 LLM 评测 CLI 到跨运行配对报告的完整数据链。上述结果只证明工程和 grader 集成，不是语言模型表现。

截至 2026-11-11，本机 Ollama 服务不可用，尚未完成真实模型调用和 LLM 对照评测。投递简历时不要写模型成功率、LLM 超过基线、模型效果提升或真实 token 成本；完成实际模型运行后再补测试集结果、模型版本、日期、无效局比例和成本。

## 面试时的贡献边界

项目复用了 Godot RL Agents 的环境协议思路和 Stable-Baselines3 PPO 实现，没有自研 PPO 或训练基础大模型。LLM Agent 目前读取结构化游戏状态，不是视觉 Agent；没有多 Agent 协作、长期记忆或代码执行。个人实现重点是游戏环境适配、任务定义与裁判、受限工具执行、异常/预算控制和可复现评测。
