#!/bin/bash
#
# Agent setup script for Kiro CLI (https://kiro.dev).
#
# Sourced by setup.sh to configure where skills and slash commands are
# installed. Exports the install paths and skill filename expected by the
# agent; additional per-agent setup steps (if any) can be added here.
#
# Kiro CLI discovers global skills as ~/.kiro/skills/<name>/SKILL.md and
# global prompts as ~/.kiro/prompts/<name>.md.  Prompts are the Kiro
# equivalent of slash commands, but they are referenced with '@' in chat
# (e.g. @kreview) or picked from the '/prompts' list, hence COMMAND_PREFIX.

export SKILL_BASE_DIR="$HOME/.kiro/skills"
export COMMANDS_DIR="$HOME/.kiro/prompts"
export SKILL_FILE_NAME="SKILL.md"
export COMMAND_PREFIX="@"
