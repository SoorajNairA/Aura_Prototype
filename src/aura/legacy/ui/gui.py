from __future__ import annotations

import math
import random
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

from aura.legacy.assistant.orchestrator import AuraSupervisor


@dataclass
class Particle:
    angle: float
    radius: float
    speed: float
    size: float


class AuraAppUI:
    def __init__(self, supervisor: AuraSupervisor) -> None:
        self.supervisor = supervisor

        self.root = tk.Tk()
        self.root.title("AURA Voice Console")
        self.root.geometry("560x720")
        self.root.configure(bg="#070b14")
        icon_path = Path(__file__).resolve().parents[4] / "assets" / "icons" / "aura.ico"
        if icon_path.is_file():
            self.root.iconbitmap(default=str(icon_path))

        self.level_lock = threading.Lock()
        self.voice_level = 0.0
        self.is_listening = False
        self.demo_buttons: list[tk.Button] = []

        self.canvas = tk.Canvas(
            self.root,
            width=520,
            height=520,
            bg="#070b14",
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(pady=18)

        self.status_var = tk.StringVar(value="Ready. Press Talk and speak your objective.")
        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            bg="#070b14",
            fg="#c8d6ff",
            font=("Segoe UI", 11),
            wraplength=500,
            justify="center",
        )
        self.status_label.pack(pady=(0, 12))

        self.transcript_var = tk.StringVar(value="Last heard: (none)")
        self.transcript_label = tk.Label(
            self.root,
            textvariable=self.transcript_var,
            bg="#070b14",
            fg="#89a2d8",
            font=("Segoe UI", 10),
            wraplength=500,
            justify="center",
        )
        self.transcript_label.pack(pady=(0, 14))

        self.talk_button = tk.Button(
            self.root,
            text="Talk",
            command=self._on_talk_pressed,
            bg="#4a8cff",
            fg="#ffffff",
            activebackground="#6ea2ff",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            font=("Segoe UI Semibold", 14),
            padx=24,
            pady=10,
            cursor="hand2",
        )
        self.talk_button.pack(pady=(0, 10))

        if self.supervisor.settings.demo_mode:
            self._create_demo_panel()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.cx = 260
        self.cy = 260
        self.base_ring = 92
        self.particles = [
            Particle(
                angle=random.uniform(0, math.pi * 2),
                radius=random.uniform(self.base_ring + 26, self.base_ring + 92),
                speed=random.uniform(0.005, 0.02),
                size=random.uniform(2.2, 4.8),
            )
            for _ in range(72)
        ]

        self._animate()

    def run(self) -> None:
        self.root.mainloop()

    def _create_demo_panel(self) -> None:
        demo_frame = tk.Frame(self.root, bg="#070b14")
        demo_frame.pack(pady=10, fill="x", padx=20)

        lbl = tk.Label(demo_frame, text="DEMO SHORTCUTS", bg="#070b14", fg="#5a72a8", font=("Segoe UI Bold", 9))
        lbl.pack(pady=(0, 8))

        btn_config = {
            "bg": "#1c2538",
            "fg": "#c8d6ff",
            "activebackground": "#2d3a56",
            "activeforeground": "#ffffff",
            "relief": "flat",
            "bd": 0,
            "font": ("Segoe UI", 9),
            "padx": 10,
            "pady": 5,
            "cursor": "hand2",
        }

        row1 = tk.Frame(demo_frame, bg="#070b14")
        row1.pack()

        self._add_demo_button(row1, "Run Full Demo", "run demo", btn_config)
        self._add_demo_button(row1, "Build Snake", "Create a Snake Game in Python", btn_config)
        self._add_demo_button(row1, "Open VS Code", "Open VS Code", btn_config)

        row2 = tk.Frame(demo_frame, bg="#070b14")
        row2.pack(pady=8)

        self._add_demo_button(row2, "Show Capabilities", "show capabilities", btn_config)
        self._add_demo_button(row2, "Memory Test", "What projects have we worked on?", btn_config)
        self._add_demo_button(row2, "Sponsor Email", "Draft a Sponsor Email", btn_config)

    def _add_demo_button(
        self,
        parent: tk.Frame,
        label: str,
        command: str,
        config: dict[str, object],
    ) -> None:
        button = tk.Button(
            parent,
            text=label,
            command=lambda: self._run_demo_command(command),
            **config,
        )
        button.pack(side="left", padx=4)
        self.demo_buttons.append(button)

    def _run_demo_command(self, cmd: str) -> None:
        if self.is_listening:
            return
        self.is_listening = True
        self.talk_button.configure(state="disabled")
        for button in self.demo_buttons:
            button.configure(state="disabled")
        self.status_var.set(f"Executing: {cmd}")
        self.transcript_var.set(f"Demo Trigger: {cmd}")

        def worker() -> None:
            try:
                should_continue = self.supervisor.handle_spoken_text(
                    cmd, require_wake_word=False
                )
                status = (
                    "Done. Choose another demo."
                    if should_continue
                    else "AURA is shutting down."
                )
                self.root.after(0, lambda: self.status_var.set(status))
            except Exception as exc:
                message = str(exc)
                self.root.after(
                    0,
                    lambda: self.status_var.set(f"Demo error: {message}"),
                )
            finally:
                self.is_listening = False
                self.root.after(0, self._enable_controls)

        threading.Thread(target=worker, daemon=True).start()

    def _enable_controls(self) -> None:
        self.talk_button.configure(state="normal", text="Talk")
        for button in self.demo_buttons:
            button.configure(state="normal")

    def _on_close(self) -> None:
        self.supervisor.shutdown()
        self.root.destroy()

    def _set_level(self, level: float) -> None:
        normalized = min(1.0, max(0.0, level * 18.0))
        with self.level_lock:
            self.voice_level = max(self.voice_level * 0.72, normalized)

    def _on_talk_pressed(self) -> None:
        if self.is_listening:
            return

        self.is_listening = True
        self.talk_button.configure(state="disabled", text="Listening...")
        self.status_var.set("Listening. Speak naturally.")

        worker = threading.Thread(target=self._capture_and_process, daemon=True)
        worker.start()

    def _capture_and_process(self) -> None:
        try:
            spoken = self.supervisor.listen_once(level_callback=self._set_level)
            heard = spoken.strip() or "(no speech detected)"
            self.root.after(0, lambda: self.transcript_var.set(f"Last heard: {heard}"))

            if spoken.strip():
                self.root.after(0, lambda: self.status_var.set("Processing objective..."))
                should_continue = self.supervisor.handle_spoken_text(spoken, require_wake_word=False)
                if not should_continue:
                    self.root.after(0, self.root.destroy)
                    return
                self.root.after(0, lambda: self.status_var.set("Done. Press Talk for next objective."))
            else:
                self.root.after(0, lambda: self.status_var.set("No clear speech detected. Try again."))
        except Exception as e:
            error_message = str(e)
            self.root.after(0, lambda message=error_message: self.status_var.set(f"Audio error: {message}"))
        finally:
            with self.level_lock:
                self.voice_level = 0.0
            self.is_listening = False
            self.root.after(0, self._enable_controls)

    def _animate(self) -> None:
        with self.level_lock:
            lvl = self.voice_level
            self.voice_level *= 0.88

        self.canvas.delete("all")

        pulse = self.base_ring + 26 * lvl
        glow = 18 + int(52 * lvl)

        self.canvas.create_oval(
            self.cx - (pulse + glow),
            self.cy - (pulse + glow),
            self.cx + (pulse + glow),
            self.cy + (pulse + glow),
            fill="#102447",
            outline="",
        )

        self.canvas.create_oval(
            self.cx - pulse,
            self.cy - pulse,
            self.cx + pulse,
            self.cy + pulse,
            fill="#1f4ea4",
            outline="#8ec2ff",
            width=2,
        )

        for p in self.particles:
            p.angle += p.speed * (1.0 + lvl * 8.0)
            wobble = math.sin(p.angle * 2.3) * (6 + 34 * lvl)
            r = p.radius + wobble
            x = self.cx + math.cos(p.angle) * r
            y = self.cy + math.sin(p.angle) * r
            size = p.size * (1.0 + lvl * 1.6)

            self.canvas.create_oval(
                x - size,
                y - size,
                x + size,
                y + size,
                fill="#9dd3ff",
                outline="",
            )

        self.canvas.create_text(
            self.cx,
            self.cy,
            text="AURA",
            fill="#ecf3ff",
            font=("Segoe UI Semibold", 26),
        )

        self.root.after(33, self._animate)
