"""独立 GPU 门控: 检查已安装权重读取与语言模型前向, 不生成正式 PDB 结构."""

import importlib.metadata
from pathlib import Path

import esm
import fm
import torch


if __name__ == "__main__":
    assert torch.cuda.is_available(), "GPU 门控要求已分配 CUDA 设备"
    print("DEVICE", torch.cuda.get_device_name(0), flush=True)
    package = Path(importlib.metadata.distribution("CryoAtom2").locate_file("CryoAtom2"))
    for name in ("RUNet.pth", "CryoNet.pth", "CryoNet_no_seq.pth"):
        checkpoint = torch.load(package / "checkpoint" / name, map_location="cpu")
        assert isinstance(checkpoint, dict) and checkpoint, name
        print("CHECKPOINT_READ_OK", name, flush=True)
        del checkpoint
    for label, loader, sequence in [("ESM2", esm.pretrained.esm2_t33_650M_UR50D, "ACDEFGHIK"), ("RNA-FM", fm.pretrained.rna_fm_t12, "AUGC")]:
        model, alphabet = loader()
        model = model.eval().to("cuda:0")
        _, _, tokens = alphabet.get_batch_converter()([(label, sequence)])
        with torch.no_grad():
            logits = model(tokens.to("cuda:0"))["logits"]
        assert torch.isfinite(logits).all(), label
        print("LANGUAGE_FORWARD_OK", label, tuple(logits.shape), flush=True)
        del logits, model, tokens
        torch.cuda.empty_cache()
    print("RUNTIME_GATE_PASSED", flush=True)
