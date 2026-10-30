# Security Policy

## Scope

`dsh-cascadeur-plugin` is a **local** DSH plugin. It:

- reads `.casc` files from paths you pass in,
- talks to Cascadeur's local MCP script server on `127.0.0.1:8765` (it executes Python inside
  your Cascadeur process — that is how the `Global Matrix` data is read),
- launches a local Blender executable (`blender -b`) to rebuild and export animation,
- writes settings to `~/.dsh/cascadeur-settings.json` and output files to `outDir`.

It does **not** make network requests, and it does not upload your animation, model or video data anywhere.

## Supported versions

| Version | Supported |
|---|---|
| 0.4.x | ✅ |
| < 0.4 | ❌ (please upgrade) |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's private vulnerability reporting:
**Security → Advisories → Report a vulnerability**
(https://github.com/GoRin-fofo/dsh-cascadeur-plugin/security/advisories/new)

Please include: affected version, steps to reproduce, and the impact you expect.
We aim to acknowledge within 7 days and to ship a fix for confirmed issues as soon as practical.

## Threat model notes

- The Cascadeur MCP server executes arbitrary Python posted to `127.0.0.1:8765`. It is a local
  development surface: keep it bound to loopback and stop it when you are not using it.
  `cascadeur_autostart/` starts it automatically — set `DSH_MCP_AUTOSTART=0` to opt out.
- `install.ps1` edits your DSH profile `package.json` and creates a junction in `node_modules`.
  It backs up the file first and rolls back on validation failure, but review the script before
  running it in a managed environment.

## 中文摘要

插件只在本机工作：读 `.casc`、连本机 Cascadeur 的 8765 脚本端口、调本机 Blender、写本机文件；不发网络请求、不上传素材。
安全问题请走 GitHub 私密漏洞报告（Security → Advisories → Report a vulnerability），不要开公开 issue。
