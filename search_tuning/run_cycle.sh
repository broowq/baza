#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_cycle.sh — overnight scoring-tuning cycle harness
#
# Steps:
#   1. Run the scoring regression bank (deterministic, no network).
#   2. Parse `SCORING_BANK_SUMMARY passed=X/Y failures=[...]` line.
#   3. Write a Markdown cycle summary to search_tuning/cycles/cycle_<ts>.md
#      with: timestamp, pass rate, failing cases, git commit hash.
#   4. Exit 0 if pass rate >= prior cycle's rate, else 1.
#
# Usage:
#   ./search_tuning/run_cycle.sh
#
# Exits:
#   0 — pass rate is >= previous cycle (or first cycle)
#   1 — regression detected
#   2 — pytest itself failed to run / couldn't parse summary
# -----------------------------------------------------------------------------

set -u  # undefined var = error; do NOT use -e because we want to tolerate
        # individual test failures (they are the whole point).

# --- paths -------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
CYCLES_DIR="${REPO_ROOT}/search_tuning/cycles"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
CYCLE_FILE="${CYCLES_DIR}/cycle_${TIMESTAMP}.md"
LOG_FILE="${CYCLES_DIR}/cycle_${TIMESTAMP}.log"

mkdir -p "${CYCLES_DIR}"

# --- git metadata ------------------------------------------------------------
GIT_COMMIT="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
GIT_BRANCH="$(cd "${REPO_ROOT}" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
GIT_DIRTY=""
if ! (cd "${REPO_ROOT}" && git diff --quiet --ignore-submodules HEAD -- 2>/dev/null); then
    GIT_DIRTY=" (dirty)"
fi

# --- run the bank ------------------------------------------------------------
echo "[cycle ${TIMESTAMP}] running scoring bank..."
pushd "${BACKEND_DIR}" >/dev/null || { echo "backend dir missing"; exit 2; }

# -s so the SCORING_BANK_SUMMARY print line is not swallowed by pytest capture.
# Pick pytest from backend venv if present; fall back to PATH.
PYTEST_BIN="${BACKEND_DIR}/.venv/bin/pytest"
[[ -x "${PYTEST_BIN}" ]] || PYTEST_BIN="pytest"

# Cycle 1 added test_relevance_bank.py (pre-filter / _candidate_relevance_score).
# Cycle 2 added test_query_builders.py (query-string regression for the
# prompt-aware discover / yandex-map / _pick_negatives builders).
# Run all files; each emits its own *_BANK_SUMMARY line and (the relevance
# bank) a legacy-compatible SCORING_BANK_SUMMARY alias. We parse the UNION
# below so the pass rate covers pre-filtering, enrichment scoring, AND
# query-string construction.
BANK_FILES=()
for f in tests/test_scoring_bank.py tests/test_relevance_bank.py tests/test_query_builders.py; do
    [[ -f "${BACKEND_DIR}/${f}" ]] && BANK_FILES+=("${f}")
done
"${PYTEST_BIN}" "${BANK_FILES[@]}" -v --tb=short -s >"${LOG_FILE}" 2>&1
PYTEST_RC=$?

popd >/dev/null

# --- parse summary -----------------------------------------------------------
# Each bank emits: <NAME>_BANK_SUMMARY passed=X/Y failures=['case_a', ...]
# We pull every *_BANK_SUMMARY line and take the UNION. The legacy
# SCORING_BANK_SUMMARY alias emitted by the relevance bank is de-duped so it
# doesn't double-count.
# Pull every *_BANK_SUMMARY line (bash-3 compatible, no mapfile)
SUMMARY_RAW="$(grep -E '^[A-Z_]+_BANK_SUMMARY' "${LOG_FILE}" 2>/dev/null || true)"

if [[ -z "${SUMMARY_RAW}" ]]; then
    echo "ERROR: could not find any *_BANK_SUMMARY lines in pytest output." >&2
    echo "  see: ${LOG_FILE}" >&2
    cat >"${CYCLE_FILE}" <<EOF
# Cycle ${TIMESTAMP}

- **status:** HARNESS_ERROR
- **git:** ${GIT_COMMIT} on ${GIT_BRANCH}${GIT_DIRTY}
- **pytest exit:** ${PYTEST_RC}
- **log:** ${LOG_FILE}

Could not parse any \`*_BANK_SUMMARY\` line from pytest output. Inspect the log.
EOF
    exit 2
fi

# Aggregate by dedupe-via-sorted-unique keys (no assoc arrays).
PASSED=0
TOTAL=0
ALL_FAILURES=""
SEEN_KEYS=""
while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    RATIO="$(echo "${line}" | sed -nE 's/.*passed=([0-9]+\/[0-9]+).*/\1/p')"
    FAILS="$(echo "${line}" | sed -nE "s/.*failures=(\[.*\]).*/\1/p")"
    [[ -z "${RATIO}" ]] && continue
    P="${RATIO%/*}"
    T="${RATIO#*/}"
    KEY="${P}|${T}|${FAILS}"
    # Skip if we've seen an identical summary (alias dedupe).
    if [[ ",${SEEN_KEYS}," == *",${KEY},"* ]]; then
        continue
    fi
    SEEN_KEYS="${SEEN_KEYS},${KEY}"
    PASSED=$(( PASSED + P ))
    TOTAL=$(( TOTAL + T ))
    if [[ -n "${FAILS}" && "${FAILS}" != "[]" ]]; then
        INNER="${FAILS#[}"
        INNER="${INNER%]}"
        [[ -z "${INNER}" ]] && continue
        if [[ -z "${ALL_FAILURES}" ]]; then
            ALL_FAILURES="${INNER}"
        else
            ALL_FAILURES="${ALL_FAILURES}, ${INNER}"
        fi
    fi
done <<< "${SUMMARY_RAW}"

if [[ "${TOTAL}" -eq 0 ]]; then
    echo "ERROR: parsed no cases across summary lines." >&2
    exit 2
fi

FAILURES="[${ALL_FAILURES}]"
# Canonical union summary line (stable format — legacy regex
# `SCORING_BANK_SUMMARY passed=X/Y failures=[...]` still matches).
SUMMARY_LINE="SCORING_BANK_SUMMARY passed=${PASSED}/${TOTAL} failures=${FAILURES}"

PASS_PCT=$(( PASSED * 100 / TOTAL ))

# --- compare with prior cycle ------------------------------------------------
PRIOR_FILE="$(ls -1 "${CYCLES_DIR}"/cycle_*.md 2>/dev/null | grep -v "cycle_${TIMESTAMP}.md" | sort | tail -n 1 || true)"
PRIOR_PASSED=""
PRIOR_TOTAL=""
PRIOR_PCT=""
if [[ -n "${PRIOR_FILE}" && -f "${PRIOR_FILE}" ]]; then
    PRIOR_RATIO="$(grep -E '^- \*\*pass rate:\*\*' "${PRIOR_FILE}" | sed -nE 's/.*\*\*pass rate:\*\* ([0-9]+\/[0-9]+).*/\1/p' | head -n 1)"
    if [[ -n "${PRIOR_RATIO}" ]]; then
        PRIOR_PASSED="${PRIOR_RATIO%/*}"
        PRIOR_TOTAL="${PRIOR_RATIO#*/}"
        if [[ "${PRIOR_TOTAL}" -gt 0 ]]; then
            PRIOR_PCT=$(( PRIOR_PASSED * 100 / PRIOR_TOTAL ))
        fi
    fi
fi

REGRESSION="no"
if [[ -n "${PRIOR_PCT}" ]]; then
    if (( PASS_PCT < PRIOR_PCT )); then
        REGRESSION="yes"
    fi
fi

# --- write cycle summary -----------------------------------------------------
{
    echo "# Cycle ${TIMESTAMP}"
    echo
    echo "- **timestamp:** ${TIMESTAMP}"
    echo "- **git:** ${GIT_COMMIT} on ${GIT_BRANCH}${GIT_DIRTY}"
    echo "- **pass rate:** ${PASSED}/${TOTAL} (${PASS_PCT}%)"
    if [[ -n "${PRIOR_PCT}" ]]; then
        echo "- **prior cycle:** ${PRIOR_PASSED}/${PRIOR_TOTAL} (${PRIOR_PCT}%) — $(basename "${PRIOR_FILE}")"
    else
        echo "- **prior cycle:** (none — first cycle)"
    fi
    echo "- **regression:** ${REGRESSION}"
    echo "- **pytest exit:** ${PYTEST_RC}"
    echo "- **log:** $(basename "${LOG_FILE}")"
    echo
    echo "## Failing cases"
    echo
    if [[ "${FAILURES}" == "[]" || -z "${FAILURES}" ]]; then
        echo "_none — bank fully green_"
    else
        echo '```'
        echo "${FAILURES}"
        echo '```'
    fi
    echo
    echo "## Raw summary line"
    echo
    echo '```'
    echo "${SUMMARY_LINE}"
    echo '```'
} >"${CYCLE_FILE}"

echo "[cycle ${TIMESTAMP}] ${PASSED}/${TOTAL} passed (${PASS_PCT}%)"
echo "[cycle ${TIMESTAMP}] report: ${CYCLE_FILE}"

# --- exit --------------------------------------------------------------------
if [[ "${REGRESSION}" == "yes" ]]; then
    echo "[cycle ${TIMESTAMP}] REGRESSION vs prior cycle (${PRIOR_PCT}% → ${PASS_PCT}%)"
    exit 1
fi
exit 0
