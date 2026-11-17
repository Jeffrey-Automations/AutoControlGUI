"""MCP automation adapters delegating lazily to executor commands.

Annotations mirror the executor JSON boundary, including heterogeneous payloads.
"""

from typing import Any, Callable, Dict, List, Optional


def _observe_handler(actions: List[Any]) -> Callable[[str, Any], None]:
    # The executor's own builder: each firing runs in a fresh variable scope
    # seeded with what the registering tool call could see (normally nothing).
    from je_auto_control.utils.executor.action_executor import (
        _observe_handler as build_handler,
    )

    return build_handler(actions)


def circuit_call(name: str, actions: List[Any], threshold: int = 5, reset_s: float = 30.0) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _circuit_call

    return _circuit_call(name, actions, threshold=int(threshold), reset_s=float(reset_s))


def run_chaos(spec: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _run_chaos

    return _run_chaos(spec)


def bulkhead_run(name: str, max_concurrent: int, actions: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _bulkhead_run

    return _bulkhead_run(name, max_concurrent, actions)


def expect_poll(
    action: Any, key: Any = None, op: str = "truthy", expected: Any = None, timeout_s: Any = 5.0, interval_s: Any = 0.25
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _expect_poll

    return _expect_poll(action, key, op, expected, timeout_s, interval_s)


def failure_signature(error: str, length: Any = 12) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _failure_signature

    return _failure_signature(error, length)


def group_failures(errors: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _group_failures

    return _group_failures(errors)


def diff_runs(before: Any, after: Any, key: str = "name", regress_factor: Any = 1.5) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _diff_runs

    return _diff_runs(before, after, key, regress_factor)


def failure_clusters(runs: Any, threshold: Any = 0.5, min_size: Any = 2) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _failure_clusters

    return _failure_clusters(runs, threshold, min_size)


def cofailure_pairs(runs: Any, threshold: Any = 0.5) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cofailure_pairs

    return _cofailure_pairs(runs, threshold)


def build_timeline(steps: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _build_timeline

    return _build_timeline(steps)


def critical_steps(steps: Any, top: Any = 3) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _critical_steps

    return _critical_steps(steps, top)


def soft_assert(checks: Any, raise_on_fail: Any = False) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _soft_assert

    return _soft_assert(checks, raise_on_fail)


def cua_command(payload: Any, source: str = "canonical") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cua_command

    return _cua_command(payload, source)


def serialize_observation(elements: Any, viewport: Any = None, max_elements: Any = 80) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _serialize_observation

    return _serialize_observation(elements, viewport, max_elements)


def observation_index(elements: Any, viewport: Any = None, max_elements: Any = 80) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _observation_index

    return _observation_index(elements, viewport, max_elements)


def delta_observation(
    prev: Any,
    curr: Any,
    viewport: Any = None,
    max_elements: Any = 80,
    max_lines: Any = 40,
    interactive_only: Any = True,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _delta_observation

    return _delta_observation(prev, curr, viewport, max_elements, max_lines, interactive_only)


def classify_effect(before: Any, after: Any, action: Any, radius: Any = 64) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _classify_effect

    return _classify_effect(before, after, action, radius)


def effect_near_point(before: Any, after: Any, point: Any, radius: Any = 64) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _effect_near_point

    return _effect_near_point(before, after, point, radius)


def check_postcondition(after: Any, spec: Any, before: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _check_postcondition

    return _check_postcondition(after, spec, before)


def plan_repair(verdict: Any, max_attempts: Any = 3) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _plan_repair

    return _plan_repair(verdict, max_attempts)


def consensus_point(candidates: Any, cluster_radius: Any = 24) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _consensus_point

    return _consensus_point(candidates, cluster_radius)


def consensus_element(candidates: Any, elements: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _consensus_element

    return _consensus_element(candidates, elements)


def settle_point(churns: Any, quiet_samples: Any = 3, max_churn: Any = 1.0) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _settle_point

    return _settle_point(churns, quiet_samples, max_churn)


def build_critic_record(
    action: Any, before: Any, after: Any, postcondition: Any = None, radius: Any = 64
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _build_critic_record

    return _build_critic_record(action, before, after, postcondition, radius)


def score_step(record: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _score_step

    return _score_step(record)


def validate_action(action: Any, screen: Any = None, targets: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _validate_action

    return _validate_action(action, screen, targets)


def replay_trace(trace: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _replay_trace

    return _replay_trace(trace)


def match_elements(before: Any, after: Any, iou_threshold: Any = 0.5) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_elements

    return _match_elements(before, after, iou_threshold)


def assign_stable_ids(elements: Any, prior: Any = None, iou_threshold: Any = 0.5) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _assign_stable_ids

    return _assign_stable_ids(elements, prior, iou_threshold)


def score_candidates(
    candidates: Any, want_role: Any = None, want_name: Any = None, anchor: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _score_candidates

    return _score_candidates(candidates, want_role, want_name, anchor)


def best_candidate(candidates: Any, want_role: Any = None, want_name: Any = None, anchor: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _best_candidate

    return _best_candidate(candidates, want_role, want_name, anchor)


def run_agent(
    goal: str,
    backend: str = "anthropic",
    max_steps: int = 25,
    wall_seconds: float = 300.0,
    model: Optional[str] = None,
    max_tokens: int = 1024,
) -> Dict[str, Any]:
    """Drive the generic plan→act→verify→retry AgentLoop against ``goal``."""
    from je_auto_control.utils.executor.action_executor import _run_agent

    return _run_agent(
        goal=goal,
        backend=backend,
        max_steps=int(max_steps),
        wall_seconds=float(wall_seconds),
        model=model,
        max_tokens=int(max_tokens),
    )
