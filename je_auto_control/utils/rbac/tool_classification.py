"""Reviewed MCP screen capabilities and canonical tool aliases.

Read-only hints describe effects, not permission to read host data. Only
reviewed screen and caller-data operations belong here. Unknown tools require
READ_DATA; trusted host registration can still replace a named handler.
"""
from collections.abc import Callable, Mapping
import json

TOOL_ALIASES: dict[str, str] = {
    "click": "ac_click_mouse",
    "move_mouse": "ac_set_mouse_position",
    "mouse_pos": "ac_get_mouse_position",
    "scroll": "ac_mouse_scroll",
    "type": "ac_type_text",
    "press": "ac_press_key",
    "hotkey": "ac_hotkey",
    "screenshot": "ac_screenshot",
    "screen_size": "ac_screen_size",
    "find_image": "ac_locate_image_center",
    "find_text": "ac_locate_text",
    "click_text": "ac_click_text",
    "drag": "ac_drag",
    "list_windows": "ac_list_windows",
    "focus_window": "ac_focus_window",
    "wait_image": "ac_wait_for_image",
    "wait_pixel": "ac_wait_for_pixel",
    "diff_screens": "ac_diff_screenshots",
    "shell": "ac_shell",
}

# Reviewed adapters observe the live desktop or compute only from caller data.
SCREEN_TOOLS = frozenset({
    "ac_a11y_dump",
    "ac_a11y_find",
    "ac_a11y_find_all",
    "ac_a11y_focused",
    "ac_a11y_list",
    "ac_ab_significance",
    "ac_adaptive_timeout",
    "ac_adjust_delays",
    "ac_apply_json_patch",
    "ac_apply_unified",
    "ac_apply_vex",
    "ac_assert_pixel",
    "ac_assert_session_active",
    "ac_assert_text",
    "ac_assert_window",
    "ac_assign_stable_ids",
    "ac_associate_fields",
    "ac_audit_accessibility",
    "ac_audit_contrast",
    "ac_audit_focus_order",
    "ac_baggage_format",
    "ac_baggage_parse",
    "ac_best_candidate",
    "ac_bidi_check",
    "ac_build_critic_record",
    "ac_build_multipart",
    "ac_build_timeline",
    "ac_burn_alerts",
    "ac_canonical_log",
    "ac_canonicalize_url",
    "ac_cascade_rects",
    "ac_categorical_drift",
    "ac_cell_by_header",
    "ac_cell_changes",
    "ac_cell_for_point",
    "ac_check_accepted_values",
    "ac_check_catalog",
    "ac_check_compatibility",
    "ac_check_foreign_key",
    "ac_check_licenses",
    "ac_check_overflow",
    "ac_check_postcondition",
    "ac_check_row_count",
    "ac_check_unique_key",
    "ac_checksum_digit",
    "ac_checksum_validate",
    "ac_ci_annotations",
    "ac_classify_effect",
    "ac_classify_formats",
    "ac_classify_lines",
    "ac_classify_lock_transitions",
    "ac_classify_widget",
    "ac_client_point",
    "ac_cofailure_pairs",
    "ac_collation_compare",
    "ac_collation_sort",
    "ac_colors_collide",
    "ac_column_gutters",
    "ac_compare_field_value",
    "ac_confusable_compare",
    "ac_confusable_scan",
    "ac_consensus_element",
    "ac_consensus_point",
    "ac_control_expand_state",
    "ac_control_get_state",
    "ac_control_get_value",
    "ac_control_range",
    "ac_control_text_attributes",
    "ac_cookie_header",
    "ac_critical_steps",
    "ac_cua_command",
    "ac_decision_table",
    "ac_decode_body",
    "ac_decode_conversion_mode",
    "ac_dedupe_moves",
    "ac_delta_observation",
    "ac_describe_stats",
    "ac_detect_anomalies",
    "ac_detect_borderless_table",
    "ac_detect_drift",
    "ac_detect_lists",
    "ac_detect_pii",
    "ac_diff_formats",
    "ac_diff_json",
    "ac_diff_rows",
    "ac_diff_runs",
    "ac_dominant_hue_regions",
    "ac_dominant_pair",
    "ac_effect_near_point",
    "ac_enumerate_monitors",
    "ac_evaluate_flag",
    "ac_evaluate_slo",
    "ac_evaluate_trajectory",
    "ac_ewma",
    "ac_explain_config",
    "ac_extract_fields",
    "ac_failure_clusters",
    "ac_failure_signature",
    "ac_find_color_region",
    "ac_find_control_text",
    "ac_find_grid",
    "ac_find_lines",
    "ac_find_rectangles",
    "ac_find_separators",
    "ac_find_shapes",
    "ac_find_text_lines",
    "ac_find_text_regions",
    "ac_flag_enabled",
    "ac_flow_order",
    "ac_foreground_window",
    "ac_foreground_window_pid",
    "ac_format_currency",
    "ac_format_date",
    "ac_format_decimal",
    "ac_format_list",
    "ac_format_message",
    "ac_fuse_elements",
    "ac_fuzzy_best_match",
    "ac_fuzzy_dedupe",
    "ac_fuzzy_ratio",
    "ac_get_client_rect",
    "ac_get_control_text",
    "ac_get_element_properties",
    "ac_get_mouse_position",
    "ac_get_pixel",
    "ac_get_selected_text",
    "ac_get_selection",
    "ac_get_visible_text",
    "ac_gettext_ngettext",
    "ac_gettext_translate",
    "ac_grade_contrast",
    "ac_grid_cell",
    "ac_grid_cells",
    "ac_grid_rects",
    "ac_group_failures",
    "ac_group_paragraphs",
    "ac_guard_text",
    "ac_http_replay",
    "ac_humanize_role",
    "ac_idle_point",
    "ac_idle_seconds",
    "ac_ime_state",
    "ac_infer_schema",
    "ac_is_composing",
    "ac_json_extract",
    "ac_json_query",
    "ac_jwt_decode",
    "ac_label_color",
    "ac_legacy_info",
    "ac_list_action_commands",
    "ac_list_monitors",
    "ac_list_views",
    "ac_list_windows",
    "ac_locate_chain",
    "ac_locate_text",
    "ac_make_json_patch",
    "ac_mask_rows",
    "ac_match_elements",
    "ac_match_json",
    "ac_match_labels_to_widgets",
    "ac_mcp_tool_schema",
    "ac_mcp_tool_search",
    "ac_mcp_tools_disable",
    "ac_mcp_tools_enable",
    "ac_mcp_tools_state",
    "ac_merge_patch",
    "ac_merge_results",
    "ac_merge_sleeps",
    "ac_mine_actions",
    "ac_monitor_at_point",
    "ac_near_duplicates",
    "ac_next_url",
    "ac_normalize_ext",
    "ac_normalize_text",
    "ac_normalize_url",
    "ac_observation_index",
    "ac_ocr_read_structure",
    "ac_outline",
    "ac_parse_cache_control",
    "ac_parse_decimal",
    "ac_parse_dotenv",
    "ac_parse_link_header",
    "ac_parse_multipart",
    "ac_parse_number",
    "ac_parse_problem",
    "ac_parse_quality_values",
    "ac_parse_set_cookie",
    "ac_parse_sse",
    "ac_percentiles",
    "ac_place_labels",
    "ac_plan_file_drop",
    "ac_plan_keep_awake",
    "ac_plan_lock_session",
    "ac_plan_repair",
    "ac_plan_retry_delays",
    "ac_point_for_cell",
    "ac_populate_table",
    "ac_profile_rows",
    "ac_propose_elements",
    "ac_pseudo_localize",
    "ac_rank_changes",
    "ac_read_table",
    "ac_readability_report",
    "ac_reading_order",
    "ac_redact_config",
    "ac_redact_pii",
    "ac_redact_secret_text",
    "ac_region_contrast",
    "ac_resolve_config",
    "ac_resolve_pointer",
    "ac_retry_after",
    "ac_retry_delay",
    "ac_rrule_next",
    "ac_rrule_occurrences",
    "ac_scale_coordinates",
    "ac_scan_secrets",
    "ac_scan_vulns",
    "ac_score_candidates",
    "ac_score_step",
    "ac_screen_diff",
    "ac_screen_size",
    "ac_search_documents",
    "ac_segment_hsv",
    "ac_serialize_observation",
    "ac_settle_point",
    "ac_simhash",
    "ac_simulate_cvd",
    "ac_slugify",
    "ac_sma",
    "ac_soft_assert",
    "ac_spans_to_otlp",
    "ac_store_validators",
    "ac_sync_entry_merge",
    "ac_sync_peer_state",
    "ac_tab_order",
    "ac_table_cell",
    "ac_table_headers",
    "ac_tag_kinds",
    "ac_text_similarity",
    "ac_three_way_merge",
    "ac_tile_rect",
    "ac_timeout_stats",
    "ac_to_model",
    "ac_to_physical",
    "ac_trace_extract",
    "ac_trace_inject",
    "ac_trim_actions",
    "ac_ts_downsample",
    "ac_ts_rate",
    "ac_unified_diff",
    "ac_urls_equal",
    "ac_validate_action",
    "ac_validate_json",
    "ac_validate_rows",
    "ac_verify_field_value",
    "ac_vote_centers",
    "ac_wait_color",
    "ac_wait_for_composition_commit",
    "ac_wait_for_focus_change",
    "ac_wait_for_pixel",
    "ac_wait_for_window",
    "ac_wait_pixel_changes",
    "ac_wait_region_idle",
    "ac_wait_screen_stable",
    "ac_wait_text_gone",
    "ac_wait_until_app_idle",
    "ac_wait_window_title",
    "ac_walk_tree",
    "ac_wcag_audit",
    "ac_window_interaction_state",
    "ac_window_pid",
    "ac_window_rect",
    "ac_windows_for_pid",
    "ac_xy_cut",
})

# Each of these exact adapters captures the screen when source is None and
# passes a supplied source to an image loader otherwise.
SCREEN_SOURCE_TOOLS = frozenset({
    "ac_image_histogram", "ac_image_quality", "ac_quality_gate",
    "ac_salient_regions", "ac_most_salient", "ac_read_barcodes",
})

CAPTURE_ASSERTIONS = frozenset({
    "ac_assert_text", "ac_assert_image", "ac_assert_pixel", "ac_assert_window",
    "ac_assert_clipboard", "ac_assert_process",
})


def canonical_tool_name(name: str) -> str:
    """Resolve only the aliases declared by the trusted built-in registry."""
    return TOOL_ALIASES.get(name, name)


UNREVIEWED_EXTERNAL_TOOLS = frozenset({"ac_list_plugins", "ac_web_list_commands", "ac_web_current_url"})

ANCHOR_TOOLS = frozenset({"ac_anchor_locate", "ac_anchor_locate_all"})
ANDROID_READ_TOOLS = frozenset({
    "ac_android_list_devices", "ac_android_device_info", "ac_android_screen_info",
    "ac_android_app_state", "ac_android_wait_for_app",
})


def _anchor_capability(arguments: Mapping[str, object]) -> str | None:
    from je_auto_control.utils.rbac.users import Capability
    locators = [arguments.get(key) for key in ("anchor", "target")]
    kinds = [value.get("kind") if isinstance(value, dict) else None for value in locators]
    if "vlm" in kinds:
        return Capability.DRIVE_INPUT
    if any(kind not in ("ocr", "a11y") for kind in kinds):
        return Capability.READ_DATA
    return None


def _config_capability(arguments: Mapping[str, object]) -> str | None:
    from je_auto_control.utils.rbac.users import Capability
    spec, config = arguments.get("schema"), arguments.get("config")
    try:
        spec = json.loads(spec) if isinstance(spec, str) else spec
        config = json.loads(config) if isinstance(config, str) else config
    except (ValueError, TypeError):
        return Capability.READ_DATA
    if not isinstance(spec, dict) or not isinstance(config, dict):
        return Capability.READ_DATA
    for name, field in spec.items():
        if not isinstance(field, dict) or (field.get("env") and name not in config):
            return Capability.READ_DATA
    return None


def _open_capability(arguments: Mapping[str, object]) -> str | None:
    from je_auto_control.utils.rbac.users import Capability
    from je_auto_control.utils.shell_open.shell_open import _scheme
    target = arguments.get("target")
    if isinstance(target, str) and _scheme(target.strip()) is not None:
        return None
    return Capability.READ_DATA


MIXED_ARGUMENT_TOOLS: dict[str, Callable[[Mapping[str, object]], str | None]] = {
    **dict.fromkeys(ANCHOR_TOOLS, _anchor_capability),
    "ac_validate_config": _config_capability,
    "ac_plan_open": _open_capability,
}


def argument_capability(name: str, arguments: Mapping[str, object]) -> str | None:
    """Additional authority needed by known mixed-effect tool arguments."""
    from je_auto_control.utils.rbac.users import Capability
    name = canonical_tool_name(name)
    if name in CAPTURE_ASSERTIONS and arguments.get("capture_on_fail", False):
        return Capability.DRIVE_INPUT
    if name in ANDROID_READ_TOOLS and arguments.get("adb_path"):
        return Capability.DRIVE_INPUT
    if name in SCREEN_SOURCE_TOOLS and arguments.get("source") is not None:
        return Capability.READ_DATA
    check = MIXED_ARGUMENT_TOOLS.get(name)
    return check(arguments) if check is not None else None
