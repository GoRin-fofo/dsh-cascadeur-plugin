"""DSH：自动启动 Cascadeur 的 MCP 脚本服务器（127.0.0.1:8765）。

为什么放在这里：
    Cascadeur 启动时用 python_actions_rule.get_actions() 递归 import
    `resources/scripts/python/scripts/` 下的**每一个**模块（为了收集命令），
    因此本文件在应用启动阶段就会被 import —— 不需要改任何官方文件。

工作方式：
    import 时起一个守护线程，等 current_scene() 可用后调用
    scripts.mcp.script_server.server.start(scene)。幂等，最多等 900 秒。

关闭方式：
    设环境变量 DSH_MCP_AUTOSTART=0
    或直接删除本文件。

卸载：
    del "<Cascadeur安装目录>\\resources\\scripts\\python\\scripts\\mcp\\autostart.py"

日志：
    %TEMP%\\dsh_mcp_autostart.log
"""

import os
import tempfile
import threading
import time
import traceback

_TAG = "[dsh]"
_ENV_NAME = "DSH_MCP_AUTOSTART"
_WAIT_SECONDS = 900
_LOG_PATH = os.path.join(tempfile.gettempdir(), "dsh_mcp_autostart.log")


def _log(msg):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        print("%s %s" % (_TAG, msg))
    except Exception:
        pass


def _enabled():
    v = os.environ.get(_ENV_NAME, "1")
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def _bootstrap():
    """等场景就绪 → 启动 MCP 服务器。全程不抛异常。"""
    deadline = time.time() + _WAIT_SECONDS
    last_err = None
    while time.time() < deadline:
        try:
            import csc
            app = csc.app.get_application()
            scene = app.get_scene_manager().current_scene()
        except Exception as exc:          # csc 还没就绪
            last_err = exc
            scene = None

        if scene is not None:
            try:
                import scripts.mcp.script_server.server as script_server
                if script_server.is_running():
                    _log("MCP 服务器已在运行，跳过")
                else:
                    script_server.start(scene)
                    _log("MCP 服务器已启动: http://127.0.0.1:8765")
                return
            except Exception:
                _log("启动失败:\n" + traceback.format_exc())
                return

        time.sleep(1.0)

    _log("等待超时（%ds），未启动 MCP。最后错误: %r" % (_WAIT_SECONDS, last_err))


def _auto_start():
    try:
        if not _enabled():
            _log("自动启动已关闭（%s=0）" % _ENV_NAME)
            return
        _log("autostart 模块已导入，等待场景就绪…")
        threading.Thread(target=_bootstrap, name="dsh-mcp-autostart", daemon=True).start()
    except Exception:
        # 绝不能因为本模块影响应用启动
        try:
            _log("初始化异常:\n" + traceback.format_exc())
        except Exception:
            pass


_auto_start()
