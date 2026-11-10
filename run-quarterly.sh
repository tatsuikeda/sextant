#!/bin/bash
# launchd entry point: quarterly review (Jan, Apr, Jul, Oct, 1st at 10:00).
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
exec ./venv/bin/python sextant.py check >> "$HOME/Library/Logs/sextant/check.log" 2>&1
