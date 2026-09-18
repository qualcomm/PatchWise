#!/bin/bash
#
# Agent setup script for goose (https://github.com/aaif-goose/goose).
#
# Sourced by setup.sh to configure where skills and slash commands are
# installed. Exports the install paths and skill filename expected by the
# agent; additional per-agent setup steps (if any) can be added here.
#
# goose discovers global skills as ~/.agents/skills/<name>/SKILL.md (it also
# scans ~/.config/goose/skills and ~/.claude/skills; verify with
# 'goose skills list').  goose has no standalone slash-command files:
# every installed skill is exposed as the /<name> slash command, so the
# commands are installed as skills too via COMMANDS_AS_SKILLS.

export SKILL_BASE_DIR="$HOME/.agents/skills"
export COMMANDS_DIR="$HOME/.agents/skills"
export SKILL_FILE_NAME="SKILL.md"
export COMMANDS_AS_SKILLS=1
