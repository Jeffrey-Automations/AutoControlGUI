"""The ``AC_*`` commands reviewed as needing only what the submitting surface checks.

Submitting an action list already needs ``drive_input`` (``POST /execute``,
``ac_execute_actions``, an action file run by a caller holding it), and the
executor checks :data:`~je_auto_control.utils.rbac.policy.COMMAND_CAPABILITIES`
on every action it runs, nested blocks and parallel branches included. Every
other command is listed here, reviewed against the one boundary that matters to
an action list: the operator role holds ``read_screen``, ``read_data`` and
``drive_input``, so a command belongs in the policy table only when it reaches
what only an admin may touch -- the signing key, users, host administration,
the servers the host runs, its USB and egress policy, the secrets vault's
administration, the audit log, or plug-in loading.

The review (U-20261115-03) screened every name, and every adapter's source for
the modules that hold that state, and read each candidate:
:data:`OPERATOR_NOTES` records why each one stays at operator. Membership
changes nothing at run time -- an unlisted command was already allowed -- but
``test_rbac_command_review.py`` fails on a command in neither table, so a new
command gets the same decision instead of inheriting the default unseen.
"""
from typing import Dict, FrozenSet

#: Reviewed candidates that stay at operator, with the reason.
OPERATOR_NOTES: Dict[str, str] = {
    "AC_approval_approve": (
        "maker-checker for scripts: nothing on the host consults the gate, and under RBAC the approver is the "
        "authenticated user (ApprovalGate refuses another name)"
    ),
    "AC_approval_reject": "as AC_approval_approve",
    "AC_approval_request": "maker-checker for scripts; under RBAC the requester is the authenticated user",
    "AC_approval_status": "reads a request's state",
    "AC_approve_artifact": "promotes a test baseline: workflow data, not host policy",
    "AC_chatops_dispatch": (
        "/run executes the script in the caller's thread, so the executor's own check refuses a privileged "
        "command inside it"
    ),
    "AC_create_signing_keypair": (
        "writes a new pair only: it refuses an existing file and a verify-only endpoint, and signing with the "
        "pair needs sign_actions"
    ),
    "AC_decrypt_action_file": (
        "reveals a file's content, which read_data covers and an operator holds; an operator can already run the "
        "file it protects"
    ),
    "AC_egress_check": "reads the egress policy; setting or resetting it needs manage_hosts",
    "AC_encrypt_action_file": (
        "Fernet with a caller passphrase or the per-user key; the content is the caller's own file"
    ),
    "AC_lease_active": "lists leases without values",
    "AC_lease_secret": (  # nosec B105  # reason: an AC_* command name, not a credential
        "a lease token carries no value; redeeming one is Python-only"
    ),
    "AC_lease_valid": "as AC_lease_secret",
    "AC_list_plugins": "lists entry points; loading them needs manage_hosts",
    "AC_parallel": (
        "branches keep the caller's authorization: the executor refuses a privileged command inside a branch"
    ),
    "AC_presence_clear": "as AC_presence_register",
    "AC_presence_register": (
        "advisory: no host consults PresenceRegistry.can_control(); raise the presence commands to manage_hosts "
        "if one starts gating input on it"
    ),
    "AC_presence_set_role": "as AC_presence_register",
    "AC_presence_unregister": "as AC_presence_register",
    "AC_repair_approve": "accepts a locator-repair suggestion: workflow data, not host policy",
    "AC_revoke_lease": "as AC_lease_secret",
    "AC_secret_list": (  # nosec B105  # reason: an AC_* command name, not a credential
        "names only; vault administration (init, set, remove, lock, unlock) needs manage_hosts"
    ),
    "AC_secret_status": (  # nosec B105  # reason: an AC_* command name, not a credential
        "path and lock state only, as AC_secret_list"
    ),
    "AC_usb_acl_list": "the stored ACL, read_data as ac_usb_acl_list and GET /usb/acl",
    "AC_usb_loopback_open": (
        "matches POST /usb/loopback/open (drive_input); the ACL and the passthrough switch need manage_hosts"
    ),
    "AC_usb_remote_open": "matches POST /usb/remote/open, as AC_usb_loopback_open",
    "AC_verify_action_file": "checks a signature against a public key; it grants nothing",
    "AC_webhook_list": "rows carry has_token, never the token; add, remove, start and stop need manage_hosts",
    "AC_webhook_status": "running state and bound address only, as AC_webhook_list",
    "AC_webrtc_accept_answer": "as AC_webrtc_create_offer",
    "AC_webrtc_create_offer": (
        "signals a host that AC_start_webrtc_host (manage_hosts) started; the viewer still authenticates with "
        "that host's token"
    ),
    "AC_webrtc_host_status": "running, authenticated and connection state only",
    "AC_ws_host_status": "state and owner only, no token (AC_remote_host_status's reply)",
}

#: Every other command: it drives input, observes the screen, or reads or
#: writes what the operator's own capabilities already reach.
OPERATOR_COMMANDS: FrozenSet[str] = frozenset({
    "AC_a11y_click", "AC_a11y_dump", "AC_a11y_find", "AC_a11y_find_all", "AC_a11y_focused", "AC_a11y_list",
    "AC_a11y_record_events", "AC_a11y_record_start", "AC_a11y_record_stop", "AC_ab_best_strategy", "AC_ab_clear",
    "AC_ab_locate", "AC_ab_report", "AC_ab_significance", "AC_act_in_view", "AC_act_with_mode",
    "AC_adaptive_timeout", "AC_agent_card", "AC_agent_dag", "AC_agent_dag_inspect", "AC_agent_runtime_readiness",
    "AC_agent_runtime_status", "AC_agent_skill", "AC_agent_skill_list", "AC_agent_target_list",
    "AC_agent_task_act", "AC_agent_task_cancel", "AC_agent_task_draft", "AC_agent_task_finish",
    "AC_agent_task_get", "AC_agent_task_list", "AC_agent_task_lookup", "AC_agent_task_observe",
    "AC_agent_task_pause", "AC_agent_task_prune", "AC_agent_task_receipts", "AC_agent_task_reconcile",
    "AC_agent_task_recovery", "AC_agent_task_resume", "AC_agent_task_stop_all", "AC_agent_task_submit",
    "AC_agent_transfer", "AC_agent_trigger", "AC_agent_trigger_list", "AC_allow_sleep", "AC_anchor_click",
    "AC_anchor_locate", "AC_anchor_locate_all", "AC_android_alert_accept", "AC_android_alert_dismiss",
    "AC_android_app_state", "AC_android_click_element", "AC_android_device_info", "AC_android_drag",
    "AC_android_dump_hierarchy", "AC_android_find_by_description", "AC_android_find_element",
    "AC_android_find_image", "AC_android_find_text", "AC_android_get_clipboard", "AC_android_install_app",
    "AC_android_key", "AC_android_launch_app", "AC_android_list_devices", "AC_android_long_press",
    "AC_android_pinch", "AC_android_pull_file", "AC_android_push_file", "AC_android_screen_info",
    "AC_android_screenshot", "AC_android_self_heal", "AC_android_set_clipboard", "AC_android_shell",
    "AC_android_start_recording", "AC_android_stop_app", "AC_android_stop_recording", "AC_android_swipe",
    "AC_android_tap", "AC_android_text", "AC_android_type_text", "AC_android_wait_for_app",
    "AC_annotate_screenshot", "AC_apply_json_patch", "AC_apply_unified", "AC_apply_vex", "AC_arrange_cascade",
    "AC_arrange_grid", "AC_assert_all", "AC_assert_any", "AC_assert_audio", "AC_assert_clipboard", "AC_assert_db",
    "AC_assert_duration", "AC_assert_eventually", "AC_assert_file", "AC_assert_http", "AC_assert_image",
    "AC_assert_pdf_text", "AC_assert_pixel", "AC_assert_process", "AC_assert_session_active", "AC_assert_text",
    "AC_assert_var", "AC_assert_video_changes", "AC_assert_visual", "AC_assert_vlm", "AC_assert_window",
    "AC_assign_stable_ids", "AC_associate_fields", "AC_audit_accessibility", "AC_audit_contrast",
    "AC_audit_focus_order", "AC_auto_threshold", "AC_baggage_format", "AC_baggage_parse", "AC_best_candidate",
    "AC_bidi_check", "AC_bidi_strip", "AC_break", "AC_bring_to_front", "AC_browser_check", "AC_browser_click",
    "AC_browser_download", "AC_browser_fill", "AC_browser_link", "AC_browser_navigate", "AC_browser_read",
    "AC_browser_select", "AC_browser_upload", "AC_browser_wait", "AC_build_critic_record", "AC_build_multipart",
    "AC_build_provenance", "AC_build_timeline", "AC_bulkhead_run", "AC_burn_alerts", "AC_call_macro",
    "AC_canonical_log", "AC_canonicalize_url", "AC_capture_window", "AC_cas_get", "AC_cas_put", "AC_cascade_rects",
    "AC_categorical_drift", "AC_cell_by_header", "AC_cell_changes", "AC_cell_for_point", "AC_change_volume",
    "AC_changed_regions", "AC_check_accepted_values", "AC_check_catalog", "AC_check_compatibility",
    "AC_check_foreign_key", "AC_check_key_is_press", "AC_check_licenses", "AC_check_overflow",
    "AC_check_postcondition", "AC_check_row_count", "AC_check_unique_key", "AC_checkpoint_clear",
    "AC_checkpoint_status", "AC_checksum_digit", "AC_checksum_validate", "AC_ci_annotations", "AC_circuit_call",
    "AC_classify_effect", "AC_classify_formats", "AC_classify_icon", "AC_classify_lines",
    "AC_classify_lock_transitions", "AC_classify_widget", "AC_click_mouse", "AC_click_text", "AC_client_point",
    "AC_clip_history_capture", "AC_clip_history_list", "AC_clip_history_search", "AC_clip_history_start",
    "AC_clip_history_stop", "AC_clipboard_formats", "AC_clipboard_get", "AC_clipboard_get_image",
    "AC_clipboard_set", "AC_clipboard_set_image", "AC_close_window", "AC_cofailure_pairs", "AC_collapse_control",
    "AC_collation_compare", "AC_collation_sort", "AC_colors_collide", "AC_column_gutters",
    "AC_compare_field_value", "AC_compliance_report", "AC_computer_use", "AC_confusable_compare",
    "AC_confusable_scan", "AC_consensus_element", "AC_consensus_point", "AC_continue", "AC_control_expand_state",
    "AC_control_get_state", "AC_control_get_value", "AC_control_invoke", "AC_control_range",
    "AC_control_set_value", "AC_control_text_attributes", "AC_control_toggle", "AC_cookie_header",
    "AC_costs_clear", "AC_costs_list", "AC_costs_record", "AC_costs_summary", "AC_create_project",
    "AC_critical_steps", "AC_cua_command", "AC_debug_trace", "AC_decision_table", "AC_decode_body",
    "AC_decode_conversion_mode", "AC_dedup_check", "AC_dedupe_images", "AC_define_macro", "AC_delta_observation",
    "AC_describe_screen", "AC_describe_stats", "AC_detect_anomalies", "AC_detect_borderless_table",
    "AC_detect_drift", "AC_detect_lists", "AC_detect_pii", "AC_detect_scale", "AC_diff_formats", "AC_diff_json",
    "AC_diff_rows", "AC_diff_runs", "AC_dominant_hue_regions", "AC_dominant_pair", "AC_drag_path", "AC_drop_files",
    "AC_edge_match", "AC_edge_match_all", "AC_effect_near_point", "AC_element_click", "AC_element_find",
    "AC_element_list", "AC_element_remove", "AC_element_save", "AC_email_trigger_add", "AC_email_trigger_list",
    "AC_email_trigger_poll_once", "AC_email_trigger_remove", "AC_email_trigger_start", "AC_email_trigger_stop",
    "AC_emit_event", "AC_ensure_field_value", "AC_enumerate_monitors", "AC_evaluate_flag", "AC_evaluate_slo",
    "AC_evaluate_trajectory", "AC_ewma", "AC_execute_action", "AC_execute_files", "AC_execute_process",
    "AC_expand_control", "AC_expect_poll", "AC_explain_config", "AC_export_sarif", "AC_extract_fields",
    "AC_failure_clusters", "AC_failure_hook_clear", "AC_failure_hook_fire", "AC_failure_hook_list",
    "AC_failure_signature", "AC_feature_match", "AC_file_association", "AC_find_color_region",
    "AC_find_control_text", "AC_find_grid", "AC_find_lines", "AC_find_rectangles", "AC_find_separators",
    "AC_find_shapes", "AC_find_text_lines", "AC_find_text_regex", "AC_find_text_regions", "AC_flag_enabled",
    "AC_flaky_report", "AC_flow_order", "AC_focus_control", "AC_focus_window", "AC_for_each", "AC_for_each_row",
    "AC_foreground_window", "AC_foreground_window_pid", "AC_format_currency", "AC_format_date",
    "AC_format_decimal", "AC_format_list", "AC_format_message", "AC_fuse_elements", "AC_fuzzy_best_match",
    "AC_fuzzy_dedupe", "AC_fuzzy_ratio", "AC_gamepad_click", "AC_gamepad_dpad", "AC_gamepad_left_stick",
    "AC_gamepad_left_trigger", "AC_gamepad_press", "AC_gamepad_release", "AC_gamepad_reset",
    "AC_gamepad_right_stick", "AC_gamepad_right_trigger", "AC_generate_code", "AC_generate_data",
    "AC_generate_html", "AC_generate_html_report", "AC_generate_json", "AC_generate_json_report",
    "AC_generate_sbom", "AC_generate_sop", "AC_generate_xml", "AC_generate_xml_report", "AC_get_asset",
    "AC_get_client_rect", "AC_get_clipboard_csv", "AC_get_clipboard_files", "AC_get_clipboard_html",
    "AC_get_clipboard_rtf", "AC_get_control_text", "AC_get_element_properties", "AC_get_keyboard_keys_table",
    "AC_get_mouse_position", "AC_get_mouse_table", "AC_get_selected_text", "AC_get_selection", "AC_get_var",
    "AC_get_visible_text", "AC_get_volume", "AC_gettext_ngettext", "AC_gettext_translate", "AC_grade_contrast",
    "AC_grid_cell", "AC_grid_cells", "AC_grid_rects", "AC_group_failures", "AC_group_paragraphs", "AC_guard_text",
    "AC_handle_file_dialog", "AC_has_motion", "AC_heal_stats", "AC_histogram_changed", "AC_history_clear",
    "AC_history_list", "AC_hold_key", "AC_hotkey", "AC_http_replay", "AC_http_request", "AC_http_to_var",
    "AC_human_move", "AC_human_type", "AC_humanize_role", "AC_idempotency_begin", "AC_idempotency_complete",
    "AC_idempotency_release", "AC_idle_point", "AC_idle_seconds", "AC_if_image_found", "AC_if_pixel", "AC_if_var",
    "AC_image_hash", "AC_image_histogram", "AC_image_quality", "AC_ime_state", "AC_inc_var", "AC_infer_schema",
    "AC_input_reachable", "AC_input_sequence", "AC_inspector_reset", "AC_ios_alert_accept", "AC_ios_alert_dismiss",
    "AC_ios_app_state", "AC_ios_click_element", "AC_ios_device_info", "AC_ios_drag", "AC_ios_dump_source",
    "AC_ios_find_by_description", "AC_ios_find_element", "AC_ios_find_image", "AC_ios_find_text",
    "AC_ios_get_clipboard", "AC_ios_install_app", "AC_ios_launch_app", "AC_ios_long_press", "AC_ios_pinch",
    "AC_ios_press_key", "AC_ios_pull_file", "AC_ios_push_file", "AC_ios_screen_info", "AC_ios_screenshot",
    "AC_ios_self_heal", "AC_ios_set_clipboard", "AC_ios_start_recording", "AC_ios_stop_app",
    "AC_ios_stop_recording", "AC_ios_swipe", "AC_ios_tap", "AC_ios_type", "AC_ios_wait_for_app", "AC_is_composing",
    "AC_is_idle", "AC_json_extract", "AC_json_query", "AC_jwt_decode", "AC_jwt_encode", "AC_keep_awake_on",
    "AC_label_color", "AC_legacy_default_action", "AC_legacy_info", "AC_list_assets", "AC_list_executions",
    "AC_list_views", "AC_list_windows", "AC_llm_plan", "AC_llm_run", "AC_load_data", "AC_load_dotenv",
    "AC_localize_changes", "AC_locate_all_image", "AC_locate_and_click", "AC_locate_chain",
    "AC_locate_image_center", "AC_locate_text", "AC_lock_session", "AC_loop", "AC_loop_guard_observe",
    "AC_loop_guard_reset", "AC_make_json_patch", "AC_mark_click", "AC_mark_screen", "AC_mask_rows",
    "AC_match_auto", "AC_match_color", "AC_match_color_all", "AC_match_elements", "AC_match_ensemble",
    "AC_match_json", "AC_match_labels_to_widgets", "AC_match_masked", "AC_match_masked_all",
    "AC_match_persistence", "AC_match_rotated", "AC_match_rotated_all", "AC_match_subpixel", "AC_match_template",
    "AC_match_template_all", "AC_match_theme", "AC_match_with_trust", "AC_mcp_manifest", "AC_memory_forget",
    "AC_memory_recall", "AC_memory_recent", "AC_memory_remember", "AC_memory_stats", "AC_merge_patch",
    "AC_merge_results", "AC_mine_actions", "AC_minimize_window", "AC_minimize_windows_for_pid",
    "AC_monitor_at_point", "AC_most_salient", "AC_mouse_left", "AC_mouse_middle", "AC_mouse_right",
    "AC_mouse_scroll", "AC_move_along_path", "AC_move_element", "AC_move_mouse_relative", "AC_move_to_trash",
    "AC_move_window", "AC_near_duplicates", "AC_next_url", "AC_normalize_ext", "AC_normalize_text",
    "AC_normalize_url", "AC_notify", "AC_notify_webhook", "AC_now_to_var", "AC_observation_index",
    "AC_observe_add", "AC_observe_list", "AC_observe_poll", "AC_observe_remove", "AC_observe_start",
    "AC_observe_stop", "AC_ocr_languages", "AC_ocr_read_structure", "AC_ocr_status", "AC_ocr_to_var",
    "AC_open_path", "AC_otp_to_var", "AC_outbox_enqueue", "AC_outbox_pending", "AC_outline",
    "AC_parse_cache_control", "AC_parse_decimal", "AC_parse_dotenv", "AC_parse_link_header", "AC_parse_multipart",
    "AC_parse_number", "AC_parse_problem", "AC_parse_quality_values", "AC_parse_set_cookie", "AC_parse_sse",
    "AC_pdf_to_var", "AC_pending_artifacts", "AC_percentiles", "AC_perceptual_diff", "AC_place_labels",
    "AC_plan_file_drop", "AC_plan_keep_awake", "AC_plan_lock_session", "AC_plan_open", "AC_plan_repair",
    "AC_plan_retry_delays", "AC_point_for_cell", "AC_populate_table", "AC_post_click_to_window",
    "AC_post_key_to_window", "AC_preprocess_image", "AC_presence_list", "AC_presence_update_cursor",
    "AC_press_keyboard_key", "AC_press_mouse", "AC_profile_rows", "AC_profiler_disable", "AC_profiler_enable",
    "AC_profiler_hot_spots", "AC_profiler_reset", "AC_profiler_stats", "AC_propose_elements", "AC_pseudo_localize",
    "AC_quality_gate", "AC_quarantine_add", "AC_quarantine_auto", "AC_quarantine_clear", "AC_quarantine_list",
    "AC_quarantine_remove", "AC_queue_add", "AC_queue_complete", "AC_queue_fail", "AC_queue_next",
    "AC_queue_stats", "AC_random_to_var", "AC_rank_changes", "AC_rank_tests", "AC_rate_limit", "AC_read_barcodes",
    "AC_read_document", "AC_read_file_to_var", "AC_read_presentation", "AC_read_qr", "AC_read_table",
    "AC_read_text_in_region", "AC_read_workbook", "AC_readability_report", "AC_reading_order", "AC_realize_item",
    "AC_record", "AC_redact_config", "AC_redact_pii", "AC_redact_screenshot", "AC_redact_secret_text",
    "AC_region_color_stats", "AC_region_contrast", "AC_region_stability", "AC_release_keyboard_key",
    "AC_release_mouse", "AC_remote_connect", "AC_remote_disconnect", "AC_remote_send_input", "AC_repair_pending",
    "AC_repair_record", "AC_repair_resolved", "AC_replay_timeline", "AC_replay_trace", "AC_resize_element",
    "AC_resolve_config", "AC_resolve_pointer", "AC_resolve_ref", "AC_resolve_refs", "AC_restore_window_layout",
    "AC_retry", "AC_retry_after", "AC_retry_delay", "AC_rrule_next", "AC_rrule_occurrences", "AC_run_agent",
    "AC_run_chaos", "AC_run_dag", "AC_run_device_matrix", "AC_run_resumable", "AC_run_saga",
    "AC_run_state_machine", "AC_run_stoppable", "AC_run_suite", "AC_s3_delete", "AC_s3_download", "AC_s3_list",
    "AC_s3_upload", "AC_salient_regions", "AC_save_window_layout", "AC_scale_sweep", "AC_scan_secrets",
    "AC_scan_vulns", "AC_score_candidates", "AC_score_step", "AC_screen_changed", "AC_screen_diff",
    "AC_screen_size", "AC_screen_snapshot", "AC_screenshot", "AC_scroll_control_into_view", "AC_scroll_to_find",
    "AC_search_documents", "AC_seed_everything", "AC_segment_hsv", "AC_select_control_item",
    "AC_select_control_text", "AC_select_tests", "AC_self_heal_click", "AC_self_heal_locate",
    "AC_self_heal_log_clear", "AC_self_heal_log_list", "AC_send_email", "AC_send_to_back", "AC_sequence_observe",
    "AC_serialize_observation", "AC_set_asset", "AC_set_clipboard_csv", "AC_set_clipboard_files",
    "AC_set_clipboard_html", "AC_set_clipboard_rtf", "AC_set_control_range", "AC_set_field_text",
    "AC_set_mouse_position", "AC_set_mute", "AC_set_record_enable", "AC_set_topmost", "AC_set_var", "AC_set_view",
    "AC_set_volume", "AC_set_window_state", "AC_settle_point", "AC_shard_suite", "AC_shell_command",
    "AC_shell_to_var", "AC_simhash", "AC_simulate_cvd", "AC_skill_list", "AC_skill_remove", "AC_skill_run",
    "AC_skill_save", "AC_skill_search", "AC_sleep", "AC_slugify", "AC_sma", "AC_snap_window", "AC_soft_assert",
    "AC_spans_to_otlp", "AC_sql_to_var", "AC_ssim_changed_regions", "AC_ssim_compare", "AC_start_webrtc_viewer",
    "AC_stop_execution", "AC_stop_record", "AC_stop_record_timeline", "AC_stop_webrtc_viewer",
    "AC_store_validators", "AC_tab_order", "AC_table_cell", "AC_table_headers", "AC_tag_kinds", "AC_take_golden",
    "AC_text_similarity", "AC_three_way_merge", "AC_tile_rect", "AC_timeout_stats", "AC_to_model",
    "AC_to_physical", "AC_toggle_mute", "AC_trace_export", "AC_trace_extract", "AC_trace_inject",
    "AC_trace_record", "AC_trace_reset", "AC_trace_summary", "AC_transform_var", "AC_try", "AC_ts_downsample",
    "AC_ts_rate", "AC_tween_drag", "AC_type_keyboard", "AC_type_unicode", "AC_type_unicode_keys",
    "AC_type_unicode_text", "AC_unified_diff", "AC_urls_equal", "AC_usb_watch_start", "AC_usb_watch_stop",
    "AC_validate_action", "AC_validate_config", "AC_validate_json", "AC_validate_rows", "AC_verify_artifact",
    "AC_verify_field_value", "AC_verify_provenance", "AC_vlm_click", "AC_vlm_locate", "AC_voice_clear",
    "AC_voice_dispatch", "AC_voice_list", "AC_voice_register", "AC_vote_centers", "AC_wait_actionable",
    "AC_wait_clipboard_change", "AC_wait_color", "AC_wait_for_composition_commit", "AC_wait_for_file",
    "AC_wait_for_focus_change", "AC_wait_for_port", "AC_wait_for_process", "AC_wait_for_unlock", "AC_wait_image",
    "AC_wait_image_gone", "AC_wait_pixel", "AC_wait_pixel_changes", "AC_wait_region_idle", "AC_wait_screen_stable",
    "AC_wait_text", "AC_wait_text_gone", "AC_wait_until_app_idle", "AC_wait_window", "AC_wait_window_closed",
    "AC_wait_window_title", "AC_walk_tree", "AC_watchdog_add", "AC_watchdog_list", "AC_watchdog_start",
    "AC_watchdog_stop", "AC_wcag_audit", "AC_web_available", "AC_web_current_url", "AC_web_list_commands",
    "AC_web_open", "AC_web_quit", "AC_web_run", "AC_web_run_actions", "AC_web_screenshot",
    "AC_webrtc_process_offer", "AC_webrtc_send_input", "AC_webrtc_viewer_status", "AC_while_image", "AC_while_var",
    "AC_window_interaction_state", "AC_window_pid", "AC_window_rect", "AC_windows_for_pid", "AC_with_modifiers",
    "AC_workflow_control", "AC_workflow_download", "AC_workflow_manifest", "AC_workflow_open", "AC_workflow_wait",
    "AC_write", "AC_write_document", "AC_write_presentation", "AC_write_secret", "AC_write_step_video",
    "AC_write_workbook", "AC_ws_connect", "AC_ws_disconnect", "AC_ws_send_input", "AC_ws_viewer_status",
    "AC_xy_cut",
})

__all__ = ["OPERATOR_COMMANDS", "OPERATOR_NOTES"]
