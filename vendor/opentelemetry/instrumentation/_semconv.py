# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
# SpanLife vendoring: exact stability classes excerpt; unused HTTP/DB helpers omitted.
# Original git blob e1af0c0960624bd5ad2f4ce5e402f09ee3bd2e54, lines 181-262.
import os
import threading
from enum import Enum

OTEL_SEMCONV_STABILITY_OPT_IN = "OTEL_SEMCONV_STABILITY_OPT_IN"

class _OpenTelemetryStabilitySignalType(Enum):
    HTTP = "http"
    DATABASE = "database"
    GEN_AI = "gen_ai"


class _StabilityMode(Enum):
    DEFAULT = "default"
    HTTP = "http"
    HTTP_DUP = "http/dup"
    DATABASE = "database"
    DATABASE_DUP = "database/dup"
    GEN_AI_LATEST_EXPERIMENTAL = "gen_ai_latest_experimental"


def _report_new(mode: _StabilityMode):
    return mode != _StabilityMode.DEFAULT


def _report_old(mode: _StabilityMode):
    return mode not in (_StabilityMode.HTTP, _StabilityMode.DATABASE)


class _OpenTelemetrySemanticConventionStability:
    _initialized = False
    _lock = threading.Lock()
    _OTEL_SEMCONV_STABILITY_SIGNAL_MAPPING = {}

    @classmethod
    def _initialize(cls):
        with cls._lock:
            if cls._initialized:
                return

            # Users can pass in comma delimited string for opt-in options
            # Only values for http, gen ai, and database stability are supported for now
            opt_in = os.environ.get(OTEL_SEMCONV_STABILITY_OPT_IN)

            if not opt_in:
                # early return in case of default
                cls._OTEL_SEMCONV_STABILITY_SIGNAL_MAPPING = {
                    _OpenTelemetryStabilitySignalType.HTTP: _StabilityMode.DEFAULT,
                    _OpenTelemetryStabilitySignalType.DATABASE: _StabilityMode.DEFAULT,
                    _OpenTelemetryStabilitySignalType.GEN_AI: _StabilityMode.DEFAULT,
                }
                cls._initialized = True
                return

            opt_in_list = [s.strip() for s in opt_in.split(",")]

            cls._OTEL_SEMCONV_STABILITY_SIGNAL_MAPPING[_OpenTelemetryStabilitySignalType.HTTP] = cls._filter_mode(
                opt_in_list, _StabilityMode.HTTP, _StabilityMode.HTTP_DUP
            )

            cls._OTEL_SEMCONV_STABILITY_SIGNAL_MAPPING[_OpenTelemetryStabilitySignalType.GEN_AI] = cls._filter_mode(
                opt_in_list,
                _StabilityMode.DEFAULT,
                _StabilityMode.GEN_AI_LATEST_EXPERIMENTAL,
            )

            cls._OTEL_SEMCONV_STABILITY_SIGNAL_MAPPING[_OpenTelemetryStabilitySignalType.DATABASE] = cls._filter_mode(
                opt_in_list,
                _StabilityMode.DATABASE,
                _StabilityMode.DATABASE_DUP,
            )
            cls._initialized = True

    @staticmethod
    def _filter_mode(opt_in_list, stable_mode, dup_mode):
        # Process semconv stability opt-in
        # http/dup,database/dup has higher precedence over http,database
        if dup_mode.value in opt_in_list:
            return dup_mode

        return stable_mode if stable_mode.value in opt_in_list else _StabilityMode.DEFAULT

    @classmethod
    def _get_opentelemetry_stability_opt_in_mode(cls, signal_type: _OpenTelemetryStabilitySignalType) -> _StabilityMode:
        # Get OpenTelemetry opt-in mode based off of signal type (http, messaging, etc.)
        return cls._OTEL_SEMCONV_STABILITY_SIGNAL_MAPPING.get(signal_type, _StabilityMode.DEFAULT)
