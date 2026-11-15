"""The design workflow: ask for a task, sort it, collect a demo if needed, propose a robot.

    ask_task -> find_building -> classify -> invalid    -> ask_task (with the reason)
                         -> complete   -> design
                         -> incomplete -> request_demo -> design

find_building settles which building the job is in (named in the job, chosen in the studio, or asked)
and loads its world from the 3D database when it has none yet; it runs with the default designer.
A skill is complete when the skill store has its motion and force recordings; a demo adds them.
The design step is the design and pathing pipeline (agent/design_flow/pipeline.py) by default.
"""

from langchain_core.runnables import Runnable
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agent.design_flow.nodes.classify import make_classify, route
from agent.design_flow.nodes.demo import make_request_demo
from agent.design_flow.nodes.design import make_design
from agent.design_flow.nodes.intake import ask_task
from agent.design_flow.skills import SkillStore
from agent.design_flow.state import WorkflowState


def default_classifier(fallback: Runnable | None = None) -> Runnable:
    """Snap first; then Claude Sonnet when ANTHROPIC_API_KEY is set, else `fallback`, else a polite refusal."""
    import os

    from agent.design_flow.fast import make_mixed_classifier

    slow, label = fallback, "the stand-in keyword classifier"
    if os.environ.get("ANTHROPIC_API_KEY"):
        from agent.design_flow.llm import make_classifier

        slow, label = make_classifier(), "Claude Sonnet"
    return make_mixed_classifier(slow, slow_label=label)


def build_graph(
    classifier: Runnable | None = None,
    designer: Runnable | None = None,
    store: SkillStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    finder=None,
):
    """Compile the workflow. The LLM steps default to Claude; tests pass stand-ins.

    A checkpointer is required: both pauses (task and demo) use interrupt().
    """
    if classifier is None:  # SubQ Snap decides fast; Claude Sonnet takes what Snap can't settle (fast.py)
        classifier = default_classifier()
    can_plan = None
    if designer is None:  # the design and pathing pipeline; llm.make_designer() is the one-call alternative
        from agent.design_flow import buildings
        from agent.design_flow.nodes.building import make_find_building
        from agent.design_flow.pipeline import can_plan, make_pipeline_designer

        designer = make_pipeline_designer()
        finder = finder or make_find_building(buildings.resolve, buildings.load, buildings.get, buildings.space_id)
    store = store or SkillStore()

    graph = StateGraph(WorkflowState)
    graph.add_node("ask_task", ask_task)
    graph.add_node("classify", make_classify(classifier, store, can_plan))
    graph.add_node("request_demo", make_request_demo(store))
    graph.add_node("design", make_design(designer, store))

    graph.add_edge(START, "ask_task")
    if finder is not None:
        graph.add_node("find_building", finder)
        graph.add_edge("ask_task", "find_building")
        graph.add_edge("find_building", "classify")
    else:
        graph.add_edge("ask_task", "classify")
    graph.add_conditional_edges("classify", route, ["ask_task", "design", "request_demo"])
    graph.add_edge("request_demo", "design")
    graph.add_edge("design", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
