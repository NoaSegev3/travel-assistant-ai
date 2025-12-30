# Role: Local developer CLI to interact with FlowController without the web UI.
# Useful for deterministic testing and seeing debug logs in the terminal.

from __future__ import annotations
import uuid

import backend.config
backend.config.load_env()

from backend.core.flow_controller import FlowController


def _new_session_id() -> str:
    return str(uuid.uuid4())


def main() -> None:
    # 1) Create FlowController
    # 2) Maintain a session_id across turns
    # 3) Route user input -> FlowController -> print assistant output
    print("Travel Assistant CLI")
    print("Commands: /new (new session), /session (show session_id), /exit")
    print("-" * 50)

    flow = FlowController()
    session_id = _new_session_id()
    print(f"session_id: {session_id}")

    while True:
        try:
            user_message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            return

        if not user_message:
            continue

        cmd = user_message.lower()

        if cmd in {"/exit", "exit", "quit", "/quit"}:
            print("Bye!")
            return

        if cmd in {"/new", "new"}:
            session_id = _new_session_id()
            print(f"New session_id: {session_id}")
            continue

        if cmd in {"/session", "session"}:
            print(f"session_id: {session_id}")
            continue

        result = flow.handle_turn(session_id, user_message)
        print(f"\nAssistant: {result.assistant_message}")


if __name__ == "__main__":
    main()
