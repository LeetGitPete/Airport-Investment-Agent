"""Scripted LLM outputs for the four assignment questions and their follow-ups.

These are goldens for the *plumbing*, not for the model: a fixed Plan / specialist report / synthesis per
turn, so the whole path (plan -> tools or engines -> synthesis -> session memory) is asserted end to end with
no network. Every number in the resulting answers must still come from the fakes' reports and tool results.
"""
from __future__ import annotations

from typing import Any

from airport_agent.contracts import LLMResult, ToolCall

P2_FOCUS = ["pct_arr_delay_gt15", "avg_dep_delay_min", "taxi_out_p80_min", "ops_per_runway",
            "npias_capacity_label", "peak_hour_ops_ratio", "pax_per_gate", "slot_or_cap_flag"]


def plan(**over: Any) -> dict[str, Any]:
    """A complete PLAN_SCHEMA object; override only what the question needs."""
    base: dict[str, Any] = {"intent": "analytical", "engines": [], "question_type": "none", "airports": [],
                            "states": [], "faa_regions": [], "hub_sizes": [], "horizons": [],
                            "scoring_preset": "none", "focus_metrics": [], "peer_group": "none", "hint": "",
                            "tool_calls": [], "presentation_notes": ""}
    base.update(over)
    return base


def specialist(**over: Any) -> dict[str, Any]:
    """A complete SPECIALIST_SCHEMA object."""
    base: dict[str, Any] = {"ranking": [], "narrative": "", "evidence_refs": [], "agreement": "",
                            "disagreements": [], "confidence": 0.6, "assumptions": [], "caveats": [],
                            "lens": ""}
    base.update(over)
    return base


def synthesis(**over: Any) -> dict[str, Any]:
    """A complete SYNTHESIS_SCHEMA object."""
    base: dict[str, Any] = {"headline": "Here is what the evidence shows.", "show_metrics": ["load_factor"],
                            "hidden_reason": "collapsed to keep the table readable", "analyst_summary": "",
                            "follow_ups": ["Try another horizon?", "Try another preset?", "Add an airport?"]}
    base.update(over)
    return base


def _thinking(text: str = "I have what I need.") -> LLMResult:
    """A specialist loop turn that asks for no tools, so the loop ends and the final report is requested."""
    return LLMResult(text=text, provider="fake", model="scripted")


def _profile_call(iata: str, horizon: str = "12m") -> LLMResult:
    return LLMResult(text="", provider="fake", model="scripted",
                     tool_calls=[ToolCall(id="c1", name="get_profile",
                                          arguments={"iata": iata, "horizons": [horizon]})])


ANC_ROUTES = '{"iata": "ANC"}'
ANC_ROUTES_LONGHAUL = '{"iata": "ANC", "threshold_mi": 1500}'
NO_ARGS = "{}"

# --------------------------------------------------------------------------------------------------
# Q1 - "Which airports in New England are strong candidates for terminal expansion?"
# --------------------------------------------------------------------------------------------------
Q1_PLAN = plan(intent="analytical", engines=["deterministic", "specialist:expansion_analyst"],
               question_type="rank", faa_regions=["ANE"], horizons=["5y"],
               scoring_preset="terminal_expansion", hint="terminal and gate constraints first",
               presentation_notes="Rank table first, then the two strongest candidates.")
Q1_SPECIALIST = specialist(
    ranking=[{"iata": "BOS", "rank": 1, "rationale": "largest constrained demand base", "confidence": 0.7},
             {"iata": "BDL", "rank": 2, "rationale": "growth with terminal headroom", "confidence": 0.6}],
    narrative="BOS carries the most absorbed demand; BDL is the cheaper terminal play.",
    evidence_refs=[{"iata": "BOS", "metric_id": "load_factor"}],
    agreement="agrees with the formula on the top two",
    disagreements=["the formula underweights gate scarcity"],
    confidence=0.65, assumptions=["5y horizon"], caveats=["tier-B gate data missing outside BOS"],
    lens="expansion")
Q1_SYNTHESIS = synthesis(headline="BOS leads the New England terminal-expansion shortlist, with BDL second.",
                         show_metrics=["load_factor", "avg_dep_delay_min"],
                         hidden_reason="capacity-label rows collapsed",
                         follow_ups=["Switch to congestion_relief?", "Why is BOS first?", "Add PWM detail?"])

# --------------------------------------------------------------------------------------------------
# Q2 - "Compare LA and Santa Ana airport congestion levels."
# --------------------------------------------------------------------------------------------------
Q2_PLAN = plan(intent="analytical", engines=["deterministic", "specialist:capacity_analyst"],
               question_type="compare", airports=["LAX", "SNA"], horizons=["12m"],
               scoring_preset="congestion_relief", focus_metrics=P2_FOCUS,
               hint="delay and capacity constraint, not scale",
               presentation_notes="Side-by-side first; name the legal cap at SNA.")
Q2_SPECIALIST = specialist(
    ranking=[{"iata": "LAX", "rank": 1, "rationale": "higher absolute congestion", "confidence": 0.7},
             {"iata": "SNA", "rank": 2, "rationale": "legally capped, not physically full", "confidence": 0.6}],
    narrative="LAX is congested on throughput; the SNA constraint is a court-ordered cap.",
    evidence_refs=[{"iata": "LAX", "metric_id": "avg_dep_delay_min"}],
    agreement="agrees that LAX is the more congested field",
    disagreements=["the formula cannot see the legal cap at SNA"], confidence=0.6,
    assumptions=["12m horizon"], caveats=["the SNA cap is legal, not physical"], lens="capacity")
Q2_SYNTHESIS = synthesis(headline="LAX is the more congested field; SNA is constrained by its legal cap.",
                         show_metrics=["avg_dep_delay_min", "taxi_out_p80_min"],
                         hidden_reason="scale metrics collapsed",
                         follow_ups=["Add BUR?", "Show the taxi-out trend?", "Switch horizon to 3y?"])

# --------------------------------------------------------------------------------------------------
# Q3 - "What is the percentage of long haul flights out of Anchorage airport?" (informational)
# --------------------------------------------------------------------------------------------------
Q3_PLAN = plan(intent="informational", engines=["tools"],
               tool_calls=[{"tool": "get_route_stats", "args_json": ANC_ROUTES}],
               presentation_notes="State the long-haul convention and separate passenger from freight.")
Q3_SYNTHESIS = synthesis(headline="15.4% of ANC passenger departures are long haul; freight is far higher.",
                         show_metrics=[], hidden_reason="",
                         follow_ups=["And for freight only?", "Which sources did you use?", "Compare to SEA?"])

# --------------------------------------------------------------------------------------------------
# Q4 - "What is the unmet flight demand in SFO airport and why?"
# --------------------------------------------------------------------------------------------------
Q4_PLAN = plan(intent="analytical", engines=["deterministic", "specialist:capacity_analyst"],
               question_type="diagnose", airports=["SFO"], horizons=["12m"],
               hint="spill model, not a load-factor cutoff",
               presentation_notes="Lead with the signal count, then the mechanism.")
Q4_SPECIALIST = specialist(
    narrative="SFO shows absorbed peak demand with weather-driven capacity loss.",
    evidence_refs=[{"iata": "SFO", "metric_id": "load_factor"},
                   {"iata": "SFO", "metric_id": "taxi_out_p80_min"}],
    agreement="agrees with the deterministic signal count",
    disagreements=["the formula cannot separate weather from demand"], confidence=0.55,
    assumptions=["12m horizon", "spill model"], caveats=["the IMC/VMC ratio is curated, majors only"],
    lens="capacity")
Q4_SYNTHESIS = synthesis(headline="SFO shows two of three unmet-demand signals, driven by peak spill.",
                         show_metrics=["load_factor", "spill_proxy"],
                         hidden_reason="capacity-label rows collapsed",
                         follow_ups=["Which signal is strongest?", "Compare with OAK?", "Show the routes?"])

# --------------------------------------------------------------------------------------------------
# Follow-ups: (message, script chunk, expected extra LLM calls, answered from session memory)
# --------------------------------------------------------------------------------------------------
FU_Q1_PRESET = ("and with congestion_relief?",
                [plan(intent="analytical", engines=["deterministic", "specialist:expansion_analyst"],
                      question_type="rank", faa_regions=["ANE"], horizons=["5y"],
                      scoring_preset="congestion_relief", presentation_notes="Same region, new preset."),
                 _thinking(), Q1_SPECIALIST,
                 synthesis(headline="Under congestion_relief the New England order changes.",
                           show_metrics=["load_factor"])], 4, False)
FU_Q1_WHY = ("why is BOS first?",
             [plan(intent="followup", engines=[], presentation_notes="Answer from the last reports."),
              synthesis(headline="BOS is first on absorbed demand, not on growth.", show_metrics=[])], 2, True)
FU_Q2_ADD = ("add BUR to the comparison",
             [plan(intent="analytical", engines=["deterministic", "specialist:capacity_analyst"],
                   question_type="compare", airports=["LAX", "SNA", "BUR"], horizons=["12m"],
                   scoring_preset="congestion_relief", presentation_notes="Three-way comparison."),
              _thinking(), Q2_SPECIALIST,
              synthesis(headline="BUR is the least congested of the three.",
                        show_metrics=["avg_dep_delay_min"])], 4, False)
FU_Q3_FREIGHT = ("and for freight only?",
                 [plan(intent="informational", engines=["tools"],
                       tool_calls=[{"tool": "get_route_stats", "args_json": ANC_ROUTES_LONGHAUL}],
                       presentation_notes="Freight row only; restate the convention."),
                  synthesis(headline="The ANC freight long-haul share is far above the passenger share.",
                            show_metrics=[])], 2, False)
FU_SOURCES = ("which sources did you use?",
              [plan(intent="informational", engines=["tools"],
                    tool_calls=[{"tool": "list_sources", "args_json": NO_ARGS}],
                    presentation_notes="List the sources with their vintages."),
               synthesis(headline="These are the datasets behind the numbers.", show_metrics=[])], 2, False)
FU_Q4_SIGNAL = ("which of those signals is strongest?",
                [plan(intent="followup", engines=[], presentation_notes="Answer from the last reports."),
                 synthesis(headline="Taxi-out is the strongest of the three signals.", show_metrics=[])],
                2, True)

MAIN: list[list[Any]] = [
    [Q1_PLAN, _thinking(), Q1_SPECIALIST, Q1_SYNTHESIS],
    [Q2_PLAN, _thinking(), Q2_SPECIALIST, Q2_SYNTHESIS],
    [Q3_PLAN, Q3_SYNTHESIS],
    [Q4_PLAN, _profile_call("SFO"), _thinking(), Q4_SPECIALIST, Q4_SYNTHESIS],
]
FOLLOW_UPS: list[list[tuple[str, list[Any], int, bool]]] = [
    [FU_Q1_PRESET, FU_Q1_WHY],
    [FU_Q2_ADD],
    [FU_Q3_FREIGHT, FU_SOURCES],
    [FU_Q4_SIGNAL],
]


def main_script(index: int) -> list[Any]:
    return list(MAIN[index])


def follow_ups(index: int) -> list[tuple[str, list[Any], int, bool]]:
    return list(FOLLOW_UPS[index])


def for_question(index: int) -> list[Any]:
    """The whole session: the question itself and then every follow-up, in order."""
    script = main_script(index)
    for _message, chunk, _calls, _memory in follow_ups(index):
        script.extend(chunk)
    return script
