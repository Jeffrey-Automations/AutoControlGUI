"""MCP data adapters delegating lazily to executor commands.

Annotations mirror the executor JSON boundary, including heterogeneous payloads.
"""

from typing import Any, Dict


def trace_inject(headers: Any = None, traceparent: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _trace_inject

    return _trace_inject(headers, traceparent)


def trace_extract(headers: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _trace_extract

    return _trace_extract(headers)


def baggage_parse(header: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _baggage_parse

    return _baggage_parse(header)


def baggage_format(items: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _baggage_format

    return _baggage_format(items)


def normalize_text(text: str, form: str = "NFKC", casefold: Any = True, collapse_ws: Any = True) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _normalize_text

    return _normalize_text(text, form, casefold, collapse_ws)


def slugify(text: str, sep: str = "-") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _slugify

    return _slugify(text, sep)


def text_similarity(a: str, b: str, metric: str = "jaro_winkler") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _text_similarity

    return _text_similarity(a, b, metric)


def simhash(text: str, bits: Any = 64) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _simhash

    return _simhash(text, bits)


def near_duplicates(texts: Any, max_distance: Any = 3) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _near_duplicates

    return _near_duplicates(texts, max_distance)


def canonical_log(fields: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _canonical_log

    return _canonical_log(fields)


def spans_to_otlp(spans: Any, resource_attrs: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _spans_to_otlp

    return _spans_to_otlp(spans, resource_attrs)


def validate_config(schema: Any, config: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _validate_config

    return _validate_config(schema, config)


def resolve_ref(ref: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _resolve_ref

    return _resolve_ref(ref)


def resolve_refs(obj: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _resolve_refs

    return _resolve_refs(obj)


def parse_link_header(value: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _parse_link_header

    return _parse_link_header(value)


def next_url(value: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _next_url

    return _next_url(value)


def build_multipart(fields: Any = None, files: Any = None, boundary: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _build_multipart

    return _build_multipart(fields, files, boundary)


def parse_multipart(content_type: str, body_base64: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _parse_multipart

    return _parse_multipart(content_type, body_base64)


def decode_body(headers: Any, body_base64: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _decode_body

    return _decode_body(headers, body_base64)


def parse_quality_values(header: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _parse_quality_values

    return _parse_quality_values(header)


def cookie_header(set_cookies: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cookie_header

    return _cookie_header(set_cookies)


def parse_set_cookie(header: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _parse_set_cookie

    return _parse_set_cookie(header)


def parse_cache_control(headers: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _parse_cache_control

    return _parse_cache_control(headers)


def store_validators(response: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _store_validators

    return _store_validators(response)


def redact_config(obj: Any, mask: str = "***") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _redact_config

    return _redact_config(obj, mask)


def redact_secret_text(text: str, mask: str = "***") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _redact_secret_text

    return _redact_secret_text(text, mask)


def profile_rows(rows: Any, columns: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _profile_rows

    return _profile_rows(rows, columns)


def infer_schema(rows: Any, columns: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _infer_schema

    return _infer_schema(rows, columns)


def parse_problem(response: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _parse_problem

    return _parse_problem(response)


def parse_dotenv(text: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _parse_dotenv

    return _parse_dotenv(text)


def load_dotenv(path: str, override: Any = False) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _load_dotenv

    return _load_dotenv(path, override)


def parse_sse(text: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _parse_sse

    return _parse_sse(text)


def resolve_config(layers: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _resolve_config

    return _resolve_config(layers)


def explain_config(layers: Any, key: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _explain_config

    return _explain_config(layers, key)


def check_compatibility(old: Any, new: Any, mode: str = "backward") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _check_compatibility

    return _check_compatibility(old, new, mode)


def ts_rate(series: Any, window_s: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _ts_rate

    return _ts_rate(series, window_s)


def ts_downsample(series: Any, bucket_s: Any, agg: str = "avg") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _ts_downsample

    return _ts_downsample(series, bucket_s, agg)


def detect_anomalies(values: Any, method: str = "mad", threshold: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _detect_anomalies

    return _detect_anomalies(values, method, threshold)


def sma(values: Any, window: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _sma

    return _sma(values, window)


def ewma(values: Any, alpha: Any = 0.3) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _ewma

    return _ewma(values, alpha)


def idempotency_begin(name: str, key: str, request: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _idempotency_begin

    return _idempotency_begin(name, key, request)


def idempotency_complete(name: str, key: str, response: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _idempotency_complete

    return _idempotency_complete(name, key, response)


def idempotency_release(name: str, key: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _idempotency_release

    return _idempotency_release(name, key)


def dedup_check(name: str, message_id: str, ttl_s: Any = 3600) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _dedup_check

    return _dedup_check(name, message_id, ttl_s)


def sequence_observe(name: str, stream_id: str, seq: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _sequence_observe

    return _sequence_observe(name, stream_id, seq)


def cas_put(name: str, key: str, value: Any, expected_version: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cas_put

    return _cas_put(name, key, value, expected_version)


def cas_get(name: str, key: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cas_get

    return _cas_get(name, key)


def outbox_enqueue(name: str, event: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _outbox_enqueue

    return _outbox_enqueue(name, event)


def outbox_pending(name: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _outbox_pending

    return _outbox_pending(name)


def collation_sort(
    items: Any, strength: str = "tertiary", tailoring: Any = None, reverse: Any = False
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _collation_sort

    return _collation_sort(items, strength, tailoring, reverse)


def collation_compare(first: str, second: str, strength: str = "tertiary", tailoring: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _collation_compare

    return _collation_compare(first, second, strength, tailoring)


def confusable_scan(text: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _confusable_scan

    return _confusable_scan(text)


def confusable_compare(first: str, second: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _confusable_compare

    return _confusable_compare(first, second)


def readability_report(text: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _readability_report

    return _readability_report(text)


def bidi_check(text: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _bidi_check

    return _bidi_check(text)


def bidi_strip(text: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _bidi_strip

    return _bidi_strip(text)


def format_list(items: Any, style: str = "and", locale: str = "en") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _format_list

    return _format_list(items, style, locale)


def format_message(pattern: str, args: Any = None, locale: str = "en") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _format_message

    return _format_message(pattern, args, locale)


def gettext_translate(po: str, msgid: str, context: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _gettext_translate

    return _gettext_translate(po, msgid, context)


def gettext_ngettext(po: str, msgid: str, msgid_plural: str, n: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _gettext_ngettext

    return _gettext_ngettext(po, msgid, msgid_plural, n)


def checksum_validate(scheme: str, number: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _checksum_validate

    return _checksum_validate(scheme, number)


def checksum_digit(scheme: str, partial: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _checksum_digit

    return _checksum_digit(scheme, partial)


def detect_drift(reference: Any, current: Any, threshold: Any = 0.25, bins: Any = 10) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _detect_drift

    return _detect_drift(reference, current, threshold, bins)


def categorical_drift(reference: Any, current: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _categorical_drift

    return _categorical_drift(reference, current)


def diff_rows(old_rows: Any, new_rows: Any, key: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _diff_rows

    return _diff_rows(old_rows, new_rows, key)


def cell_changes(old_rows: Any, new_rows: Any, key: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cell_changes

    return _cell_changes(old_rows, new_rows, key)


def check_foreign_key(child_rows: Any, child_col: str, parent_rows: Any, parent_col: str) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _check_foreign_key

    return _check_foreign_key(child_rows, child_col, parent_rows, parent_col)


def check_unique_key(rows: Any, cols: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _check_unique_key

    return _check_unique_key(rows, cols)


def check_accepted_values(rows: Any, col: str, allowed: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _check_accepted_values

    return _check_accepted_values(rows, col, allowed)


def check_row_count(rows: Any, minimum: Any = None, maximum: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _check_row_count

    return _check_row_count(rows, minimum, maximum)
