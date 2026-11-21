import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from graph import get_app

app = FastAPI(title="AI Travel Booking System")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

AGENT_META = {
    "supervisor":        ("🧭", "Supervisor"),
    "flight_agent":      ("✈️", "Flight Agent"),
    "hotel_agent":       ("🏨", "Hotel Agent"),
    "transport_agent":   ("🚇", "Transport Agent"),
    "weather_agent":     ("🌤️", "Weather Agent"),
    "budget_agent":      ("💰", "Budget Agent"),
    "itinerary_agent":   ("🗓️", "Itinerary Agent"),
    "human_approval":    ("🙋", "Human Approval"),
    "final_response":    ("✅", "Final Response"),
}

NODE_TEXT_KEYS = {
    "flight_agent": "flight_results",
    "hotel_agent": "hotel_results",
    "transport_agent": "transport_results",
    "weather_agent": "weather_results",
    "budget_agent": "budget_results",
    "itinerary_agent": "itinerary",
}


class PlanRequest(BaseModel):
    query: str
    thread_id: str = "web_user"


class ApprovalRequest(BaseModel):
    thread_id: str
    approved: bool
    feedback: str = ""


class AnswerRequest(BaseModel):
    thread_id: str
    origin: str


def _run_config(thread_id: str, step: str) -> dict:
    """LangGraph config + LangSmith tracing info.

    `thread_id` in metadata is what LangSmith uses to group the plan -> answer -> approve
    runs of one conversation into a single Thread (Project -> Threads tab).
    """
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"travel_planner.{step}",
        "tags": ["travel-planner", step],
        "metadata": {"thread_id": thread_id, "step": step},
    }


def _initial_state(query: str) -> dict:
    return {
        "messages": [HumanMessage(content=query)],
        "user_query": query,
        "selected_agents": [],
        "trip_constraints": {},
        "flight_results": "",
        "hotel_results": "",
        "transport_results": "",
        "weather_results": "",
        "budget_results": "",
        "itinerary": "",
        "llm_calls": 0,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/plan")
async def plan(req: PlanRequest):
    """Run the multi-agent pipeline and stream updates as SSE.
    Ends with either 'done' or 'approval' (when the graph interrupts for human review)."""
    async def event_stream():
        config = _run_config(req.thread_id, "plan")
        collected = {"itinerary": "", "final_response": "", "llm_calls": 0}
        travel_app = await get_app()

        try:
            try:
                async for chunk in travel_app.astream(
                    _initial_state(req.query),
                    config=config,
                    stream_mode="updates",
                ):
                    for event in _format_chunk(chunk, collected):
                        yield event
            except GraphInterrupt:
                pass  # graph paused, handled by _finish below

            async for event in _finish(travel_app, config, collected, req.thread_id):
                yield event
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/answer")
async def answer(req: AnswerRequest):
    """Resume the graph after the user answers a question (e.g. departure city)."""
    async def event_stream():
        config = _run_config(req.thread_id, "answer")
        collected = {"itinerary": "", "final_response": "", "llm_calls": 0}
        travel_app = await get_app()

        try:
            try:
                async for chunk in travel_app.astream(
                    Command(resume={"origin": req.origin}),
                    config=config,
                    stream_mode="updates",
                ):
                    for event in _format_chunk(chunk, collected):
                        yield event
            except GraphInterrupt:
                pass  # paused again (e.g. approval), handled by _finish

            async for event in _finish(travel_app, config, collected, req.thread_id):
                yield event
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/approve")
async def approve(req: ApprovalRequest):
    """Resume the graph after human approval/rejection and stream the final response."""
    async def event_stream():
        config = _run_config(req.thread_id, "approve")
        collected = {"itinerary": "", "final_response": "", "llm_calls": 0}
        travel_app = await get_app()

        try:
            try:
                async for chunk in travel_app.astream(
                    Command(resume={"approved": req.approved, "feedback": req.feedback}),
                    config=config,
                    stream_mode="updates",
                ):
                    for event in _format_chunk(chunk, collected):
                        yield event
            except GraphInterrupt:
                pass

            async for event in _finish(travel_app, config, collected, req.thread_id):
                yield event
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _interrupt_value(state) -> dict:
    """Extract the payload of the first pending interrupt, if any."""
    for task in getattr(state, "tasks", None) or []:
        for iv in getattr(task, "interrupts", None) or []:
            return iv.value if isinstance(iv.value, dict) else {}
    return {}


async def _finish(travel_app, config, collected, thread_id):
    """After a stream: either ask a question, ask approval, or send done."""
    state = await travel_app.aget_state(config)
    if state.next:  # graph is paused on an interrupt
        draft = (state.values or {}).get("itinerary", "")
        if draft:
            yield f"data: {json.dumps({'type': 'approval', 'thread_id': thread_id, 'itinerary': draft})}\n\n"
        else:
            question = _interrupt_value(state).get("question", "More information needed")
            yield f"data: {json.dumps({'type': 'question', 'thread_id': thread_id, 'question': question})}\n\n"
    else:
        yield f"data: {json.dumps({'type': 'done', 'itinerary': collected.get('itinerary', ''), 'final_response': collected.get('final_response', ''), 'llm_calls': collected.get('llm_calls', 0)})}\n\n"


def _format_chunk(chunk: dict, collected: dict):
    """Convert a stream chunk into SSE 'agent' events + update collected data."""
    events = []
    for node_name, state_update in chunk.items():
        if node_name == "__interrupt__":
            continue  # human-in-the-loop pause, handled after the stream ends
        if node_name == "supervisor":
            collected["selected"] = state_update.get("selected_agents", [])

        text = state_update.get(NODE_TEXT_KEYS.get(node_name, ""), "")
        if node_name == "final_response":
            text = state_update.get("final_response", "")
            collected["final_response"] = text

        if node_name in ("itinerary_agent", "final_response"):
            collected["itinerary"] = state_update.get("itinerary", collected.get("itinerary", ""))

        collected["llm_calls"] = state_update.get("llm_calls", collected["llm_calls"])

        icon, label = AGENT_META.get(node_name, ("🔧", node_name))
        events.append(
            f"data: {json.dumps({'type': 'agent', 'node': node_name, 'icon': icon, 'label': label, 'text': text})}\n\n"
        )
    return events
