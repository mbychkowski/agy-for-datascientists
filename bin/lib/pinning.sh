# shellcheck shell=bash
# Shared Pinning library for Command Center CLI scripts.
# Sourced by bin/* scripts to load demo.env, validate PROJECT_ID and REGION,
# and pin all bq, gcloud storage, and Dataproc Serverless calls.

_pinning_resolve_repo_root() {
  local src="${BASH_SOURCE[0]}"
  while [[ -h "$src" ]]; do
    local dir
    dir="$(cd -P "$(dirname "$src")" && pwd)"
    src="$(readlink "$src")"
    [[ "$src" != /* ]] && src="$dir/$src"
  done
  local lib_dir
  lib_dir="$(cd -P "$(dirname "$src")" && pwd)"
  (cd -P "${lib_dir}/../.." && pwd)
}

REPO_ROOT="${REPO_ROOT:-$(_pinning_resolve_repo_root)}"

# Usage: _pinning_require_value <VAR_NAME> <description>
# Returns 1 with a [FAIL] message when VAR_NAME is unset, empty, or a 'your-' placeholder.
_pinning_require_value() {
  local name="$1"
  local description="$2"
  local value="${!name:-}"
  if [[ -z "${value}" || "${value}" == *your-* ]]; then
    echo "[FAIL] ${name} is missing or contains a 'your-' placeholder ('${value}'). Edit demo.env with your real ${description}." >&2
    return 1
  fi

  return 0
}

pinned_require_project_region() {
  _pinning_require_value PROJECT_ID "project ID" &&
    _pinning_require_value REGION "GCP region"
}

pinned_require_staging_bucket() {
  _pinning_require_value STAGING_BUCKET "staging bucket"
}

pinned_require_state_bucket() {
  _pinning_require_value STATE_BUCKET "Terraform state bucket"
}

pinned_load_env() {
  REPO_ROOT="${REPO_ROOT:-$(_pinning_resolve_repo_root)}"
  local env_file="${1:-${ENV_FILE:-${REPO_ROOT}/demo.env}}"
  ENV_FILE="${env_file}"

  if [[ ! -f "${env_file}" ]]; then
    echo "[FAIL] Environment file not found: ${env_file}" >&2
    return 1
  fi

  # shellcheck disable=SC1090
  source "${env_file}"

  if ! pinned_require_project_region; then
    return 1
  fi

  export PROJECT_ID REGION

  if [[ "${CLI_DATASET_SET:-false}" != "true" && -n "${DATASET_LOCATION:-}" && "${DATASET_LOCATION}" != *your-* ]]; then
    # shellcheck disable=SC2034
    DATASET_DIR="${DATASET_LOCATION}"
  fi

  return 0
}

pinned_require_cli() {
  local cli
  for cli in "$@"; do
    if ! command -v "${cli}" >/dev/null 2>&1; then
      echo "[FAIL] ${cli} CLI is not installed or not on PATH" >&2
      return 1
    fi
  done
  return 0
}

pinned_bq() {
  if ! command -v bq >/dev/null 2>&1; then
    echo "[FAIL] bq CLI is not installed or not on PATH" >&2
    return 1
  fi

  if ! pinned_require_project_region; then
    return 1
  fi

  if [[ $# -eq 0 ]]; then
    echo "[FAIL] pinned_bq requires a bq subcommand" >&2
    return 1
  fi

  local subcmd="$1"
  shift

  local -a flag_args=()
  while [[ $# -gt 0 && "$1" == -* ]]; do
    if [[ "$1" == "--set_label" && $# -ge 2 ]]; then
      flag_args+=("$1" "$2")
      shift 2
    else
      flag_args+=("$1")
      shift
    fi
  done

  bq "${subcmd}" ${flag_args[@]+"${flag_args[@]}"} \
    --project_id="${PROJECT_ID}" \
    --location="${REGION}" \
    "$@"
}

pinned_label() {
  local table="${1:-}"
  if [[ -z "${table}" ]]; then
    echo "[FAIL] pinned_label requires a table reference" >&2
    return 1
  fi

  if ! pinned_require_project_region; then
    return 1
  fi

  local target_ref="${table}"
  local display_table="${table}"
  if [[ "${table}" == *:* ]]; then
    display_table="${table#*:}"
  else
    target_ref="${PROJECT_ID}:${table}"
  fi

  if ! pinned_bq update --set_label demo:true "${target_ref}"; then
    echo "[FAIL] Failed to apply demo:true label to ${display_table}" >&2
    return 1
  fi

  return 0
}

pinned_bq_json() {
  REPO_ROOT="${REPO_ROOT:-$(_pinning_resolve_repo_root)}"
  local helper="${REPO_ROOT}/lib/bq_json.py"

  if [[ $# -eq 0 ]]; then
    python3 "${helper}"
    return $?
  fi

  case "$1" in
    query|show|ls|head|mk|rm|cp|load|update|extract|wait|version|info)
      local raw_out
      if ! raw_out="$(pinned_bq "$@" 2>&1)"; then
        echo "${raw_out}" >&2
        return 1
      fi
      python3 "${helper}" "${raw_out}"
      return $?
      ;;
    *)
      python3 "${helper}" "$1"
      return $?
      ;;
  esac
}

# Usage: pinned_has_demo_label "<raw bq show --format=json output>"
# Returns 0 only when the (possibly noisy) bq show output decodes to table
# metadata whose labels carry demo:true. Takes captured output, not a table ref,
# so callers can report "missing table" and "missing label" separately.
pinned_has_demo_label() {
  local meta_json
  if ! meta_json="$(pinned_bq_json "${1:-}" 2>/dev/null)"; then
    return 1
  fi

  python3 -c '
import json, sys
meta = json.loads(sys.argv[1])
labels = meta.get("labels") if isinstance(meta, dict) else None
sys.exit(0 if isinstance(labels, dict) and labels.get("demo") == "true" else 1)
' "${meta_json}"
}

pinned_storage() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "[FAIL] gcloud CLI is not installed or not on PATH" >&2
    return 1
  fi

  if ! pinned_require_project_region; then
    return 1
  fi

  if [[ $# -eq 0 ]]; then
    echo "[FAIL] pinned_storage requires a gcloud storage subcommand" >&2
    return 1
  fi

  if [[ "$1" == "buckets" && $# -ge 3 ]]; then
    local group="$1"
    local verb="$2"
    local bucket_url="$3"
    shift 3
    gcloud storage "${group}" "${verb}" "${bucket_url}" --project="${PROJECT_ID}" "$@"
  else
    local verb="$1"
    shift
    gcloud storage "${verb}" --project="${PROJECT_ID}" "$@"
  fi
}

pinned_dataproc_submit() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "[FAIL] gcloud CLI is not installed or not on PATH" >&2
    return 1
  fi

  if ! pinned_require_project_region; then
    return 1
  fi

  if ! pinned_require_staging_bucket; then
    return 1
  fi

  local is_async="false"
  local -a pos_args=()
  local -a job_args=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --)
        shift
        job_args=("$@")
        break
        ;;
      --async)
        is_async="true"
        shift
        ;;
      -*)
        echo "[FAIL] Unsupported flag for pinned_dataproc_submit: $1 (only --async is allowed; custom gcloud flags such as --service-account are forbidden per ADR 0002)" >&2
        return 1
        ;;
      *)
        pos_args+=("$1")
        shift
        ;;
    esac
  done

  if [[ ${#pos_args[@]} -ne 2 ]]; then
    echo "[FAIL] Usage: pinned_dataproc_submit [--async] <pyspark_script> <batch_id> [-- <job_args...>]" >&2
    return 1
  fi

  local script_path="${pos_args[0]}"
  local batch_id="${pos_args[1]}"
  local subnet="${SUBNET:-demo-dataproc-subnet}"

  local -a cmd=(
    gcloud dataproc batches submit pyspark "${script_path}"
    --project="${PROJECT_ID}"
    --region="${REGION}"
    --batch="${batch_id}"
    --version="3.0"
    --deps-bucket="gs://${STAGING_BUCKET}"
    --subnet="${subnet}"
  )

  if [[ "${is_async}" == "true" ]]; then
    cmd+=(--async)
  fi

  if [[ ${#job_args[@]} -gt 0 ]]; then
    cmd+=(-- "${job_args[@]}")
  fi

  "${cmd[@]}"
}

pinned_dataproc_describe() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "[FAIL] gcloud CLI is not installed or not on PATH" >&2
    return 1
  fi

  if ! pinned_require_project_region; then
    return 1
  fi

  local batch_id="${1:-}"
  if [[ -z "${batch_id}" ]]; then
    echo "[FAIL] pinned_dataproc_describe requires a batch_id" >&2
    return 1
  fi
  shift

  gcloud dataproc batches describe "${batch_id}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    "$@"
}

pinned_dataproc_delete() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "[FAIL] gcloud CLI is not installed or not on PATH" >&2
    return 1
  fi

  if ! pinned_require_project_region; then
    return 1
  fi

  local batch_id="${1:-}"
  if [[ -z "${batch_id}" ]]; then
    echo "[FAIL] pinned_dataproc_delete requires a batch_id" >&2
    return 1
  fi
  shift

  gcloud dataproc batches delete "${batch_id}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --quiet \
    "$@"
}
