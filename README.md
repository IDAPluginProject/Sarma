# IDA-MCP

**[English](README.md)** | **[中文](README_CN.md)**

<p align="center">
  <img src="Sarma.png" width="75%">
</p>

[![MCP Badge](https://lobehub.com/badge/mcp/captain-ai-hub-ida-mcp)](https://lobehub.com/mcp/captain-ai-hub-ida-mcp)

[wiki](https://github.com/jelasin/IDA-MCP/wiki) · [deepwiki](https://deepwiki.com/jelasin/IDA-MCP)

## IDA-MCP (FastMCP + Multi-instance Gateway)

* Each IDA instance starts its own **FastMCP Streamable HTTP** endpoint at `/mcp`
* A standalone gateway daemon maintains the in-memory instance registry and forwards tool calls
* The gateway serves both the internal API at `/internal` and the client-facing MCP proxy at `/mcp` on `127.0.0.1:11338` by default
* The stdio proxy is a separate subprocess entrypoint that reuses the same proxy tool set
* MCP Resources are exposed by each IDA instance directly, not by the gateway/proxy
* A PySide6 desktop IDE provides installation, configuration, gateway management, and status monitoring

## Architecture

### Repository Structure

```text
IDA-MCP/
├── ide/                        # PySide6 desktop IDE (main project)
│   ├── app/                    # UI layer
│   ├── supervisor/             # Gateway lifecycle & installation
│   ├── resources/ida_mcp/      # Bundled ida_mcp source (installed to IDA plugins/)
│   └── tests/
├── skills/                     # MCP skill documentation
├── test/                       # Test suite
├── API.md                      # Tool & response contract reference
├── README.md / README_CN.md
└── project.md / roadmap.md
```

### Core Infrastructure (inside `ida_mcp/`)

* `rpc.py` - `@tool` / `@resource` / `@unsafe` decorators and registration
* `sync.py` - `@idaread` / `@idawrite` IDA thread synchronization decorators
* `utils.py` - Address parsing, pagination, pattern filtering utilities
* `compat.py` - IDA 8.x/9.x compatibility layer

### API Modules

* `api_core.py` - IDB metadata, function/string/global lists
* `api_analysis.py` - Decompilation, disassembly, cross-references
* `api_memory.py` - Memory reading operations
* `api_modeling.py` - Database shaping (functions, code/data/string creation)
* `api_types.py` - Type operations (prototypes, local types)
* `api_modify.py` - Comments, renaming
* `api_stack.py` - Stack frame operations
* `api_debug.py` - Debugger control (marked unsafe)
* `api_python.py` - Python execution in IDA context (marked unsafe)
* `api_resources.py` - MCP Resources (`ida://` URI patterns)

### Key Features

* **Decorator Chain Pattern**: `@tool` + `@idaread`/`@idawrite` for clean API definitions
* **Batch Operations**: Most tools accept lists for batch processing
* **MCP Resources**: REST-like `ida://` URI patterns for read-only data access on direct instance connections
* **Multi-instance Support**: A standalone gateway on port 11338 manages multiple IDA instances
* **HTTP-first Defaults**: The bundled config defaults to `enable_http=true`, `enable_stdio=false`, and `enable_unsafe=true`
* **IDA 8.x/9.x Compatible**: Compatibility layer handles API differences
* **Desktop IDE**: PySide6 GUI for one-click install, config, gateway control, and status monitoring

## Installation

### Via Desktop IDE (Recommended)

1. Launch the IDE: `python ide/launcher.py`
2. In Settings → Config, set **IDA Python** path (e.g. `D:\IDA\ida-python\python.exe`)
3. Plugin directory defaults to `%APPDATA%\Hex-Rays\IDA Pro\plugins`
4. Click **Install** — the IDE copies plugin files and installs Python dependencies
5. Click **Start Gateway** from the status page or toolbar

### Via Command Line

```bash
python ide/resources/ida_mcp/ida_mcp/command.py gateway start --json
```

### Manual Installation

1. Copy `ida_mcp.py` and `ida_mcp/` from `ide/resources/ida_mcp/` to IDA's `plugins/` directory
2. Install dependencies using IDA's Python:
   ```bash
   <ida_python> -m pip install -r ide/resources/ida_mcp/requirements.txt
   ```
3. Open a target binary in IDA and wait for initial analysis

## Startup Steps

1. Install the plugin (via IDE or manually).
2. Open a target binary and wait for initial analysis.
3. Start the gateway (via IDE or `command.py gateway start`).
4. In IDA, trigger the plugin manually or via `open_in_ida` from the proxy.
5. On startup, the instance:
   * selects a free instance port starting from `10000`
   * serves MCP over `http://127.0.0.1:<instance_port>/mcp/`
   * registers itself with the gateway at `http://127.0.0.1:11338/internal`

Closing an IDA instance only deregisters that instance. The standalone gateway keeps running.

## Current Tools

### Core Tools (`api_core.py`)

* `check_connection` – Gateway/registry health check (ok/count)
* `list_instances` – List all IDA instances registered in the shared gateway
* `get_metadata` – IDB metadata (hash/arch/bits/endian)
* `list_functions` – Paginated function list with optional pattern filter
* `list_globals` – Global symbols (non-functions)
* `list_strings` – Extracted strings
* `list_local_types` – Local type definitions
* `get_entry_points` – Program entry points
* `convert_number` – Number format conversion
* `list_imports` – List imported functions with module names
* `list_exports` – List exported functions/symbols
* `list_segments` – List memory segments with permissions
* `get_cursor` – Get current cursor position and context

### Analysis Tools (`api_analysis.py`)

* `decompile` – Batch decompile functions (Hex-Rays)
* `disasm` – Batch disassemble functions
* `linear_disasm` – Linear disassembly from arbitrary address
* `get_callers` – Structured caller summary grouped by function and call site
* `get_callees` – Structured callee summary grouped by function and call site
* `get_function_signature` – Best-available function signature string
* `xrefs_to` – Batch cross-references to addresses
* `xrefs_from` – Batch cross-references from addresses
* `xrefs_to_field` – Heuristic struct field references
* `find_bytes` – Search for byte patterns with wildcards
* `get_basic_blocks` – Get basic blocks with control flow

### Memory Tools (`api_memory.py`)

* `get_bytes` – Read raw bytes
* `read_scalar` – Read integers with explicit width
* `get_string` – Read null-terminated strings

### Modeling Tools (`api_modeling.py`)

* `create_function` – Create a function at an address
* `delete_function` – Delete an existing function
* `make_code` – Convert bytes at an address into code
* `undefine_items` – Undefine a byte range
* `make_data` – Create typed data items
* `make_string` – Create a string literal

### Type Tools (`api_types.py`)

* `declare_struct` – Create/update local structs
* `declare_enum` – Create/update local enums
* `declare_typedef` – Create/update local typedefs
* `set_function_prototype` – Set function signature
* `set_local_variable_type` – Set local variable type (Hex-Rays)
* `set_global_variable_type` – Set global variable type
* `list_structs` – List all structures/unions
* `get_struct_info` – Get structure definition with fields

### Modify Tools (`api_modify.py`)

* `set_comment` – Batch set comments
* `rename_function` – Rename function
* `rename_local_variable` – Rename local variable (Hex-Rays)
* `rename_global_variable` – Rename global symbol
* `patch_bytes` – Patch bytes at addresses

### Stack Tools (`api_stack.py`)

* `stack_frame` – Get stack frame variables
* `declare_stack` – Create stack variables
* `delete_stack` – Delete stack variables

### Python Tools (`api_python.py`) - Unsafe

* `py_eval` – Execute arbitrary Python code in IDA context

### Debug Tools (`api_debug.py`) - Unsafe

* `dbg_regs` – Get all registers
* `dbg_callstack` – Get call stack
* `dbg_list_bps` – List breakpoints
* `dbg_start` / `dbg_exit` / `dbg_continue` – Start/stop/continue debugging
* `dbg_run_to` – Run to address
* `dbg_add_bp` / `dbg_delete_bp` / `dbg_enable_bp` – Breakpoint management
* `dbg_step_into` / `dbg_step_over` – Single-step execution
* `dbg_read_mem` / `dbg_write_mem` – Debugger memory access

### MCP Resources (`api_resources.py`)

* `ida://idb/metadata` – IDB metadata
* `ida://functions` – Function list
* `ida://function/{addr}` – Single function details
* `ida://function/{addr}/decompile` – Function decompilation snapshot
* `ida://function/{addr}/disasm` – Function disassembly snapshot
* `ida://function/{addr}/basic_blocks` – Function CFG/basic block view
* `ida://function/{addr}/stack` – Function stack/local-variable view
* `ida://strings` / `ida://globals` / `ida://types` / `ida://segments`
* `ida://imports` / `ida://imports/{module}` / `ida://exports` / `ida://entry_points`
* `ida://structs` / `ida://struct/{name}`
* `ida://xrefs/to/{addr}` / `ida://xrefs/from/{addr}` (+ `/summary` variants)
* `ida://memory/{addr}?size=N` – Read memory

## Transport Overview

| Mode | Description | Configuration |
|------|-------------|---------------|
| **HTTP proxy** (recommended) | Connects to the standalone gateway MCP proxy on `11338` | Only requires `url` |
| **stdio proxy** | MCP client launches `ida_mcp/proxy/ida_mcp_proxy.py` as a subprocess | Requires `command` and `args` |
| **Direct instance HTTP** | Connects straight to one IDA instance, mainly useful for `ida://` resources | Requires the selected instance port |

**Proxy Tools:**

| Category | Tools |
|----------|-------|
| Management | `check_connection`, `list_instances`, `select_instance` |
| Lifecycle | `open_in_ida`, `close_ida`, `shutdown_gateway` |
| Core | `list_functions`, `get_metadata`, `list_strings`, `list_globals`, `list_local_types`, `get_entry_points`, `convert_number`, `list_imports`, `list_exports`, `list_segments`, `get_cursor` |
| Analysis | `decompile`, `disasm`, `linear_disasm`, `get_callers`, `get_callees`, `get_function_signature`, `xrefs_to`, `xrefs_from`, `xrefs_to_field`, `find_bytes`, `get_basic_blocks` |
| Modeling | `create_function`, `delete_function`, `make_code`, `undefine_items`, `make_data`, `make_string` |
| Modify | `set_comment`, `rename_function`, `rename_global_variable`, `rename_local_variable`, `patch_bytes` |
| Memory | `get_bytes`, `read_scalar`, `get_string` |
| Types | `set_function_prototype`, `set_local_variable_type`, `set_global_variable_type`, `declare_struct`, `declare_enum`, `declare_typedef`, `list_structs`, `get_struct_info` |
| Stack | `stack_frame`, `declare_stack`, `delete_stack` |
| Python | `py_eval` |
| Debug | `dbg_start`, `dbg_continue`, `dbg_step_into`, `dbg_step_over`, `dbg_regs`, `dbg_add_bp`, `dbg_delete_bp`, ... |

Works with any MCP client: Claude Code, Codex, Cursor, VSCode, LangChain, Cherry Studio, etc.

### Method 1: HTTP Proxy Mode (Recommended)

```json
{
  "mcpServers": {
    "ida-mcp": {
      "url": "http://127.0.0.1:11338/mcp"
    }
  }
}
```

### Method 2: stdio Proxy Mode

```json
{
  "mcpServers": {
    "ida-mcp-proxy": {
      "command": "path/to/ida-python/python.exe",
      "args": ["path/to/ida_mcp/proxy/ida_mcp_proxy.py"]
    }
  }
}
```

## Configuration

Edit `ida_mcp/config.conf` (located in the IDA plugins directory after installation):

```ini
enable_stdio = false
enable_http = true
enable_unsafe = true
wsl_path_bridge = false

http_host = "0.0.0.0"
http_port = 11338
http_path = "/mcp"

ida_default_port = 10000
ida_host = "127.0.0.1"
# ida_path = "C:\\Path\\To\\ida.exe"
# ida_python = "C:\\Path\\To\\ida-python\\python.exe"
open_in_ida_bundle_dir = ""
open_in_ida_autonomous = true
auto_start = false
server_name = "IDA-MCP"

request_timeout = 30
debug = false
```

## Command Helper

The installed `command.py` provides CLI access:

```bash
python <plugins>/ida_mcp/command.py gateway start
python <plugins>/ida_mcp/command.py gateway status
python <plugins>/ida_mcp/command.py gateway stop
python <plugins>/ida_mcp/command.py ida list
python <plugins>/ida_mcp/command.py ida open ./target.exe
python <plugins>/ida_mcp/command.py tool call get_metadata --port 10000
```

Add `--json` for machine-readable output.

## Development

It's not about having many tools, but about having precise ones; the power of the API is what truly matters. Additionally, the tools should be comprehensive, and the more tools there are, the more obstacles there are for the model to call them. If certain tools can be achieved through existing ones, then those tools are unnecessary. What I need are the missing tools—the ones that existing tools cannot accomplish.

## License

See [LICENSE](LICENSE).
