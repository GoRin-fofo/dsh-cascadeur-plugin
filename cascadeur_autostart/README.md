# Cascadeur MCP 自动启动模块

让 Cascadeur **每次启动时自动打开** MCP 脚本服务器（`127.0.0.1:8765`），
省掉手动点 `Scripts → MCP → Start script server`。

---

## 原理

Cascadeur 启动时会用下面这段逻辑递归 **import `scripts/` 下的每一个模块**
（目的是收集命令）：

```python
# resources/scripts/python/python_actions_rule.py
for _, pack_name, ispkg in pkgutil.walk_packages(pkg.__path__):
    importlib.import_module(next_pkg)
```

所以只要把一个 `autostart.py` 放进 `scripts/mcp/`，它就会在应用启动阶段被执行。

`autostart.py` 做的事：

1. import 时起一个**守护线程**（不阻塞启动）
2. 每秒轮询，等 `current_scene()` 可用
3. 场景就绪后调 `scripts.mcp.script_server.server.start(scene)`
4. 幂等（已运行则跳过），最多等 900 秒
5. 所有异常都吞掉，**绝不影响 Cascadeur 启动**

日志：`%TEMP%\dsh_mcp_autostart.log`

---

## 安装

```powershell
$dest = "<Cascadeur安装目录>\resources\scripts\python\scripts\mcp"
Copy-Item .\autostart.py $dest
```

其中 `<Cascadeur安装目录>` 换成你自己的安装路径（例如 `D:\Apps\Cascadeur`）。

然后**重启 Cascadeur**。约 60 秒后（等场景加载完）看日志：

```powershell
Get-Content "$env:TEMP\dsh_mcp_autostart.log"
```

正常输出：

```
2026-10-26 22:01:25 autostart 模块已导入，等待场景就绪…
2026-10-26 22:02:29 MCP 服务器已启动: http://127.0.0.1:8765
```

验证端口：

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing
```

---

## 关闭 / 卸载

```powershell
# 临时关闭（不删文件）
$env:DSH_MCP_AUTOSTART = "0"

# 彻底移除
Remove-Item "<Cascadeur安装目录>\resources\scripts\python\scripts\mcp\autostart.py"
```

---

## 注意

1. **约 60 秒延迟**：服务器要等场景就绪才启动，别在刚打开 Cascadeur 时急着调用
2. **脚本里请用注入的 `scene` 变量**，不要用
   `csc.app.get_application().get_scene_manager().current_scene()` ——
   后者在自动启动的情况下可能返回 `csc.view.Scene`（没有 `model_viewer`）
3. 只在本机 Cascadeur 安装目录里加了一个文件，**没有修改任何官方文件**
4. 不涉及授权，只是调用官方 `script_server.start()`

---

## 出处

这个思路来自 ARM/Android 环境下的实验记录（box64 跑 Cascadeur），
那边验证了"钩子确实执行"，但应用崩得太早所以没跑到启动那一步。
在正常 x86 机器上**实测可用**。
