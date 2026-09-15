"""CPU-only adapter math, restoration, and pipeline lifecycle checks."""
from concurrent.futures import ThreadPoolExecutor

import pytest
import torch
from safetensors.torch import save_file

from yue2.lora import AcousticLoRA
from yue2.modeling_yue2 import YuE2Config, YuE2ForCausalLM
from yue2.pipeline import YuE2Pipeline, SemanticResult, SymbolicPlan
from yue2.protocol import SongRequest, GenerationConfig
from yue2 import nar, pipeline


@pytest.fixture
def model():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    with torch.random.fork_rng():
        torch.manual_seed(173)
        value = YuE2ForCausalLM(YuE2Config(
            hidden_size=16, intermediate_size=32, num_hidden_layers=1,
            num_attention_heads=4, num_key_value_heads=2, head_dim=4,
            vocab_size=32, max_position_embeddings=128,
            latent_dim=64, vae_latent_dim=64, max_latent_frames=128)).eval()
    yield value
    torch.set_num_threads(old)


def write_adapter(tmp_path, name="diffusion_model.llm2vae", rows=64, cols=16,
                  rank=2, alpha=4., metadata=None):
    rng = torch.Generator().manual_seed(19)
    down = torch.randn(rank, cols, generator=rng) * .1
    up = torch.randn(rows, rank, generator=rng) * .1
    path = tmp_path / "test.safetensors"
    save_file({name + ".lora_down.weight": down, name + ".lora_up.weight": up,
               name + ".alpha": torch.tensor(alpha)}, path,
              metadata=metadata or {"format": "comfyui-native-lora", "trigger_word": "test_sound"})
    return path, up @ down * (alpha / rank)


@pytest.mark.parametrize("strength", [0., .5, 1., 2., -1.])
def test_strength_and_exact_bf16_restore(model, tmp_path, strength):
    model.to(torch.bfloat16)
    path, delta = write_adapter(tmp_path)
    adapter = AcousticLoRA.read(path)
    original = {k: v.clone() for k, v in model.state_dict().items()}
    for _ in range(3):
        with adapter.applied(model, strength):
            expected = (original["llm2vae.weight"].float() + delta * strength).bfloat16()
            assert torch.equal(model.llm2vae.weight, expected)
            assert all(torch.equal(v, original[k]) for k, v in model.state_dict().items() if k != "llm2vae.weight")
        assert all(torch.equal(v, original[k]) for k, v in model.state_dict().items())


@pytest.mark.parametrize("branch,fused,parts,rows", [
    ("self_attn", "qkv_proj", ["q_proj", "k_proj", "v_proj"], [16, 8, 8]),
    ("mlp", "gate_up_proj", ["gate_proj", "up_proj"], [32, 32]),
])
def test_fused_native_conversion(model, tmp_path, branch, fused, parts, rows):
    path, delta = write_adapter(tmp_path, f"diffusion_model.model.layers.0.{branch}.{fused}", sum(rows))
    modules = [model.get_submodule(f"model.layers.0.nar_{branch}.{p}") for p in parts]
    originals = [m.weight.clone() for m in modules]
    with AcousticLoRA.read(path).applied(model, .75):
        for module, original, change in zip(modules, originals, delta.split(rows)):
            torch.testing.assert_close(module.weight, original + change * .75)


def test_trainer_format_global_alpha(model, tmp_path):
    path = tmp_path / "trainer.safetensors"
    name = "model.layers.0.nar_self_attn.q_proj"
    save_file({name + ".lora_down.weight": torch.ones(2, 16),
               name + ".lora_up.weight": torch.ones(16, 2)}, path,
              metadata={"format": "yue2-lora-v1", "alpha": "4"})
    original = model.model.layers[0].nar_self_attn.q_proj.weight.clone()
    with AcousticLoRA.read(path).applied(model, 1):
        torch.testing.assert_close(model.model.layers[0].nar_self_attn.q_proj.weight, original + 4)


@pytest.mark.parametrize("name", ["model.layers.0.self_attn.q_proj", "diffusion_model.model.norm", "lm_head"])
def test_ar_and_unknown_targets_rejected(tmp_path, name):
    path, _ = write_adapter(tmp_path, name)
    with pytest.raises(ValueError, match="Unsupported acoustic"):
        AcousticLoRA.read(path)


@pytest.mark.parametrize("rows,cols,alpha", [(63,16,4), (64,15,4), (64,16,float("nan"))])
def test_invalid_adapter_does_not_change_base(model, tmp_path, rows, cols, alpha):
    path, _ = write_adapter(tmp_path, rows=rows, cols=cols, alpha=alpha)
    original = model.llm2vae.weight.clone()
    with pytest.raises(ValueError):
        with AcousticLoRA.read(path).applied(model, 1):
            pytest.fail("Invalid adapter accepted")
    assert torch.equal(model.llm2vae.weight, original)


def test_cancellation_and_partial_merge_failure_restore(model, tmp_path):
    path, _ = write_adapter(tmp_path)
    adapter = AcousticLoRA.read(path)
    original = model.llm2vae.weight.clone()
    with pytest.raises(InterruptedError):
        with adapter.applied(model, 1):
            raise InterruptedError("cancel")
    assert torch.equal(model.llm2vae.weight, original)
    name = "time_embedder.mlp.2"
    bad = ((name,), torch.full((1, 16), 1e30), torch.full((16, 1), 1e30), 1.)
    broken = AcousticLoRA(adapter.path, adapter.sha256, {}, adapter.groups + (bad,))
    with pytest.raises(ValueError, match="non-finite"):
        with broken.applied(model, 1):
            pass
    assert torch.equal(model.llm2vae.weight, original)


def bare_pipe(model):
    pipe = object.__new__(YuE2Pipeline)
    pipe._model, pipe._vae = model, None
    pipe.backend, pipe.quantization = "torch-eager", "none"
    pipe.progress, pipe.offload_ar = False, False
    pipe.device = torch.device("cpu")
    pipe.tokenizer = object()
    pipe.generation_config = GenerationConfig(ode_steps=2)
    pipe._load_model = lambda **kwargs: model
    return pipe


def test_real_synthesis_changes_then_none_restores(model, tmp_path, monkeypatch):
    pipe = bare_pipe(model)
    path, _ = write_adapter(tmp_path)
    monkeypatch.setattr(pipeline, "token_prefixes", lambda *args: [2, 3])
    noise = torch.randn(3, 64, generator=torch.Generator().manual_seed(41))
    monkeypatch.setattr(nar, "song_chunks", lambda *args: [nar.Chunk([2, 3, 4], noise)])
    semantic = SemanticResult(SymbolicPlan(SongRequest(style="test", lyrics="", cot="off"), None, [], [2, 3]), [0], {}, False)
    base = pipe.synthesize(semantic)
    original = model.llm2vae.weight.clone()
    info = pipe.load_lora(path)
    assert info["trigger_word"] == "test_sound" and len(info["sha256"]) == 64
    changed = pipe.synthesize(semantic)
    assert not (changed == base).all()
    assert torch.equal(model.llm2vae.weight, original)
    with pytest.raises(InterruptedError):
        pipe.synthesize(semantic, cancelled=lambda: True)
    assert torch.equal(model.llm2vae.weight, original)
    assert pipe.lora_info == info
    # Failure in shape validation preserves the previously selected adapter.
    bad_path, _ = write_adapter(tmp_path, rows=63)
    with pytest.raises(ValueError):
        pipe.load_lora(bad_path)
    assert pipe.lora_info == info
    # Adapter bytes are retained: replacing its file did not change this render.
    assert (pipe.synthesize(semantic) == changed).all()
    pipe.set_lora_strength(0)
    assert (pipe.synthesize(semantic) == base).all()
    pipe.unload_lora()
    assert pipe.lora_info is None and (pipe.synthesize(semantic) == base).all()


def test_selection_is_cpu_only_atomic_and_rejects_busy_changes(model, tmp_path):
    pipe = bare_pipe(model)
    path, _ = write_adapter(tmp_path)
    pipe._model = None
    pipe._load_model = lambda **kwargs: pytest.fail("Selection must not load a model")
    first = pipe.load_lora(path)
    with pytest.raises(ValueError):
        pipe.load_lora(path, strength=float("inf"))
    assert pipe.lora_info == first
    pipe._operation_lock.acquire()
    try:
        with ThreadPoolExecutor() as pool:
            with pytest.raises(RuntimeError, match="busy"):
                pool.submit(pipe.unload_lora).result()
        pipe._operation_depth = 1  # A callback on the generating thread.
        with pytest.raises(RuntimeError, match="during generation"):
            pipe.unload_lora()
    finally:
        pipe._operation_depth = 0
        pipe._operation_lock.release()
    pipe.close()
    assert pipe.lora_info is None


def test_metadata_enters_effective_config_only_when_selected(model, tmp_path):
    pipe = bare_pipe(model)
    pipe.vae_dir = tmp_path
    (tmp_path / "config.json").write_text('{}', encoding="utf-8")
    pipe.vae_core_frames, pipe.memory_budget_gib = 512, 24
    pipe.runtime_sha256 = "test"
    request = SongRequest(style="test", lyrics="")
    base = pipe.effective_config(request)
    assert "lora" not in base
    path, _ = write_adapter(tmp_path)
    info = pipe.load_lora(path, strength=.5)
    assert pipe.effective_config(request)["lora"] == info
    pipe.unload_lora()
    assert pipe.effective_config(request) == base
