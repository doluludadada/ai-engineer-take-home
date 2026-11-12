# List the commands
default:
    @just --list

# Install Python 3.14 and the dependencies into .venv
setup:
    uv sync

# Run the tests: `just test` for all, `just test tests/q2` for one question
test *args:
    uv run pytest {{ args }}

# Format check, lint and type check
check:
    uv run ruff format --check .
    uv run ruff check .
    uv run pyright

# Question 2: start the demo server with sample orders, a member and a customer service agent
demo:
    PYTHONPATH=order_tools/src:. uv run python order_tools/demo.py

# Question 2: call one tool on the running demo server as member or customer_service,
# e.g. just call member get_order '{"order_id": "ORD-100001"}'
call who tool arguments='{}':
    @PYTHONPATH=order_tools/src:. uv run python order_tools/demo.py call '{{ who }}' {{ tool }} '{{ arguments }}'

# Question 2: start the server from the ORDER_TOOLS_* environment variables
serve:
    PYTHONPATH=order_tools/src:. uv run python -m d_presentation.mcp_tools.server
