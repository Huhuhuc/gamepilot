# 来源与授权边界

- 游戏来源：用户仓库 [Huhuhuc/2dshootgame](https://github.com/Huhuhuc/2dshootgame)，固定提交见 sources.json。原人物、地图、音频、敌人和战斗逻辑来自该项目，GamePilot 增加训练适配。
- Godot RL Agents 插件：[edbeeching/godot_rl_agents_plugin](https://github.com/edbeeching/godot_rl_agents_plugin)，MIT；原始下载保留在 vendor/，运行副本在 game/addons/，原许可证位于 vendor/godot_rl_agents_plugin/LICENSE。
- Python 框架：[godot_rl_agents](https://github.com/edbeeching/godot_rl_agents)，MIT；通过依赖安装，复用 GodotEnv 的协议/空间构建。
- PPO 实现：[Stable-Baselines3](https://github.com/DLR-RM/stable-baselines3)，MIT；没有声称原创算法。
- Voyager 作为选型研究参考，没有复制其 Minecraft 执行代码。

原游戏包含第三方角色/美术/音频；目前未提供逐项可再分发授权。本公开仓库不包含原游戏音频、字体、美术图片或游戏预览图。运行前可显式执行 `restore-game-assets.ps1`，它从 `sources.json` 中固定的原游戏提交下载这些文件到本地；下载仅用于本地运行，使用者需自行确认并遵守原游戏及素材的授权条款。该脚本不会把素材重新加入 GamePilot 仓库。本项目不对整个目录授予统一 MIT 许可证。
