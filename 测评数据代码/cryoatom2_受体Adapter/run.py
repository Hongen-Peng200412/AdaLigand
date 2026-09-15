"""CryoAtom2 受体适配的命令行模块.

``main()`` 解析一个 PDB 清单和输入、输出根目录, 然后只调用
``adapter.prepare_receptor_dataset()``. 长期产物是逐 PDB 的
``receptor_tokens.npz``、``sim.npy``、``sim.npz`` 和顶层有序
``受体适配记录.jsonl``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from adapter import prepare_receptor_dataset


def main() -> None:
    """解析一次受体适配任务, 并调用唯一的数据集入口.

    命令行输入:
        - split-file: Path, 有序 PDB JSON 清单.
        - cryoatom2-root: Path, CryoAtom2 逐 PDB ``latest.json`` 的根目录.
        - reference-root: Path, 已验收主 ``Ori_Data`` 根目录.
        - output-root: Path, 长期使用的 CryoAtom2 ``Ori_Data`` 根目录.
        - scratch-root: Path, 本次 Chimera 临时目录, 必须不存在.
        - chimera: Path, UCSF Chimera 可执行文件.
        - workers: int, 同时处理的 PDB 数.
        - timeout-seconds: float, 单个 Chimera 调用的超时秒数.

    副作用:
        - 把 ``receptor_tokens.npz``、``sim.npy``、``sim.npz`` 和一份有序 JSONL 记录写入 output-root.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-file", type=Path, required=True)
    parser.add_argument("--cryoatom2-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--chimera", type=Path, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    args = parser.parse_args()
    prepare_receptor_dataset(
        args.split_file,
        args.cryoatom2_root,
        args.reference_root,
        args.output_root,
        args.scratch_root,
        (str(args.chimera),),
        args.workers,
        args.timeout_seconds,
    )


if __name__ == "__main__":
    main()
