#!/usr/bin/env python3
"""
LAIW Chat — inference loop with legal search tools.

Usage:
    python3 tools/chat.py [--model claude-sonnet-4-6]

Requires:
    pip install anthropic
    export ANTHROPIC_API_KEY=...

Or use with a local Mistral model via llama.cpp / ollama (set --backend local).
"""

import json
import sys
import argparse
from .legal_search import TOOL_DEFINITIONS, TOOL_DISPATCH

SYSTEM_PROMPT = """Du är LAIW, en svensk juridisk AI-assistent specialiserad på svensk och EU-rättslig rådgivning.

Du har tillgång till verktyg för att söka i:
- Svenska lagar (SFS)
- Riksdagsdokument (propositioner, betänkanden m.m.)
- Vägledande domstolsavgöranden
- EU-lagstiftning (EUR-Lex)

Använd alltid verktygen när du behöver citera eller referera till specifika lagar, domar eller förarbeten.
Svara på svenska om inte användaren frågar på annat språk.
Var tydlig med att du ger juridisk information, inte juridisk rådgivning."""


def run_anthropic(model: str):
    import anthropic
    client = anthropic.Anthropic()

    messages = []
    print(f"LAIW ({model}) — skriv 'avsluta' för att avsluta\n")

    while True:
        user_input = input("Du: ").strip()
        if not user_input or user_input.lower() in ("avsluta", "quit", "exit"):
            break

        messages.append({"role": "user", "content": user_input})

        while True:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Collect text and tool calls
            text_parts = []
            tool_calls = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(block)

            if text_parts:
                print(f"\nLAIW: {''.join(text_parts)}\n")

            if response.stop_reason == "end_turn" or not tool_calls:
                messages.append({"role": "assistant", "content": response.content})
                break

            # Execute tool calls
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tc in tool_calls:
                print(f"  [verktyg: {tc.name}({json.dumps(tc.input, ensure_ascii=False)})]")
                fn = TOOL_DISPATCH.get(tc.name)
                if fn:
                    try:
                        result = fn(**tc.input)
                    except Exception as e:
                        result = {"error": str(e)}
                else:
                    result = {"error": f"Unknown tool: {tc.name}"}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LAIW Chat")
    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Model ID (default: claude-sonnet-4-6)")
    args = parser.parse_args()
    run_anthropic(args.model)
