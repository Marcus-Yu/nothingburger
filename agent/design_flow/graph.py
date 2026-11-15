"""The design workflow: ask for a task, sort it, collect a demo if needed, propose a robot.

    ask_task -> classify -> invalid    -> ask_task (with the reason)
                         -> complete   -> design
                         -> incomplete -> request_demo -> design

A skill is complete when the skill store has its motion and force recordings; a demo adds them.
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


def build_graph(
    classifier: Runnable | None = None,
    designer: Runnable | None = None,
    store: SkillStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile the workflow. The LLM steps default to Claude; tests pass stand-ins.

    A checkpointer is required: both pauses (task and demo) use interrupt().
    """
    if classifier is None or designer is None:
        from agent.design_flow.llm import make_classifier, make_designer  # only needs an API key when used

        classifier = classifier or make_classifier()
        designer = designer or make_designer()
    store = store or SkillStore()

    graph = StateGraph(WorkflowState)
    graph.add_node("ask_task", ask_task)
    graph.add_node("classify", make_classify(classifier, store))
    graph.add_node("request_demo", make_request_demo(store))
    graph.add_node("design", make_design(designer, store))

    graph.add_edge(START, "ask_task")
    graph.add_edge("ask_task", "classify")
    graph.add_conditional_edges("classify", route, ["ask_task", "design", "request_demo"])
    graph.add_edge("request_demo", "design")
    graph.add_edge("design", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
