import json
import os
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from config import get_llm
from mcp_client import current_weather, forecast, list_airlines, list_airports, tavily_search
from state import TravelState

llm = get_llm()

# Verbose agent logging; enable with DEBUG_LOGS=1 in .env
DEBUG_LOGS = os.getenv("DEBUG_LOGS", "").lower() in ("1", "true", "yes")


def _debug(*args):
    if DEBUG_LOGS:
        print(*args)


def _format_search_results(result: Any, max_items: int = 5) -> str:
    """Turn a raw Tavily MCP result (list of content blocks holding JSON) into readable markdown."""
    blocks = result if isinstance(result, list) else [result]
    items = []
    for block in blocks:
        text = block.get("text", "") if isinstance(block, dict) else str(block)
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            if text.strip():
                items.append({"content": text.strip()})
            continue
        items.extend(data.get("results", []) if isinstance(data, dict) else data or [])

    lines = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or "Result"
        url = item.get("url")
        snippet = (item.get("content") or "").strip().replace("\n", " ")
        if len(snippet) > 300:
            snippet = snippet[:300].rsplit(" ", 1)[0] + "…"
        lines.append(f"- **[{title}]({url})**  \n  {snippet}" if url else f"- **{title}**  \n  {snippet}")
    return "\n".join(lines) or "No results found."

def _llm_text(system: str, prompt: str) -> str:
    response = llm.invoke(
        [
            SystemMessage(content=system),
            HumanMessage(content=prompt),
        ]
    )
    return response.content

def _json_from_llm(text: str) -> dict:
    _debug("\n========== RAW LLM RESPONSE ==========")
    _debug(text)
    _debug("======================================\n")

    start = text.index("{")
    end = text.rindex("}") + 1

    json_text = text[start:end]

    _debug("\n========== EXTRACTED JSON ==========")
    _debug(json_text)
    _debug("====================================\n")

    return json.loads(json_text)


def supervisor_agent(state: TravelState):
    query = state["user_query"]

    guardrail_prompt = f"""
    Determine whether the following request is a valid travel planning request.

    Return only JSON in this format:

    {{
        "allowed": true,
        "reason": ""
    }}

    User request:
    {query}
    """

    guardrail_raw = _llm_text(
        "You are an input validation guardrail. Return strict JSON only.",
        guardrail_prompt,
    )

    _debug("\n========== GUARDRAIL RAW RESPONSE ==========")
    _debug(guardrail_raw)
    _debug("============================================\n")

    guardrail_result = _json_from_llm(guardrail_raw)

    _debug("\n========== GUARDRAIL PARSED RESPONSE ==========")
    _debug(json.dumps(guardrail_result, indent=2))
    _debug("================================================\n")

    if not guardrail_result.get("allowed", False):
        reason = guardrail_result.get(
            "reason",
            "Request rejected by input guardrail."
        )

        return {
            "selected_agents": [],
            "trip_constraints": {},
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [
                AIMessage(content=f"Guardrail blocked request: {reason}")
            ],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }



    prompt = f"""
You are the supervisor of a real-world multi-agent travel planning system.

Decide which specialist agents are needed for this user request.

Available agents:
- flight_agent: use when flights, airports, airlines, routes, or airfare guidance are needed
- hotel_agent: use when hotels, stays, neighborhoods, or accommodation are needed
- transport_agent: use when local transport, trains, metro, car rental, airport transfers, or getting around is needed
- weather_agent: use when weather, climate, season, packing, or forecast is useful
- budget_agent: use when budget, affordability, cost, or price constraints are mentioned
- itinerary_agent: almost always needed to produce the travel plan

Return only JSON with this schema:
{{
  "selected_agents": ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"],
  "trip_constraints": {{
    "destination": "",
    "origin": "",
    "duration": "",
    "budget": "",
    "travel_style": "",
    "special_preferences": []
  }},
  "reasoning": ""
}}

User request:
{query}
"""


    raw = _llm_text(
        "You route work to specialist agents. Return strict JSON only.",
        prompt,
    )

    _debug("\n========== RAW LLM RESPONSE ==========")
    _debug(raw)
    _debug("======================================\n")

    parsed = _json_from_llm(raw)

    #parsed = json.loads(raw)

    _debug("\n========== PARSED JSON ==========")
    _debug(json.dumps(parsed, indent=2))
    _debug("=================================\n")

    '''
    At first glance they look the same, but they're not:

    raw → string returned by the LLM
    parsed → Python dictionary created from that string

    If you really want to demonstrate the difference, add:

    _debug(type(raw))
    _debug(type(parsed))
    Output:

    <class 'str'>
    <class 'dict'>
    Yes, you can get output from a string, but it's much harder and less reliable.
    '''

    selected = parsed["selected_agents"]

    return {
        "selected_agents": selected,
        "trip_constraints": parsed["trip_constraints"],
        "supervisor_reasoning": parsed["reasoning"],
        "messages": [AIMessage(content="Supervisor created the agent plan.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }






# without guardrail

# def supervisor_agent(state: TravelState):
#     query = state["user_query"]
#     prompt = f"""
# You are the supervisor of a real-world multi-agent travel planning system.

# Decide which specialist agents are needed for this user request.

# Available agents:
# - flight_agent: use when flights, airports, airlines, routes, or airfare guidance are needed
# - hotel_agent: use when hotels, stays, neighborhoods, or accommodation are needed
# - weather_agent: use when weather, climate, season, packing, or forecast is useful
# - budget_agent: use when budget, affordability, cost, or price constraints are mentioned
# - itinerary_agent: almost always needed to produce the travel plan

# Return only JSON with this schema:
# {{
#   "selected_agents": ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"],
#   "trip_constraints": {{
#     "destination": "",
#     "origin": "",
#     "duration": "",
#     "budget": "",
#     "travel_style": "",
#     "special_preferences": []
#   }},
#   "reasoning": ""
# }}

# User request:
# {query}
# """

#     raw = _llm_text(
#         "You route work to specialist agents. Return strict JSON only.",
#         prompt,
#     )

#     print("\n========== RAW LLM RESPONSE ==========")
#     print(raw)
#     print("======================================\n")

#     parsed = _json_from_llm(raw)
#     print("\n========== PARSED JSON ==========")
#     print(json.dumps(parsed, indent=2))
#     print("=================================\n")

#     print(type(raw))
#     print(type(parsed))

#     selected = parsed["selected_agents"]

#     return {
#         "selected_agents": selected,
#         "trip_constraints": parsed["trip_constraints"],
#         "supervisor_reasoning": parsed["reasoning"],
#         "messages": [AIMessage(content="Supervisor created the agent plan.")],
#         "llm_calls": state.get("llm_calls", 0) + 1,
#     }



async def flight_agent(state: TravelState):
    query = state["user_query"]
    constraints = state["trip_constraints"]
    destination = constraints.get("destination", "")
    origin = (constraints.get("origin", "") or "").strip()

    _debug("\n========== FLIGHT AGENT INPUT ==========")
    _debug("Query:", query)
    _debug("Constraints:", constraints)
    _debug("========================================\n")

    # No departure city -> pause the graph and ASK the human
    if not origin or origin.lower() in ("unknown", "n/a", "none"):
        answer = interrupt({
            "question": f"Where are you flying from for your trip to {destination or 'your destination'}? (e.g. Paris, Madrid, London)",
            "for": "origin",
        })
        origin = (answer.get("origin", "") or "").strip()
        if not origin:
            return {
                "flight_results": "⚠️ Still no departure city — fill in flight details manually.",
                "messages": [AIMessage(content="Flight agent got no origin.")],
                "llm_calls": state.get("llm_calls", 0),
            }

    airports = await list_airports(destination, limit=10)
    airlines = await list_airlines("", limit=10)

    _debug("\n========== AIRPORT MCP DATA ==========")
    _debug(airports)
    _debug("======================================\n")

    _debug("\n========== AIRLINE MCP DATA ==========")
    _debug(airlines)
    _debug("======================================\n")

    prompt = f"""
Create flight guidance for this trip.

User request:
{query}

Departure city:
{origin}

Trip constraints:
{constraints}

Airport MCP data:
{str(airports)[:3000]}

Airline MCP data:
{str(airlines)[:3000]}

Include likely departure/arrival airports, relevant airlines,
estimated duration, fare range, peak season warning,
and booking advice.
"""

    result = _llm_text(
        "You are a flight planning specialist.",
        prompt,
    )

    _debug("\n========== FLIGHT AGENT OUTPUT ==========")
    _debug(result)
    _debug("=========================================\n")

    return {
        "flight_results": result,
        "messages": [AIMessage(content="Flight agent completed.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }




async def hotel_agent(state: TravelState):
    query = f"Best hotels and areas to stay for: {state['user_query']}"

    _debug("\n========== HOTEL AGENT INPUT ==========")
    _debug(query)
    _debug("=======================================\n")

    result = _format_search_results(await tavily_search(query))

    _debug("\n========== HOTEL SEARCH RESULT ==========")
    _debug(result)
    _debug("=========================================\n")

    return {
        "hotel_results": result,
        "messages": [AIMessage(content="Hotel agent completed.")],
    }


async def transport_agent(state: TravelState):
    constraints = state.get("trip_constraints", {})
    destination = constraints.get("destination", "")
    query = f"Getting around {destination}: public transport, metro, trains, airport transfers, car rental for: {state['user_query']}"

    result = _format_search_results(await tavily_search(query))

    return {
        "transport_results": result,
        "messages": [AIMessage(content="Transport agent completed.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


async def weather_agent(state: TravelState):
    constraints = state["trip_constraints"]
    city = constraints.get("destination", "")
    if not city:
        return {
            "weather_results": "⚠️ Destination city unknown — cannot fetch weather.",
            "messages": [AIMessage(content="Weather agent needs a destination.")],
        }

    _debug("\n========== WEATHER AGENT INPUT ==========")
    _debug("City:", city)
    _debug("=========================================\n")

    weather_data = await current_weather(city)
    forecast_data = await forecast(city)

    _debug("\n========== CURRENT WEATHER ==========")
    _debug(weather_data)
    _debug("=====================================\n")

    _debug("\n========== WEATHER FORECAST ==========")
    _debug(forecast_data)
    _debug("======================================\n")

    result = f"""
Current weather:
{weather_data}

Forecast:
{forecast_data}
"""

    _debug("\n========== WEATHER AGENT OUTPUT ==========")
    _debug(result)
    _debug("==========================================\n")

    return {
        "weather_results": result,
        "messages": [AIMessage(content="Weather agent completed.")],
    }



def budget_agent(state: TravelState):

    _debug("\n========== BUDGET AGENT INPUT ==========")
    _debug("Trip Constraints:")
    _debug(state.get("trip_constraints"))
    _debug("\nFlight Results:")
    _debug(state.get("flight_results"))
    _debug("\nHotel Results:")
    _debug(state.get("hotel_results"))
    _debug("\nWeather Results:")
    _debug(state.get("weather_results"))
    _debug("=========================================\n")

    prompt = f"""
Analyze whether this trip plan is realistic for the user's budget.

User request:
{state['user_query']}

Constraints:
{state.get('trip_constraints', {})}

Flight results:
{state.get('flight_results', '')}

Hotel results:
{state.get('hotel_results', '')}

Weather results:
{state.get('weather_results', '')}

Return a concise budget assessment with:
1. estimated cost categories
2. risk areas
3. money-saving suggestions
4. whether the plan seems feasible
"""

    result = _llm_text(
        "You are a practical travel budget analyst.",
        prompt,
    )

    _debug("\n========== BUDGET AGENT OUTPUT ==========")
    _debug(result)
    _debug("=========================================\n")

    return {
        "budget_results": result,
        "messages": [AIMessage(content="Budget agent completed.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }



def itinerary_agent(state: TravelState):

    _debug("\n========== ITINERARY AGENT INPUT ==========")
    _debug("Trip Constraints:")
    _debug(state.get("trip_constraints"))

    _debug("\nFlight Results:")
    _debug(state.get("flight_results"))

    _debug("\nHotel Results:")
    _debug(state.get("hotel_results"))

    _debug("\nWeather Results:")
    _debug(state.get("weather_results"))

    _debug("\nBudget Results:")
    _debug(state.get("budget_results"))
    _debug("===========================================\n")

    prompt = f"""
Create a clear draft travel itinerary.

User request:
{state['user_query']}

Trip constraints:
{state.get('trip_constraints', {})}

Flight results:
{state.get('flight_results', '')}

Hotel results:
{state.get('hotel_results', '')}

Transport results:
{state.get('transport_results', '')}

Weather results:
{state.get('weather_results', '')}

Budget results:
{state.get('budget_results', '')}

Make the output structured, practical, and ready for human review.
"""

    result = _llm_text(
        "You are an expert itinerary planner.",
        prompt,
    )

    _debug("\n========== ITINERARY OUTPUT ==========")
    _debug(result)
    _debug("======================================\n")

    approval_request = f"""
Please review this draft travel plan.

{result}

Reply with approval or feedback.
"""

    return {
        "itinerary": result,
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def human_approval_agent(state: TravelState):
    feedback = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "expected_response": {
                "approved": True,
                "feedback": "Optional feedback for revision",
            },
        }
    )

    approved = feedback["approved"]
    human_feedback = feedback["feedback"]

    return {
        "approved": approved,
        "human_feedback": human_feedback,
        "messages": [AIMessage(content="Human approval step completed.")],
    }



def final_response_agent(state: TravelState):

    _debug("\n========== FINAL AGENT INPUT ==========")
    _debug("Approved:", state.get("approved"))
    _debug("Feedback:", state.get("human_feedback"))
    _debug("=======================================\n")

    if state["approved"]:
        prompt = f"""
The human approved this draft itinerary.

Produce the final polished travel plan.

Draft itinerary:
{state['itinerary']}

Budget notes:
{state.get('budget_results', '')}
"""
    else:
        prompt = f"""
The human did not approve the draft.

Original user request:
{state['user_query']}

Draft itinerary:
{state['itinerary']}

Human feedback:
{state['human_feedback']}

Budget notes:
{state.get('budget_results', '')}
"""

    result = _llm_text(
        "You produce final user-ready travel plans.",
        prompt,
    )

    _debug("\n========== FINAL RESPONSE ==========")
    _debug(result)
    _debug("====================================\n")

    return {
        "final_response": result,
        "messages": [AIMessage(content=result)],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
