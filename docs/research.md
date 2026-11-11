# Voyager 与 Godot RL Agents：针对胡宸凡的项目选型

研究日期：2026-10-18。状态：已阅读论文主要方法、实验与局限，核对核心实现及用户游戏源码；尚未运行两个上游系统，也没有训练出新策略。以下是选型与设计，不是复现实验结果。

## 结论

选择 Godot RL Agents 路线，以用户的 `Huhuhuc/2dshootgame` 为环境，制作 GamePilot：强化学习自动试玩与难度评测项目。

理由是已有两个大模型应用项目，下一项适合展示环境建模、训练、评测和游戏工程联调。用户已有射击游戏源码，能控制观测、动作、奖励、重置和日志，个人贡献比仅跑上游 Minecraft 示例更清楚。此结论针对当前作品组合，不代表 RL 比 LLM Agent 更适合所有岗位。

如果目标改为只投 LLM Agent 应用开发，Voyager 路线与技能记忆、工具编排、反馈修复更直接对应；GamePilot 不能被描述成大模型训练、RLHF 或开放世界自主学习项目。

## 阅读依据及冻结版本

| 来源 | 本次获取的提交 | 已核对内容 |
|---|---|---|
| MineDojo/Voyager | `55e45a880755d0c8c66ca7fb5fe7962ac8974f89` | README、FAQ、安装、主循环、Action/Critic/SkillManager、课程模块、Python/Mineflayer 桥接 |
| edbeeching/godot_rl_agents | `207b6f476f5846f33d08b92c7a350147e7b78bf5` | README、论文、自定义环境、训练建议、SB3 示例、GodotEnv 与 SB3 wrapper |
| 该仓库固定的插件子模块 | `3984fd124a2b941a446f4614bb0eacd09a2468f5` | 旧 Sync，协议 minor 0.3，未包含当前 AIController 文件结构 |
| 插件当前 main | `998c357a0cd09b37f40a36d70c7867fc9f682338` | AIController2D、Sync、ONNX 包装，协议 minor 0.7 |
| Huhuhuc/2dshootgame | `1ce73ad946302e61e87060d4a9a3ef44d4af106a` | project.godot、player/game/enemy/bullet、配置与项目说明 |
| Huhuhuc/rougelike-test | `fc90e176ff0f3c740b1beda63522e58beea341d2` | 文件树，作为后续策略对照项目候选，未深入复核战斗实现 |
| Huhuhuc/2dmoveinggame | `728f428dd2433be8b6a1714f8deeeaa11a5e84f0` | 当前远端树仅 README，不能据此接入横版游戏 |

原始阅读缓存在外层工作区 docs/research/game-agent-2026-10-18；本项目保留此阅读记录及原始链接。下载不等于全部文件都读过；主要实现阅读范围按上表记录。保留原始文件用于个人研究，不把这些文件当作本项目原创实现。

## Voyager：真正值得学的结构

1. `Voyager.learn()` 请求下一个任务，执行受次数限制的 rollout。成功后将代码交给 SkillManager，再更新完成/失败任务记录。
2. ActionAgent 把观测、前次代码、环境反馈和 critique 组织成提示；用 Babel 解析返回的 JavaScript，抽取接受 bot 参数的 async 函数。语法结构检查不等于安全沙箱或语义正确性。
3. CriticAgent 根据结构化游戏状态判断成功并提出 critique；执行报错直接判失败。论文承认成功判定与任务生成也会出错。
4. SkillManager 保存技能代码和描述，以 OpenAIEmbeddings + Chroma 检索相关技能，默认 top-5。这里的“学习”主要是积累可执行程序和上下文复用，不是 PPO 更新网络权重。
5. Python 通过本地 HTTP 调用 Node/Mineflayer，再操作 Minecraft。观测主要来自结构化状态；不能描述成直接看屏幕、模拟键鼠的视觉 Agent。
6. 上游测试基于 Minecraft 1.19 与特定 Fabric/mod 组合。现有依赖接口较旧，更换模型不是只替换 API key：还涉及聊天封装、输出解析、Embedding 服务和模型表现验证。

原 FAQ 的约 160 轮、50 美元是历史 GPT-4 运行估计，不能当作 2026 年 DeepSeek 的报价。当前成本需在具体适配后记录真实调用量。Minecraft 游戏许可/登录、Java/Node/mod 联调也是该方向的前置条件，目前没有检查用户已授权的游戏账户。

可参考的改进方向是：为确定性任务增加程序检查器，记录技能版本与成功率，限制每次执行和费用，评估禁用技能库的消融。但这是另一条完整路线，本次不同时实施。

## Godot RL Agents：应当复用的结构

1. Godot 持有真实游戏状态；AIController 提供 `get_obs/get_reward/get_action_space/set_action`。
2. Sync 按 action_repeat 同步，TCP 传输动作、观测和结果，Python 侧包装为训练环境。
3. SB3 的 PPO 是可复用算法实现，个人工作应集中在环境、奖励、实验和错误处理，不宣称原创 PPO。
4. 相对位置、数值归一化和简单奖励是上游明确建议；第一版采用结构化状态，避免像素输入增加算力和调试成本。
5. 原框架支持无界面运行、加速、多进程与同场景多 Agent，但用户游戏含全局场景树访问，不能直接复制多个环境到同一树。先单进程单局，后续独立进程并行。
6. ONNX 在上游标注实验性，Godot 内推理路径涉及 C#/.NET。用户本机找到 Godot 4.6.1 标准版，所以第一版保留 Python 推理，不把 ONNX 作为必须先完成的依赖。

### 已发现的集成风险

- Python 仓库固定的旧插件与当前 Python 协议不对应，应明确固定最新插件的已核对提交并做真实握手测试。
- `GodotEnv.step_recv()` 把 done 同时填给 terminated 和 truncated；SB3 wrapper 接收但没有分别传播。新项目必须独立定义自然终止与外部截断，不能直接相信示例已满足 Gymnasium 完整语义。
- `GodotEnv.reset(seed=...)` 的当前实现没有把 seed 参数发送给游戏。需在项目桥接层实际实现逐局种子设置，并验证重置轨迹。
- Sync 源码的终止自动重置存在 TODO/注释。必须规定返回末状态后谁负责重置，不能把下一局初始状态误记为上一局末状态。

## 用户游戏为什么选射击

`player.gd` 已有移动、方向射击、生命、无敌时间、Buff，`game.gd` 已有刷新加速、敌人上限、60 秒通关，四类敌人配置可复用，回合目标明确。

需要接入的真实位置：

| 文件 | 当前行为 | RL 接入要求 |
|---|---|---|
| scence/player.gd | Input.get_vector 直接读取键盘 | 抽出统一输入接口，人工与 Agent 使用同一移动/射击实现 |
| scence/game.gd | `_show_result` 设置 time_scale=0 且暂停场景树 | 训练模式产生终止记录并等待 reset，正常人工模式保持结算体验 |
| scence/game.gd | `_process` 推进计时；独立 RNG.randomize | 训练关键时钟固定物理步；显式种子，分离刷新随机流 |
| scence/enemy.gd | 每个敌人独立 randomize；死亡动画后掉落 | 敌人种子可追溯，记录击杀、伤害和掉落，明确事件时序 |
| player/enemy | 子弹、掉落加入 current_scene | 第一版单游戏场景运行，避免多环境交叉污染 |

本机检查得到 24 GB 内存、RTX 4060 Laptop GPU，以及 Godot 4.6.1 可执行文件。显存的 WMI 数字不作为可靠显存容量证据。结构化观测的小网络 PPO 可先尝试 CPU，是否需要 GPU 以实测为准，不能预先保证训练耗时或收敛。

## 三个方案的取舍

| 方案 | 优点 | 代价 | 本次选择 |
|---|---|---|---|
| Minecraft + Voyager 机制复现 | 与 LLM Agent 岗位贴合，技能复用演示直观 | 版本链长、模型与 Embedding 适配、持续 API 调用 | 暂不做 |
| 自有射击游戏 + Godot RL + PPO | 个人源码、训练闭环、量化测试，补充现有作品 | 奖励设计、环境重置与训练调参需要真实实验 | 选择 |
| 同时加入 LLM 任务规划和 RL 操作 | 覆盖面大 | 初期难定位效果来源，两套系统成本高 | 第一版排除 |

## 原始资料

- https://github.com/MineDojo/Voyager
- https://arxiv.org/html/2305.16291v2 （方法、实验、局限、提示词附录）
- https://github.com/MineDojo/Voyager/blob/main/FAQ.md
- https://github.com/edbeeching/godot_rl_agents
- https://arxiv.org/html/2112.03636v1
- https://github.com/edbeeching/godot_rl_agents/blob/main/docs/CUSTOM_ENV.md
- https://github.com/edbeeching/godot_rl_agents/blob/main/docs/GENERAL_TIPS.md
- https://github.com/edbeeching/godot_rl_agents/blob/main/godot_rl/core/godot_env.py
- https://github.com/edbeeching/godot_rl_agents_plugin
- https://github.com/Huhuhuc/2dshootgame
