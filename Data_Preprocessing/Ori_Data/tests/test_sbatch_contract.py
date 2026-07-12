"""AdaLigand sbatch 资源参数与动态 run_cmd 契约测试。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SBATCH_ROOT = PROJECT_ROOT / "sbatch"


def test_job_core_reuses_a_valid_preloaded_run_cmd() -> None:
    """专用 core 必须复用普通文件，并在首次及每次重试前重新校验。"""
    core = (SBATCH_ROOT / "_adaligand_job_core.sh").read_text(encoding="utf-8")

    assert 'elif [ -f "${RUN_CMD_FILE}" ]; then' in core
    assert "[RunCmd] reusing preloaded file" in core
    assert 'write_adaligand_run_cmd "${RUN_CMD_FILE}"' in core
    validation_start = core.index("validate_run_cmd()")
    validation_end = core.index("\n}\n", validation_start)
    validation_body = core[validation_start:validation_end]
    assert '[ -L "${RUN_CMD_FILE}" ]' in validation_body
    assert 'bash -n "${RUN_CMD_FILE}"' in validation_body
    assert 'sha256sum "${RUN_CMD_FILE}"' in validation_body
    retry_loop = core.index("while true; do")
    retry_validation = core.index("    validate_run_cmd", retry_loop)
    command_start = core.index("    setsid stdbuf", retry_loop)
    assert retry_loop < retry_validation < command_start


def test_full_pipeline_resource_defaults_match_cpu96_contract() -> None:
    """未来完整提交默认使用 D64/E24、F12，并保留 G 的单 CPU analyze。"""
    de_script = (SBATCH_ROOT / "de_full.sbatch").read_text(encoding="utf-8")
    f_script = (SBATCH_ROOT / "f_full.sbatch").read_text(encoding="utf-8")
    g_script = (SBATCH_ROOT / "g_analyze.sbatch").read_text(encoding="utf-8")
    submit_script = (SBATCH_ROOT / "submit_full_pipeline.sh").read_text(encoding="utf-8")

    assert '${D_N_JOBS:-64}' in de_script
    assert '${E_N_JOBS:-24}' in de_script
    assert '${E_TIMEOUT_SECONDS:-3600}' in de_script
    assert '${F_N_JOBS:-12}' in f_script
    assert "#SBATCH --cpus-per-task=1" in g_script
    assert "D_N_JOBS=64,E_N_JOBS=24" in submit_script
    assert "F_N_JOBS=12" in submit_script


def test_de_f_g_use_cluster_unlimited_walltime_default() -> None:
    """DE/F/G 不应重新引入会截断多日正式运行的显式 walltime。"""
    for script_name in ("de_full.sbatch", "f_full.sbatch", "g_analyze.sbatch"):
        script = (SBATCH_ROOT / script_name).read_text(encoding="utf-8")
        assert "#SBATCH --time" not in script


def test_abc_source_resume_is_stage_aware_and_never_runs_b() -> None:
    """316114 恢复必须保留 pre-gate 证据，并用新 attempt 收敛 partial generic apply。"""
    script = (
        SBATCH_ROOT / "resume_abc_316114_source_v2.sh"
    ).read_text(encoding="utf-8")

    assert "scripts/b_download.py" not in script
    assert 'REPAIR="adaligand_ag_20260711T154658_csrc_v4"' in script
    assert 'POST="adaligand_ag_20260711T154658_csrc_v4_post_exact"' in script
    assert "scripts/c_descriptor_prefetch.py" in script
    assert "CCD:5GP" in script
    assert "descriptor_prefetch" in script
    descriptor_function = script[
        script.index("run_descriptor_prefetch()"):
        script.index("run_rebuild_audit_once()")
    ]
    assert 'if [[ -e "$summary" ]]' not in descriptor_function
    assert "delegated_full_rebuild_ready" in script
    assert "generic_attempt_${attempt}" in script
    assert "--require_all_exact" in script
    assert 'summary.get("counts") != {"exact": 2156}' in script
    assert "primary_key_migration" not in script  # 计数由冻结 rebuild summary 统一门禁

    final_c_start = script.rindex('"$PY" scripts/c_parse.py')
    final_c_end = script.index('"$PY" scripts/abc_release_gate.py', final_c_start)
    final_c = script[final_c_start:final_c_end]
    assert "--pdb_ids_file" not in final_c
    assert "--overwrite" not in final_c
    assert '--run_id "$FORMAL"' in final_c


def test_de_e_repair_is_filtered_then_refreshes_formal_status_without_d() -> None:
    """316115 恢复先隔离 18 个工程失败，再以正式 run id 无过滤复核 E。"""
    script = (SBATCH_ROOT / "resume_de_316115_e_repair_v1.sh").read_text(
        encoding="utf-8"
    )

    assert "scripts/d_atom_labels.py" not in script
    assert 'REPAIR="adaligand_ag_20260711T154658_eeng_v1"' in script
    assert "6f9bea3a9448f8f24940d3241520633890aefad88d737fad0580f47ff0b280be" in script
    assert "b03b7c72a00730f5fc0bb56b718f0f7f5a7313f11212fbc034fc74f4a6a6c7b0" in script
    assert "--n_jobs 4" in script
    assert "--timeout_seconds 21600" in script
    assert "--require_success" in script

    repair_start = script.index('"${PYTHON}" scripts/e_density.py')
    repair_end = script.index('"${PYTHON}" scripts/stage_release_gate.py', repair_start)
    repair_command = script[repair_start:repair_end]
    assert '--pdb_ids_file "${IDS_FILE}"' in repair_command
    assert '--run_id "${REPAIR}"' in repair_command

    formal_start = script.rindex('"${PYTHON}" scripts/e_density.py')
    formal_end = script.index('"${PYTHON}" scripts/stage_release_gate.py', formal_start)
    formal_command = script[formal_start:formal_end]
    assert "--pdb_ids_file" not in formal_command
    assert "--overwrite" not in formal_command
    assert '--run_id "${FORMAL}"' in formal_command
