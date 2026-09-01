from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.infrastructure.desktop.computer_operator import ComputerOperator
from aura.legacy.assistant.domain_manager import DomainManager
from aura.legacy.assistant.executive_behavior import ExecutiveBehavior
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.legacy.assistant.models import ActionRequest, ActionResult
from aura.legacy.assistant.planner import PlannerAgent
from aura.infrastructure.desktop.result_revealer import ResultRevealer
from aura.safety.policies import SafetyLayer
from aura.legacy.assistant.software_director import SoftwareDirector


@dataclass
class ExecutiveOutcome:
    ok: bool
    message: str
    assumptions: dict[str, str] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


@dataclass
class AssumedExecution:
    project_name: str
    project_path: Path
    assumptions: dict[str, str]
    requests: list[ActionRequest]


class AssumptionEngine:
    """Fill safe implementation details for common project-style goals."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def infer(self, goal: str) -> AssumedExecution:
        lowered = goal.lower()

        if "folder" in lowered and self._contains_any(
            lowered,
            ("readme", "python script", "inside it"),
        ):
            return self._compound_folder_project(goal)
        if "open vs code" in lowered and "project" in lowered:
            return self._vscode_project(goal)
        if "sponsor" in lowered and "email" in lowered:
            return self._sponsor_email(goal)
        if self._contains_any(
            lowered,
            ("game", "pygame", "snake", "tetris", "platformer", "arcade", "racing"),
        ):
            return self._game_project(goal)
        if self._contains_any(lowered, ("discord bot", "telegram bot", " bot")):
            return self._bot_project(goal)
        if self._contains_any(
            lowered,
            ("website", "web app", " site", "portfolio", "landing page", "dashboard", "flask"),
        ):
            return self._web_project(goal)
        if "calculator" in lowered or "calclator" in lowered:
            return self._python_calculator(goal)
        if self._contains_any(lowered, ("proposal", "notes", "report", "presentation", "ppt")):
            return self._document_project(goal)
        if self._contains_any(
            lowered,
            (
                " ai ",
                "ai ",
                "assistant",
                "chatbot",
                "agent",
                "vision",
                "classifier",
            ),
        ):
            return self._ai_project(goal)
        if self._contains_any(
            lowered,
            ("python", " app", "application", " tool", "program", "utility", "script"),
        ):
            return self._python_project(goal)

        project_name = self._project_name(goal, "AuraProject")
        project_path = self.workspace_root / "Code" / project_name
        assumptions = {
            "implementation": "simplest local implementation",
            "storage": "local files",
        }
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": f"# {project_name}\n\nGoal: {goal.strip()}\n",
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _compound_folder_project(self, goal: str) -> AssumedExecution:
        folder_match = re.search(
            r"folder(?:\s+named|\s+called)?\s+([A-Za-z][A-Za-z0-9_-]{1,40})",
            goal,
            flags=re.IGNORECASE,
        )
        project_name = folder_match.group(1) if folder_match else "GeneratedFolder"
        project_path = self.workspace_root / project_name
        lowered = goal.lower()
        assumptions = {
            "location": "AURA workspace",
            "execution": "sequential",
        }
        requests = [ActionRequest(action="create_folder", args={"path": str(project_path)})]
        if "python script" in lowered:
            requests.append(
                ActionRequest(
                    action="write_text_file",
                    args={
                        "path": str(project_path / "main.py"),
                        "content": 'print("Hello World")\n',
                    },
                )
            )
        if "readme" in lowered:
            requests.append(
                ActionRequest(
                    action="write_text_file",
                    args={
                        "path": str(project_path / "README.md"),
                        "content": f"# {project_name}\n\nCreated by AURA.\n",
                    },
                )
            )
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _vscode_project(self, goal: str) -> AssumedExecution:
        project_name = self._project_name(goal, "TestProject")
        project_path = self.workspace_root / "Code" / project_name
        assumptions = {
            "editor": "VS Code",
            "language": "Python 3.11",
            "implementation": "minimal starter project",
        }
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "main.py"),
                    "content": 'print("Hello from AURA")\n',
                },
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": f"# {project_name}\n\nOpened as a VS Code project.\n",
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _game_project(self, goal: str) -> AssumedExecution:
        lowered = goal.lower()
        project_name = "SnakeGame" if "snake" in lowered else self._project_name(goal, "PythonGame")
        project_path = self.workspace_root / "Code" / project_name
        assumptions = {
            "engine": "pygame",
            "language": "Python 3.11",
            "gameplay": "simple runnable starter",
        }
        main_py = '''from __future__ import annotations

import random

import pygame

WIDTH, HEIGHT = 800, 500
PLAYER_SIZE = 34


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("AURA Python Game")
    clock = pygame.time.Clock()
    player = pygame.Rect(80, HEIGHT // 2, PLAYER_SIZE, PLAYER_SIZE)
    target = pygame.Rect(600, 180, 24, 24)
    score = 0
    font = pygame.font.Font(None, 32)
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()
        player.x += (keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]) * 5
        player.y += (keys[pygame.K_DOWN] - keys[pygame.K_UP]) * 5
        player.clamp_ip(screen.get_rect())

        if player.colliderect(target):
            score += 1
            target.topleft = (
                random.randint(30, WIDTH - 50),
                random.randint(30, HEIGHT - 50),
            )

        screen.fill("#151922")
        pygame.draw.rect(screen, "#55d6be", player)
        pygame.draw.rect(screen, "#ffcc66", target)
        screen.blit(font.render(f"Score: {score}", True, "white"), (20, 18))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()
'''
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(action="create_folder", args={"path": str(project_path / "assets")}),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "main.py"), "content": main_py},
            ),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "requirements.txt"), "content": "pygame>=2.5,<3\n"},
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": (
                        f"# {project_name}\n\n"
                        "Install with `pip install -r requirements.txt`, then run `python main.py`.\n"
                        "Use the arrow keys to collect targets.\n"
                    ),
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _bot_project(self, goal: str) -> AssumedExecution:
        lowered = goal.lower()
        is_telegram = "telegram" in lowered
        project_name = "TelegramBot" if is_telegram else "DiscordBot"
        project_path = self.workspace_root / "Code" / project_name
        if is_telegram:
            requirements = "python-telegram-bot>=21,<22\n"
            main_py = '''from __future__ import annotations

import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello from your AURA Telegram bot.")


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()


if __name__ == "__main__":
    main()
'''
            token_name = "TELEGRAM_BOT_TOKEN"
        else:
            requirements = "discord.py>=2.4,<3\n"
            main_py = '''from __future__ import annotations

import os

import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.command()
async def hello(ctx: commands.Context) -> None:
    await ctx.send("Hello from your AURA Discord bot.")


bot.run(os.environ["DISCORD_BOT_TOKEN"])
'''
            token_name = "DISCORD_BOT_TOKEN"
        assumptions = {
            "language": "Python 3.11",
            "framework": "python-telegram-bot" if is_telegram else "discord.py",
            "credentials": "environment variable",
        }
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "main.py"), "content": main_py},
            ),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "requirements.txt"), "content": requirements},
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / ".env.example"),
                    "content": f"{token_name}=replace_me\n",
                },
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": (
                        f"# {project_name}\n\n"
                        "Install dependencies, copy `.env.example` values into your environment, "
                        "then run `python main.py`.\n"
                    ),
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _document_project(self, goal: str) -> AssumedExecution:
        lowered = goal.lower()
        if "presentation" in lowered or "ppt" in lowered:
            project_name = "Presentation"
            filename = "presentation_outline.md"
            heading = "Presentation Outline"
        elif "proposal" in lowered:
            project_name = "Proposal"
            filename = "proposal.md"
            heading = "Proposal"
        elif "report" in lowered:
            project_name = "Report"
            filename = "report.md"
            heading = "Report"
        else:
            project_name = "AINotes" if "ai" in lowered else "Notes"
            filename = "notes.md"
            heading = "AI Notes" if "ai" in lowered else "Notes"
        project_path = self.workspace_root / "Code" / project_name
        assumptions = {
            "format": "Markdown",
            "storage": "local project folder",
            "content": "concise starter document",
        }
        content = (
            f"# {heading}\n\n"
            f"Requested goal: {goal.strip()}\n\n"
            "## Overview\n\n"
            "This document is ready for details, decisions, and next actions.\n\n"
            "## Next Actions\n\n"
            "- Add the core content.\n"
            "- Review and refine.\n"
        )
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / filename), "content": content},
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": f"# {project_name}\n\nGenerated for: {goal.strip()}\n",
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _ai_project(self, goal: str) -> AssumedExecution:
        lowered = goal.lower()
        if "chatbot" in lowered:
            fallback = "LocalChatbot"
        elif "classifier" in lowered:
            fallback = "LocalClassifier"
        elif "vision" in lowered:
            fallback = "VisionProject"
        else:
            fallback = "LocalAIAssistant"
        project_name = self._project_name(goal, fallback)
        project_path = self.workspace_root / "Code" / project_name
        assumptions = {
            "language": "Python 3.11",
            "inference": "local Ollama",
            "storage": "local files",
        }
        main_py = '''from __future__ import annotations

import requests


def ask_local_model(prompt: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen2.5:3b",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


if __name__ == "__main__":
    print(ask_local_model(input("You: ")))
'''
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "main.py"), "content": main_py},
            ),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "requirements.txt"), "content": "requests>=2.32,<3\n"},
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": (
                        f"# {project_name}\n\n"
                        "Local AI starter using Ollama. Start Ollama, then run `python main.py`.\n"
                    ),
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _python_calculator(self, goal: str) -> AssumedExecution:
        project_name = self._project_name(goal, "CalculatorApp")
        project_path = self.workspace_root / "Code" / project_name
        assumptions = {
            "language": "Python 3.11",
            "interface": "command line",
            "dependencies": "standard library only",
        }
        main_py = '''from __future__ import annotations


def calculate(left: float, operator: str, right: float) -> float:
    operations = {
        "+": lambda a, b: a + b,
        "-": lambda a, b: a - b,
        "*": lambda a, b: a * b,
        "/": lambda a, b: a / b,
    }
    if operator not in operations:
        raise ValueError("Operator must be one of: +, -, *, /")
    return operations[operator](left, right)


def main() -> None:
    expression = input("Enter calculation, for example 12 * 3: ").split()
    if len(expression) != 3:
        raise ValueError("Use: number operator number")
    left, operator, right = expression
    print(calculate(float(left), operator, float(right)))


if __name__ == "__main__":
    main()
'''
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "main.py"), "content": main_py},
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "requirements.txt"),
                    "content": "# Standard library only\n",
                },
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": (
                        f"# {project_name}\n\n"
                        "A small Python 3.11 command-line calculator.\n\n"
                        "Run with `python main.py`.\n"
                    ),
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _python_project(self, goal: str) -> AssumedExecution:
        fallback = "PythonApp"
        if "weather" in goal.lower():
            fallback = "WeatherApp"
        elif "todo" in goal.lower() or "to-do" in goal.lower():
            fallback = "TodoApp"
        project_name = self._project_name(goal, fallback)
        project_path = self.workspace_root / "Code" / project_name
        assumptions = {
            "language": "Python 3.11",
            "interface": "command line",
            "dependencies": "standard library first",
        }
        main_py = (
            '"""Local starter application generated by AURA."""\n\n'
            "def main() -> None:\n"
            f'    print("{project_name} is ready.")\n\n\n'
            'if __name__ == "__main__":\n'
            "    main()\n"
        )
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "main.py"), "content": main_py},
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "requirements.txt"),
                    "content": "# Add dependencies only when needed\n",
                },
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": f"# {project_name}\n\nGenerated for: {goal.strip()}\n",
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _web_project(self, goal: str) -> AssumedExecution:
        lowered = goal.lower()
        backend_implied = self._contains_any(
            lowered,
            ("flask", "backend", "database", "api", "server", "web app", "dashboard"),
        )
        fallback = "PortfolioWebsite" if "portfolio" in lowered else (
            "FlaskWebsite" if backend_implied else "StaticWebsite"
        )
        project_name = self._project_name(goal, fallback)
        project_path = self.workspace_root / "Code" / project_name
        if not backend_implied:
            assumptions = {
                "frontend": "HTML/CSS/JS",
                "backend": "none",
                "storage": "static files",
            }
            index_html = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AURA Website</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header>
    <p class="eyebrow">Portfolio</p>
    <h1>Welcome to your new website.</h1>
    <p>Replace this copy with your work, story, and contact details.</p>
  </header>
  <main id="projects"></main>
  <script src="script.js"></script>
</body>
</html>
'''
            styles_css = '''body {
  margin: 0;
  font-family: Arial, sans-serif;
  background: #f4f6f8;
  color: #18202a;
}

header, main {
  max-width: 900px;
  margin: 0 auto;
  padding: 56px 24px;
}

.eyebrow {
  color: #166534;
  font-weight: 700;
  text-transform: uppercase;
}
'''
            script_js = '''const projects = document.querySelector("#projects");
projects.textContent = "Add your projects here.";
'''
            requests = [
                ActionRequest(action="create_folder", args={"path": str(project_path)}),
                ActionRequest(
                    action="write_text_file",
                    args={"path": str(project_path / "index.html"), "content": index_html},
                ),
                ActionRequest(
                    action="write_text_file",
                    args={"path": str(project_path / "styles.css"), "content": styles_css},
                ),
                ActionRequest(
                    action="write_text_file",
                    args={"path": str(project_path / "script.js"), "content": script_js},
                ),
                ActionRequest(
                    action="write_text_file",
                    args={
                        "path": str(project_path / "README.md"),
                        "content": f"# {project_name}\n\nOpen `index.html` in a browser.\n",
                    },
                ),
            ]
            return AssumedExecution(project_name, project_path, assumptions, requests)

        assumptions = {
            "backend": "Flask",
            "frontend": "HTML/CSS/JS",
            "database": "SQLite when persistence is needed",
            "runtime": "Python 3.11",
        }
        app_py = '''from flask import Flask, render_template

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
'''
        index_html = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AURA Website</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <main>
    <h1>Your Flask website is ready.</h1>
    <p>Edit this page to continue building.</p>
  </main>
</body>
</html>
'''
        styles_css = '''body {
  margin: 0;
  font-family: Arial, sans-serif;
  background: #f4f6f8;
  color: #18202a;
}

main {
  max-width: 720px;
  margin: 80px auto;
  padding: 32px;
  background: white;
  border: 1px solid #d8dee6;
}
'''
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "app.py"), "content": app_py},
            ),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "requirements.txt"), "content": "Flask>=3.0,<4\n"},
            ),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "templates" / "index.html"), "content": index_html},
            ),
            ActionRequest(
                action="write_text_file",
                args={"path": str(project_path / "static" / "styles.css"), "content": styles_css},
            ),
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(project_path / "README.md"),
                    "content": (
                        f"# {project_name}\n\n"
                        "Install with `pip install -r requirements.txt` and run `python app.py`.\n"
                    ),
                },
            ),
        ]
        return AssumedExecution(project_name, project_path, assumptions, requests)

    def _sponsor_email(self, goal: str) -> AssumedExecution:
        project_name = "SponsorEmail"
        project_path = self.workspace_root / "workspace"
        email_path = project_path / "sponsor_email.txt"
        assumptions = {
            "tone": "professional and concise",
            "delivery": "draft only; do not send",
            "format": "plain text",
        }
        content = (
            "Subject: Sponsorship Opportunity\n\n"
            "Hello,\n\n"
            "We are reaching out to explore a sponsorship partnership for our upcoming event. "
            "Your support would help us deliver a stronger experience for attendees while giving "
            "your brand meaningful visibility with our community.\n\n"
            "We would be glad to share the event plan, audience profile, and sponsorship options.\n\n"
            "Best regards,\n"
            "Event Team\n"
        )
        requests = [
            ActionRequest(action="create_folder", args={"path": str(project_path)}),
            ActionRequest(
                action="write_text_file",
                args={"path": str(email_path), "content": content},
            ),
        ]
        return AssumedExecution(project_name, email_path, assumptions, requests)

    def _project_name(self, goal: str, fallback: str) -> str:
        match = re.search(
            r"(?:called|named)\s+([A-Za-z][A-Za-z0-9_-]{1,40})",
            goal,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)
        return fallback

    def _contains_any(self, text: str, markers: tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)


class ExecutionVerifier:
    """Verify tool outcomes using Python and the local filesystem."""

    def verify(self, request: ActionRequest, result: ActionResult) -> tuple[bool, str]:
        if not result.ok:
            return False, result.message

        if request.action == "create_folder":
            path = Path(str(request.args.get("path", ""))).expanduser()
            return path.is_dir(), f"Folder verification: {path}"

        if request.action == "create_file":
            path = Path(str(request.args.get("path", ""))).expanduser()
            return path.is_file(), f"File verification: {path}"

        if request.action == "write_text_file":
            path = Path(str(request.args.get("path", ""))).expanduser()
            expected = str(request.args.get("content", ""))
            if not path.is_file():
                return False, f"File missing after write: {path}"
            return path.read_text(encoding="utf-8") == expected, f"Content verification: {path}"

        if request.action == "open_app":
            launched = bool(result.output.get("command")) or bool(result.output.get("fallback_used"))
            return launched, result.message

        if request.action == "open_url":
            return bool(result.output.get("url")), result.message

        return result.ok, result.message


class ExecutiveAgent:
    """Additive orchestration layer over AURA's existing components."""

    def __init__(
        self,
        planner: PlannerAgent,
        executor: ExecutionAgent,
        verifier: ExecutionVerifier,
        assumption_engine: AssumptionEngine,
        memory: MemoryStore,
        safety: SafetyLayer,
        workspace_root: Path,
        confirmation_callback: Optional[Callable[[str], bool]] = None,
        result_revealer: Optional[ResultRevealer] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        software_director: Optional[SoftwareDirector] = None,
        computer_operator: Optional[ComputerOperator] = None,
        domain_manager: Optional[DomainManager] = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.verifier = verifier
        self.assumption_engine = assumption_engine
        self.memory = memory
        self.safety = safety
        self.workspace_root = workspace_root.resolve()
        self.executor.workspace_root = self.workspace_root
        self.confirmation_callback = confirmation_callback
        self.result_revealer = result_revealer
        self.status_callback = status_callback
        self.computer_operator = computer_operator or ComputerOperator(
            executor=self.executor,
            memory=self.memory,
            safety=self.safety,
            result_revealer=self.result_revealer,
            status_callback=self.status_callback,
        )
        self.software_director = software_director or SoftwareDirector(
            workspace_root=self.workspace_root,
            executor=self.executor,
            memory=self.memory,
            safety=self.safety,
            result_revealer=self.result_revealer,
            status_callback=self.status_callback,
        )
        self.domain_manager = domain_manager or DomainManager(
            memory=self.memory,
            domains_dir=self.workspace_root / "domains",
            operator_executor=self.computer_operator.execute,
            software_executor=self.software_director.execute,
        )

    def can_handle(self, goal: str) -> bool:
        lowered = goal.strip().lower()
        domain_manager = getattr(self, "domain_manager", None)
        if domain_manager is not None and domain_manager.can_handle(goal):
            return True
        computer_operator = getattr(self, "computer_operator", None)
        if computer_operator is not None and computer_operator.can_handle(goal):
            return True
        software_director = getattr(self, "software_director", None)
        if software_director is not None and software_director.can_handle(goal):
            return True
        if "sponsor" in lowered and "email" in lowered:
            return True
        action_words = (
            "make",
            "build",
            "create",
            "generate",
            "develop",
            "design",
            "implement",
            "produce",
            "write",
        )
        project_markers = (
            "game",
            "pygame",
            "snake",
            "tetris",
            "platformer",
            "arcade",
            "racing",
            "website",
            "web app",
            "portfolio",
            "landing page",
            "dashboard",
            "application",
            "tool",
            "program",
            "utility",
            "script",
            "assistant",
            "chatbot",
            "agent",
            "vision",
            "classifier",
            "bot",
            "discord bot",
            "telegram bot",
            "proposal",
            "notes",
            "report",
            "presentation",
            "ppt",
            "project",
            "calculator",
            "calclator",
        )
        if "folder" in lowered and any(
            marker in lowered for marker in ("readme", "python script", "inside it")
        ):
            return True
        if "open vs code" in lowered and "project" in lowered:
            return True
        has_action = any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in action_words)
        conversational_build_intent = any(
            phrase in lowered
            for phrase in (
                "i want ",
                "i need ",
            )
        )
        has_project = any(
            re.search(rf"\b{re.escape(marker)}\b", lowered)
            for marker in project_markers
        )
        has_project = has_project or bool(
            re.search(r"\b(?:web\s+app|landing\s+page|discord\s+bot|telegram\s+bot)\b", lowered)
        )
        if re.search(r"\bai\b", lowered):
            has_project = has_project or bool(
                re.search(r"\b(?:project|assistant|agent|chatbot|app|tool|classifier|vision)\b", lowered)
            )
        if re.search(r"\bapp\b", lowered):
            has_project = True
        return has_project and (has_action or conversational_build_intent)

    def execute(self, goal: str) -> ExecutiveOutcome:
        domain_manager = getattr(self, "domain_manager", None)
        if domain_manager is not None and domain_manager.can_handle(goal):
            result = domain_manager.execute(goal)
            return ExecutiveOutcome(
                ok=result.ok,
                message=result.message,
                assumptions={
                    "domain_manager": "ATLAS",
                    "domains": ", ".join(route.domain_id for route in result.routes),
                },
                actions=result.actions,
                artifacts=result.artifacts,
            )

        computer_operator = getattr(self, "computer_operator", None)
        if computer_operator is not None and computer_operator.can_handle(goal):
            outcome = computer_operator.execute(goal)
            return ExecutiveOutcome(
                ok=outcome.ok,
                message=outcome.message,
                assumptions={
                    "operator": outcome.plan.environment,
                    "application": outcome.plan.application,
                },
                actions=[
                    {
                        "id": step.id,
                        "action": step.kind,
                        "target": step.target,
                        "status": step.status,
                    }
                    for step in outcome.plan.steps
                ],
                artifacts=[],
            )

        software_director = getattr(self, "software_director", None)
        if software_director is not None and software_director.can_handle(goal):
            outcome = self.software_director.execute(goal)
            return ExecutiveOutcome(
                ok=outcome.ok,
                message=outcome.message,
                assumptions={
                    "engineering": "software director",
                    "complexity": str(outcome.blueprint.complexity_level),
                },
                actions=outcome.actions,
                artifacts=outcome.artifacts,
            )

        self._status(ExecutiveBehavior.ANALYZING.label)
        assumed = self.assumption_engine.infer(goal)
        self._status(ExecutiveBehavior.PLANNING.label)
        now = datetime.now(timezone.utc).isoformat()
        planner_state = {
            "goal": goal,
            "constraints": {"assumptions": assumed.assumptions},
            "context": {"source": "deterministic_assumption_engine"},
            "plan": [
                {
                    "id": f"T{index}",
                    "title": request.action.replace("_", " ").title(),
                    "owner": "AURA",
                    "dependencies": [],
                    "risk": request.risk.value,
                    "execution_type": "execution",
                    "status": "pending",
                }
                for index, request in enumerate(assumed.requests, start=1)
            ],
            "created_at": now,
            "updated_at": now,
        }

        action_records: list[dict[str, Any]] = []
        artifacts: list[str] = []
        all_ok = True

        for request in assumed.requests:
            self._status(self._status_for_request(request))
            request.risk = self.safety.classify(request.action)
            if self.safety.requires_confirmation(request):
                if not self._confirm(f"Approve high-risk action {request.action}?"):
                    action_records.append(self._record(request, None, False, "Rejected by user"))
                    all_ok = False
                    break

            path = str(request.args.get("path", ""))
            if path:
                path_decision = self.safety.assess_path(
                    request.action,
                    path,
                    self.workspace_root,
                )
            else:
                path_decision = None
            if path_decision is not None and path_decision.denied:
                action_records.append(self._record(request, None, False, path_decision.reason))
                all_ok = False
                break
            if path_decision is not None and path_decision.requires_confirmation:
                if not self._confirm(f"{path_decision.reason} Approve access to {path_decision.target}?"):
                    action_records.append(self._record(request, None, False, "Rejected by user"))
                    all_ok = False
                    break
                if "existing" in path_decision.reason.lower():
                    request.args["overwrite"] = True
                if "outside approved workspace" in path_decision.reason:
                    request.args["allow_external_write"] = True

            result = self.executor.run(request)
            self._status(ExecutiveBehavior.VERIFYING.label)
            verified, verification = self.verifier.verify(request, result)
            if not verified and not self._should_not_retry(result):
                self._status(ExecutiveBehavior.RECOVERING.label)
                retry = self.executor.run(request)
                retry_verified, retry_verification = self.verifier.verify(request, retry)
                if retry_verified:
                    result = retry
                    verified = retry_verified
                    verification = f"Recovered after retry. {retry_verification}"
            record = self._record(request, result, verified, verification)
            action_records.append(record)
            self.memory.append_log(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "mode": "executive_agent",
                    "goal": goal,
                    "project": assumed.project_name,
                    **record,
                }
            )

            if verified and request.action in {"create_folder", "create_file", "write_text_file"}:
                artifacts.append(str(request.args.get("path", "")))
            if not verified:
                all_ok = False
                break

        project_data = {
            "goal": goal,
            "project_name": assumed.project_name,
            "project_path": str(assumed.project_path),
            "assumptions": assumed.assumptions,
            "planner_state": planner_state,
            "actions": action_records,
            "artifacts": artifacts,
            "status": "completed" if all_ok else "failed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.memory.upsert_project(assumed.project_name, project_data)

        if all_ok:
            self._status(ExecutiveBehavior.REVEALING.label)
            reveal_method = self._reveal_result(assumed)
            message = self._completion_message(assumed, artifacts, reveal_method)
        else:
            self._status(ExecutiveBehavior.RECOVERING.label)
            failed = next((row for row in action_records if not row["verified"]), None)
            detail = failed["verification"] if failed else "Execution stopped."
            message = ExecutiveBehavior.sanitize_for_user(
                f"I couldn't complete {assumed.project_name}. {detail}"
            )
        self._status(ExecutiveBehavior.COMPLETE.label)

        return ExecutiveOutcome(
            ok=all_ok,
            message=message,
            assumptions=assumed.assumptions,
            actions=action_records,
            artifacts=artifacts,
        )

    def _confirm(self, prompt: str) -> bool:
        if self.confirmation_callback is None:
            return False
        return self.confirmation_callback(prompt)

    def _record(
        self,
        request: ActionRequest,
        result: Optional[ActionResult],
        verified: bool,
        verification: str,
    ) -> dict[str, Any]:
        return {
            "request": request.model_dump(),
            "result": result.model_dump() if result is not None else None,
            "verified": verified,
            "verification": verification,
        }

    def _completion_message(
        self,
        assumed: AssumedExecution,
        artifacts: list[str],
        reveal_method: str = "",
    ) -> str:
        if assumed.project_name == "SponsorEmail":
            opened = " Saved and opened" if reveal_method == "file" else " Saved"
            return f"Done.{opened} sponsor_email.txt at {assumed.project_path}."
        return ExecutiveBehavior.concise_completion(
            project_name=assumed.project_name,
            artifact_count=len(artifacts),
            reveal_method=reveal_method,
        )

    def _reveal_result(self, assumed: AssumedExecution) -> str:
        if self.result_revealer is None or not self.result_revealer.enabled:
            return ""
        if assumed.project_name == "SponsorEmail":
            return "file" if self.result_revealer.reveal_file(assumed.project_path) else ""
        revealed, method = self.result_revealer.reveal_project(assumed.project_path)
        return method if revealed else ""

    def _status(self, message: str) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(message)
        except Exception:
            pass

    def _status_for_request(self, request: ActionRequest) -> str:
        if request.action == "create_folder":
            return "Creating folders..."
        if request.action in {"create_file", "write_text_file"}:
            return "Generating files..."
        if request.action in {"open_app", "open_url"}:
            return "Launching..."
        return ExecutiveBehavior.EXECUTING.label

    def _should_not_retry(self, result: ActionResult) -> bool:
        return bool(
            result.output.get("overwrite_required")
            or result.output.get("already_exists")
        )
