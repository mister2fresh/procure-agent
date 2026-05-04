# From primitives to LangGraph

The from-scratch ReAct loop in `src/procure_agent/agent.py` runs supplier-quote extraction without LangGraph. This note maps each piece of that loop to its counterpart in `src/procure_agent/graph.py` so the translation reads as a refactor, not a rewrite.

## The loop becomes nodes

## Tool dispatch becomes a tools node

## The `for` over turns becomes a conditional edge

## Manual message accumulation becomes state with a reducer

## The implicit "no checkpointing" becomes MemorySaver

## Halting for human approval becomes `interrupt_before`
