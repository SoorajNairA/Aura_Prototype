# AURA

## Autonomous Unified Reasoning Assistant

AURA is an AI engineering workspace for understanding, analyzing, verifying, and reasoning about engineering systems. It connects system requirements, components, interfaces, physical representations, electrical connections, verification findings, and engineering work in one workspace.

Instead of behaving like a conventional chatbot, AURA is designed to act as an engineering partner: it builds a structured model, explains relationships, evaluates proposed changes, and keeps representations synchronized around the same system definition.

## What AURA Does

- Represents engineering systems as components, interfaces, and relationships.
- Visualizes physical assemblies in an interactive 3D view.
- Generates electrical schematic representations.
- Connects selections and identities across assembly and schematic views.
- Verifies graph, reference, electrical, physical, and safety relationships.
- Tracks engineering work and its lifecycle.
- Evaluates proposed changes through What-If analysis before they are applied.
- Preserves consistent component and system relationships across the workspace.

These capabilities are connected through a shared engineering graph rather than implemented as isolated screens.

## How It Works

```text
Requirement / Mission
        -> Engineering system
        -> Components and relationships
        -> 3D assembly + electrical schematic
        -> Verification
        -> Engineering Work
        -> What-If analysis
        -> Re-verification
```

AURA turns an engineering intent into a structured system model. The model drives its visual representations and verification results. Proposed changes can then be reviewed for affected components and findings before the updated system is verified again.

## Architecture

```text
AURA Workspace (browser or Electron)
                 |
        HTTP and WebSocket API
                 |
     Workspace and Planner services
                 |
          Engineering Graph
        /          |           \
  3D assembly   Schematic   Verification
        \          |           /
        What-If analysis and Work
```

The Python workspace service owns project state, revisions, events, persistence, planning, and verification. The engineering graph is the shared model for entities and relationships. A React interface presents the workspace in a browser or Electron shell, while representation services compile 3D and schematic data from the same graph.

## Key Features

### 3D Assembly

Interactive visualization of physical components, geometry, placement, and assembly relationships using Three.js and OpenCascade-based browser assets.

### Schematic

Electrical components and connections are compiled to Circuit JSON and rendered with tscircuit tooling.

### Verification

Deterministic checks identify invalid references, relationship issues, electrical and physical findings, safety concerns, and readiness limitations. Verification results are engineering guidance, not production certification.

### Work

Engineering work items capture tasks, status, dependencies, evidence, and lifecycle events associated with the system.

### What-If Analysis

Proposed changes can be evaluated before acceptance. Where supported, AURA shows affected components, relationship changes, and verification deltas.

### Connected Engineering Model

Components keep stable identities across the engineering graph, 3D assembly, schematic, verification, and work views, allowing the workspace to show the same system from multiple perspectives.

## Technology

- Python 3.9+ with FastAPI, Uvicorn, Pydantic, and Pint
- SQLite project storage by default, with optional PostgreSQL and Google Cloud Storage adapters
- React 18 and TypeScript
- Vite for frontend builds
- Electron for the desktop shell
- Three.js and `cascade-core`/OpenCascade WebAssembly for 3D representation
- tscircuit and Circuit JSON for schematic generation and display
- Optional Google Vertex AI planner integration
- pytest, Vitest, and Playwright for automated testing

## Requirements

- Windows with PowerShell
- Python 3.9 or newer; Python 3.11 is recommended
- A current Node.js LTS release with npm
- Optional: Google Cloud Application Default Credentials for Vertex AI planning

## Installation

The launcher creates a Python virtual environment and installs missing backend and frontend dependencies automatically:

```powershell
git clone <repository-url> Aura_Prototype
Set-Location Aura_Prototype
Copy-Item .env.example .env
.\scripts\start.ps1 -Install -Build
```

Edit `.env` if you want to configure cloud planning or override the local defaults. The file is excluded from Git.

For manual installation:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[server,vertex]"
Set-Location src\aura\workspace\web\frontend
npm ci
npm run build
Set-Location ..\..\..\..\..
```

## Running AURA

Launch the backend and Electron desktop application:

```powershell
.\scripts\start.bat
```

Open the browser interface instead:

```powershell
.\scripts\start.ps1 -Frontend browser
```

Run only the backend:

```powershell
.\scripts\start.ps1 -Frontend none
```

The default workspace URL is <http://127.0.0.1:8765/>. The liveness endpoint is <http://127.0.0.1:8765/health/live>.

### Planning modes

The start screen provides an **Offline / Online** switch in the top-right corner.

- **Offline Engineering** is the default. It requires no account, internet connection, API key, or local model. The options panel shows the bounded requirement format and example systems supported by the deterministic planner.
- **Online** uses the Vertex AI planner for broader natural-language requirements. Enter a Google Cloud project ID in the options panel; AURA saves this non-secret value to the local `.env` file. Authentication remains in Google Application Default Credentials and is never stored by AURA. If ADC is not connected, run `gcloud auth application-default login` locally.

The local configuration endpoint is disabled in cloud deployments and rejects credential or API-key fields.

To run the Electron shell separately after the backend is available:

```powershell
Set-Location src\aura\workspace\web\frontend
npm run electron:dev
```

## Project Structure

```text
src/aura/engineering_graph/   Shared engineering entities and relationships
src/aura/planner/             Structured proposal planning
src/aura/verification/        Engineering verification rules and results
src/aura/workspace/           Workspace services, API, representations, and UI
src/aura/infrastructure/      Persistence, model-provider, voice, and host adapters
src/aura/legacy/              Optional compatibility subsystems
tests/                        Python unit and integration tests
migrations/                   SQLite and PostgreSQL schemas
infra/                        Optional cloud infrastructure definitions
scripts/                      Startup, testing, cleanup, and deployment commands
docs/                         Architecture, development, deployment, and notices
```

## License

AURA is available under the [MIT License](LICENSE). See [third-party notices](docs/THIRD_PARTY_NOTICES.md) for bundled technology details.
