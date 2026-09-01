# Development

## Supported environment

Use Windows with Python 3.11 and the current Node.js LTS release. Python 3.9+
is accepted by the package and exercised by the test suite, but 3.11 is the
recommended local and deployment version.

The quickest bootstrap is:

```powershell
.\scripts\start.ps1
```

It creates `.venv`, installs missing `server` and `vertex` Python extras,
installs npm packages when `node_modules` is absent, starts the backend, and
launches Electron. It never overwrites an existing `.env`.

For a full development environment:

```powershell
.\scripts\start.ps1 -Frontend none
.\.venv\Scripts\python.exe -m pip install -e ".[server,vertex,dev]"
```

Use `-Install` to refresh dependencies and `-Build` to force a frontend build.

## Configuration

Local settings come from `.env`, which is excluded from Git. Start from
`.env.example`. Live planning and free-form modification proposals use the
configured server-side AI provider and Application Default Credentials:

```powershell
gcloud auth application-default login
```

Set `AURA_GCP_PROJECT` if credentials do not supply a quota project. The
deterministic planner and test harness do not require cloud access. Provider and
model identifiers are operational configuration and are not rendered as UI
output.

SQLite and local artifacts are the normal development storage. Their platform
default is `%LOCALAPPDATA%\AURA`. Use `AURA_DATA_DIR`,
`AURA_WORKSPACE_DB_PATH`, or `AURA_WORKSPACE_ARTIFACT_DIR` for an isolated
workspace.

## Run modes

```powershell
# Desktop application and backend
.\scripts\start.ps1

# Browser application and backend
.\scripts\start.ps1 -Frontend browser

# Backend only
.\scripts\start.ps1 -Frontend none
```

The backend command used by the launcher is equivalent to:

```powershell
.\.venv\Scripts\python.exe -m aura.workspace.server --host 127.0.0.1 --port 8765
```

The Electron shell waits for `/health/live` and then loads the same application
served to browsers.

## Frontend workflow

The React/TypeScript application is isolated under
`src/aura/workspace/web/frontend`:

```powershell
Set-Location src\aura\workspace\web\frontend
npm ci
npm test
npm run build
npm run test:browser
npm run test:electron
```

Vite writes the production bundle to `../representation`. The Python server and
Electron shell both consume that output. `@tscircuit/core` runs only in the
bounded Node generator; the browser renders Circuit JSON and lazy-loads
`cascade-core` for supported mechanical representations.

## Validation

Run the default non-live checks from the repository root:

```powershell
.\scripts\test.ps1 -Module all
```

The script runs Python tests, frontend unit tests, a production frontend build,
and Python bytecode compilation. Browser and Electron smoke suites remain
explicit commands because they launch browser processes.

Live Vertex, voice, desktop-integration, Ollama compatibility, and Unreal tests
are opt-in and host-dependent. Historical reports are not proof of the current
checkout.

## Generated and local data

Do not commit `.env`, `.venv`, `node_modules`, Python caches, Playwright output,
Electron packages, Terraform state, databases, generated workspaces, logs,
downloaded models, or runtime artifacts. Terraform state and `.env` are local
operational data, not disposable cleanup targets.

Run `.\scripts\cleanup.ps1` to delete only the repository's reproducible test,
package, workspace, egg metadata, and Python cache output. Add `-StopBackend`
when port 8765 is occupied by the local AURA backend and it should be stopped
before cleanup.

The QML assistant, voice stack, and Unreal domain remain optional compatibility
systems and are not imported during normal workspace startup.
