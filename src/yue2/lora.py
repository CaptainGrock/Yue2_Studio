"""Inference-only acoustic LoRAs; base weights are restored exactly after use."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import hashlib
import math
import re

import torch
from safetensors.torch import load


def validate_strength(value):
    if isinstance(value, bool):
        raise ValueError("LoRA strength must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("LoRA strength must be a finite number")
    return value


def _targets(name):
    """Map native fused rows to the released model's separate projections."""
    native = name.startswith("diffusion_model.")
    if native:
        name = name[len("diffusion_model."):]
    if name in {"vae2llm", "llm2vae", "time_embedder.mlp.0", "time_embedder.mlp.2"}:
        return [name]
    match = re.fullmatch(r"model\.layers\.(\d+)\.(\w+)\.(\w+)", name)
    if not match:
        raise ValueError(f"Unsupported acoustic LoRA target: {name}")
    index, branch, projection = match.groups()
    if native:
        branch = {"self_attn": "nar_self_attn", "mlp": "nar_mlp"}.get(branch, "")
    allowed = {"nar_self_attn": {"q_proj", "k_proj", "v_proj", "o_proj"},
               "nar_mlp": {"gate_proj", "up_proj", "down_proj"}}
    fused = {("nar_self_attn", "qkv_proj"): ["q_proj", "k_proj", "v_proj"],
             ("nar_mlp", "gate_up_proj"): ["gate_proj", "up_proj"]}
    projections = fused.get((branch, projection)) if native else None
    if projections is None:
        if projection not in allowed.get(branch, set()):
            raise ValueError(f"Unsupported acoustic LoRA target: {name}")
        projections = [projection]
    return [f"model.layers.{index}.{branch}.{p}" for p in projections]


@dataclass(frozen=True)
class AcousticLoRA:
    path: str
    sha256: str
    metadata: dict
    groups: tuple

    @classmethod
    def read(cls, path):
        path = Path(path).resolve()
        if path.suffix.lower() != ".safetensors":
            raise ValueError("LoRA must be a .safetensors file")
        # Hash and deserialize the same bytes, even if the file is replaced later.
        data = path.read_bytes()
        tensors = load(data)
        import json
        header_size = int.from_bytes(data[:8], "little")
        metadata = json.loads(data[8:8 + header_size]).get("__metadata__", {})
        if metadata.get("format") not in {None, "comfyui-native-lora", "yue2-lora-v1", "pt"}:
            raise ValueError("Unsupported LoRA format")
        # Two community naming conventions carry the same math (delta = up @ down):
        # ComfyUI's .lora_down.weight/.lora_up.weight and PEFT's .lora_A/.lora_B.
        down_suffix = next((s for s in (".lora_down.weight", ".lora_A")
                            if any(k.endswith(s) for k in tensors)), None)
        if down_suffix is None:
            raise ValueError("LoRA is empty or contains unsupported/unpaired tensors")
        up_suffix = ".lora_up.weight" if down_suffix == ".lora_down.weight" else ".lora_B"
        def canonical(name):
            # Keep diffusion_model. intact: _targets maps native branch names
            # (mlp -> nar_mlp) only when it sees the native prefix itself.
            # Community files sometimes omit the model. prefix on native targets.
            if name.startswith("layers."):
                name = "model." + name
            return name
        groups, used = [], set()
        for key in sorted(tensors):
            if not key.endswith(down_suffix):
                continue
            name = key[:-len(down_suffix)]
            up_key, alpha_key = name + up_suffix, name + ".alpha"
            if up_key not in tensors:
                raise ValueError(f"Missing LoRA up matrix: {name}")
            down, up = tensors[key], tensors[up_key]
            if down.ndim != 2 or up.ndim != 2 or min(*down.shape, *up.shape) < 1 or up.shape[1] != down.shape[0]:
                raise ValueError(f"Invalid LoRA matrix dimensions: {name}")
            if any(not t.is_floating_point() or not torch.isfinite(t).all() for t in (down, up)):
                raise ValueError(f"LoRA matrices must be finite floating point tensors: {name}")
            alpha = tensors.get(alpha_key)
            if alpha is not None and alpha.numel() != 1:
                raise ValueError(f"Invalid LoRA alpha: {name}")
            default_alpha = metadata.get("alpha", down.shape[0]) if metadata.get("format") == "yue2-lora-v1" else down.shape[0]
            scale = validate_strength(alpha.item() if alpha is not None else default_alpha) / down.shape[0]
            try:
                targets = tuple(_targets(canonical(name)))
            except ValueError as exc:
                label = canonical(name)
                if label.startswith("text_encoders."):
                    raise ValueError("Targets the planner text-encoder branch, which the acoustic style engine cannot apply") from exc
                if re.fullmatch(r"model\.layers\.\d+\.(mlp|self_attn)\..+", label):
                    raise ValueError("Targets the AR composer branch, which the acoustic style engine cannot apply") from exc
                raise
            groups.append((targets, down.float(), up.float(), scale))
            used.update((key, up_key))
            if alpha is not None:
                used.add(alpha_key)
        if not groups:
            raise ValueError("LoRA is empty or contains unsupported/unpaired tensors")
        if used != tensors.keys():
            extra = sorted(set(tensors) - used)
            raise ValueError("Contains tensors the acoustic engine cannot apply: "
                             + ", ".join(extra[:3]) + ("…" if len(extra) > 3 else ""))
        return cls(str(path), hashlib.sha256(data).hexdigest(), metadata, tuple(groups))

    def info(self, strength):
        return {"path": self.path, "sha256": self.sha256, "strength": strength,
                "format": self.metadata.get("format", "safetensors"),
                "trigger_word": self.metadata.get("trigger_word", ""),
                "base_model": self.metadata.get("base_model", "")}

    def _bindings(self, model):
        bindings, seen = [], set()
        for names, down, up, scale in self.groups:
            offset = 0
            for name in names:
                try:
                    module = model.get_submodule(name)
                except AttributeError as exc:
                    raise ValueError(f"LoRA target missing from model: {name}") from exc
                if type(module) is not torch.nn.Linear or not module.weight.is_floating_point() or module.weight.device.type == "meta":
                    raise ValueError(f"LoRA requires an ordinary floating point Linear: {name}")
                weight = module.weight
                if id(weight) in seen or down.shape[1] != weight.shape[1] or offset + weight.shape[0] > up.shape[0]:
                    raise ValueError(f"LoRA shape mismatch or duplicate target: {name}")
                seen.add(id(weight))
                bindings.append((weight, down, up[offset:offset + weight.shape[0]], scale))
                offset += weight.shape[0]
            if offset != up.shape[0]:
                raise ValueError(f"LoRA output rows do not match model: {names}")
        return bindings

    def validate_model(self, model):
        self._bindings(model)

    @contextmanager
    def applied(self, model, strength):
        strength = validate_strength(strength)
        bindings = self._bindings(model)  # Validate every target before any write.
        saved = []
        try:
            if strength != 0:
                with torch.no_grad():
                    for weight, down, up, scale in bindings:
                        original = weight.detach().to("cpu", copy=True)
                        # CPU FP32 merge bounds GPU overhead to one weight copy.
                        updated = original.float() + (up @ down) * (scale * strength)
                        updated = updated.to(weight.dtype)
                        if not torch.isfinite(updated).all():
                            raise ValueError("LoRA strength produces non-finite weights")
                        saved.append((weight, original))
                        weight.copy_(updated)
            yield
        finally:
            with torch.no_grad():
                for weight, original in reversed(saved):
                    weight.copy_(original)
