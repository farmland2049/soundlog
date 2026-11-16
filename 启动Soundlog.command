#!/bin/zsh
# Finder double-click entry; keep paths with spaces intact.
cd -- "${0:A:h}" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  print '未找到 Python 3。请使用已配置的项目环境；此入口不会安装软件。'
  read '?按回车关闭…'
  exit 1
fi
if ! python3 scripts/launch_soundlog.py; then
  read '?启动失败，按回车关闭…'
  exit 1
fi
print 'Soundlog 已在浏览器打开。重复双击会复用服务；可关闭此终端窗口。'
